# Translation Profile Export / Import (JSON)

## Goal

Add per-profile JSON export and import to the Translation Profiles page so a user can move a profile between machines, share one with a collaborator, or back up a profile they're about to edit. Single round-trip lossless: export → save → import → identical profile on disk.

## Why

Today, the only way to move a translation profile between machines is to copy the YAML file out of `config/translation_profiles/` manually. That works for the maintainer but doesn't scale to anyone using the web UI — the YAML directory isn't surfaced anywhere in the app. Two buttons on the page close that gap without any BE work.

## Non-goals

- **Batch export / import** (single ZIP of all profiles). Per-profile is the natural unit; batch is a follow-up if the profile count ever grows.
- **YAML import / export**. JSON is the FE-native format and matches the existing API response shape. YAML stays the on-disk source-of-truth via the existing CRUD.
- **Versioning or schema metadata** in the exported file. The file is the raw API body. If the schema changes in a future PR, that PR owns the migration story.
- **Sharing via URL / cloud storage**. Local file download / upload only.
- **Cross-account portability or auth**. Single-user assumption (matches the rest of the app).
- **Overwrite-on-import**. Spec'd choice: name-conflict triggers an inline rename prompt, never silent replace.
- **Auto-import-and-edit flow**. Import lands the profile as a snapshot; user can then open it via the existing selection UI and Edit.

## Architecture

Pure FE feature. The existing BE endpoints already cover everything:

```
                            Translation Profiles page
                            (ui-app/src/pages/TranslationProfiles.tsx)
                                            │
              ┌──── Export ────────────┐    │   ┌──── Import ──────────────┐
              ▼                        │    │   │                          ▼
   getProfile(name)            (existing      <input type="file"           createProfile(parsed)
   GET /api/profiles/{name}     client fn)    accept=".json">              POST /api/profiles
              │                                       │                      │
              ▼                                       ▼                      │
   serialise → Blob                       FileReader.readAsText               │
              │                                       │                      │
              ▼                                       ▼                      │
   <a download={name}.json>                JSON.parse                         │
   URL.createObjectURL                              │                        │
                                                    ▼                        │
                                          validateProfileJson(obj)            │
                                          ✗ → inline error                    │
                                          ✓ → createProfile(profile)            │
                                                                              │
                                                              ┌───────────────┘
                                                              ▼
                                                   201 → refresh list, select new
                                                   409 → inline rename prompt
                                                          (default: '{name}-imported')
                                                          on Confirm → re-post w/ renamed body
                                                          on Cancel → drop import
```

No new BE routes. No new dependencies. Adds one small client helper for download + one for validation; both live next to the page that uses them.

## Components

### `ui-app/src/utils/profileJson.ts` — new

Two pure helpers, easy to test in isolation:

```ts
import type { TranslationProfile } from '../api/types';

/** Trigger a browser download of a JSON file for the given profile body. */
export function downloadProfileJson(profile: TranslationProfile): void;

/** Validate that a parsed JSON value matches the TranslationProfile shape.
 *  Returns either { ok: true; profile } or { ok: false; reason }. */
export type ValidateResult =
  | { ok: true; profile: TranslationProfile }
  | { ok: false; reason: string };

export function validateProfileJson(raw: unknown): ValidateResult;
```

Behaviour:

- `downloadProfileJson`: builds a `Blob` of `JSON.stringify(profile, null, 2)`, creates an `URL.createObjectURL(blob)`, synthesises a hidden `<a download={`${profile.name}.json`} href={url}>`, clicks it, then revokes the object URL on the next tick. No state, no React.
- `validateProfileJson`: walks the 6 required fields:
  - `name` — non-empty string
  - `description` — string (empty allowed)
  - `target_language` — non-empty string
  - `source_language` — non-empty string
  - `style_guide` — string (empty allowed)
  - `example_pairs` — array; each entry an object with string `source` and string `target`
  Returns the first failure as `{ ok: false, reason: "Missing field: <name>" }` or `"Field X has wrong type: ..."`. Doesn't enforce server-side rules (e.g. uniqueness, file-system safety of the name) — those surface naturally from the BE on POST.

### `ui-app/src/pages/TranslationProfiles.tsx` — modified

Two new affordances and one inline rename form:

1. **Export button** — appears in the right-pane header next to Edit / Delete when a profile is selected (and not in edit/new mode). Click → fetches the full profile body via the existing `getProfile(name)` API client and hands it to `downloadProfileJson`.

2. **Import button** — appears in the left-pane header next to "New Profile". Click → triggers a hidden `<input type="file" accept=".json">`. On file selection:
   - `FileReader.readAsText` → `JSON.parse` (wrapped in try/catch; "Invalid JSON" on failure).
   - `validateProfileJson` (surface returned `reason` on failure).
   - `createProfile(profile)`. On 201, refresh the profile list, select the new profile. On 409 (name conflict), switch the left pane into a small inline rename form.

3. **Inline rename form** — appears when import hit a 409. Renders a labelled `<input>` pre-filled with `${parsedName}-imported` plus Confirm + Cancel buttons. Confirm → re-POST with `{ ...profile, name: chosenName }`; loops back to 201/409 handling. Cancel → discards the import; left pane reverts.

   The form lives inline (no modal) to keep the implementation surface small and consistent with how Edit currently swaps the right pane.

### `ui-app/src/api/client.ts` — one small addition

`getProfile(name)`, `createProfile(profile)`, `updateProfile(name, profile)`, `deleteProfileApi(name)`, and `getProfiles()` all already exist and are exported. The export path uses `getProfile` as-is.

The import path needs to distinguish HTTP 409 (name conflict — triggers the rename form) from other failures (display as a generic error). The existing `createProfile` helper goes through a shared `request()` wrapper that throws an `Error` with just the response body — the status code is lost, and detecting 409 would require substring-matching the BE's error wording. To keep that coupling out, add one sibling helper:

```ts
export type CreateProfileResult =
  | { status: 201; profile: TranslationProfile }
  | { status: 409; message: string }
  | { status: number; message: string };

export async function createProfileWithStatus(
  profile: TranslationProfile,
): Promise<CreateProfileResult>;
```

Behaviour: same POST as `createProfile`, but returns `{ status, profile }` on 201 or `{ status, message }` on any non-2xx. Unwraps FastAPI's `{ detail: '...' }` body so callers see the human message; falls back to raw text if the body isn't JSON. The existing `createProfile` stays untouched (still used by the page's Save flow).

## Data flow

```
EXPORT
  click Export → getProfile(name) → TranslationProfile
       → downloadProfileJson(profile)
       → user gets ${name}.json in Downloads

IMPORT
  click Import → file input opens
  user picks file → FileReader.readAsText → JSON.parse
       ✗ parse error → inline "Invalid JSON: <message>" in the left pane
       ✓ parsed → validateProfileJson
            ✗ schema error → inline "<reason>" in the left pane
            ✓ valid → createProfile(profile)
                 201 → refresh list, setSelectedName(name), clear import error
                 409 → set importedProfileBuffer + show inline rename form (default `${name}-imported`)
                 other error → inline "<status text>"

  rename form Confirm → createProfile({ ...importedProfileBuffer, name: chosenName })
       loops back to 201/409/other handling
  rename form Cancel → clear importedProfileBuffer, exit form
```

## Behavior

| Scenario | Result |
|---|---|
| Click Export with a profile selected | Browser downloads `{name}.json`; profile body is the same JSON the API returns. |
| Click Export with no profile selected | Button isn't rendered (the right-pane header only shows it when `selectedName` is set and not editing). |
| Import a valid JSON, name doesn't exist | Profile created (201), list refreshes, new profile selected and shown in the right pane. |
| Import a valid JSON, name exists | 409 caught; left pane shows the rename form with `${name}-imported` pre-filled. |
| Rename form Confirm with a unique name | Re-POSTs; 201 path runs. |
| Rename form Confirm with another conflicting name | 409 again — form stays open, error displayed, user tries another name. |
| Rename form Cancel | Import buffer discarded; left pane returns to normal. |
| Import a malformed JSON file | Inline error "Invalid JSON: <parser message>". No POST attempted. |
| Import a JSON missing `style_guide` | Inline error "Missing field: style_guide". No POST attempted. |
| Import a JSON whose `example_pairs[0].source` is a number | Inline error "Field example_pairs[0].source: expected string". |
| Import a JSON whose `name` contains shell-unsafe chars (e.g. `../`) | The FE-side validator accepts it (string is non-empty); the BE rejects on POST with whatever error it already returns. Surface that error inline. |

## Error handling

- **Parse errors** (`JSON.parse` throws): caught, message extracted (`err.message`), shown inline as `"Invalid JSON: <message>"`.
- **Schema errors** (`validateProfileJson` returns `{ ok: false }`): the `reason` string is shown inline verbatim. The validator's reasons are pre-written so they read OK to a human (no raw `TypeError` text).
- **HTTP errors from POST**: existing error-handling pattern from the page's other mutations — surface the response body text in the error banner that already exists at the top of the right pane.
- **FileReader errors** (rare; corrupt file, IO failure): surface as `"Could not read file: <message>"`.
- **Concurrent import attempts** (user spams Import → picks two files quickly): the second file's POST runs after the first; race is benign because each is independent. No special handling.

## Testing

### Unit — `ui-app/src/utils/__tests__/profileJson.test.ts` (new)

vitest. Mock `URL.createObjectURL` + `URL.revokeObjectURL` for download tests.

- `test_validateProfileJson_accepts_well_formed_profile`
- `test_validateProfileJson_rejects_missing_name`
- `test_validateProfileJson_rejects_missing_style_guide`
- `test_validateProfileJson_rejects_non_array_example_pairs`
- `test_validateProfileJson_rejects_example_pair_with_non_string_source`
- `test_validateProfileJson_rejects_null_and_non_object_input`
- `test_downloadProfileJson_creates_object_url_and_clicks_anchor_with_correct_filename`
- `test_downloadProfileJson_revokes_object_url_after_click`

### Component — `ui-app/src/pages/__tests__/TranslationProfiles.test.tsx` (new or extended)

Mock `fetch` for the GET/POST round-trips.

- `test_export_button_renders_only_when_profile_selected_and_not_editing`
- `test_export_click_fetches_profile_then_triggers_download`
- `test_import_button_opens_hidden_file_input`
- `test_import_invalid_json_shows_inline_error_no_post`
- `test_import_missing_field_shows_inline_error_no_post`
- `test_import_happy_path_posts_and_refreshes_list`
- `test_import_409_shows_rename_form_with_default_suffix`
- `test_import_rename_confirm_re_posts_with_new_name`
- `test_import_rename_cancel_clears_buffer`

If `TranslationProfiles.test.tsx` doesn't exist, create it with a minimal `renderPage()` helper that mocks `react-router-dom` (same pattern as other page tests in this codebase).

## Verification

1. `cd ui-app && npx vitest run` — full FE suite passes, +17 tests.
2. `cd ui-app && npx tsc --noEmit` — clean.
3. **Manual smoke (after merge):**
   - Open Translation Profiles → select `dramatic-vi` → click Export → file `dramatic-vi.json` downloads with the full body.
   - Click Import → pick `dramatic-vi.json` → inline rename form appears with `dramatic-vi-imported` pre-filled → Confirm → new profile appears in the list.
   - Click Import → pick a non-JSON file → inline "Invalid JSON" error.
   - Click Import → pick a JSON missing `style_guide` → inline "Missing field: style_guide" error.

## Files touched

- New: `ui-app/src/utils/profileJson.ts` (~50 lines).
- New: `ui-app/src/utils/__tests__/profileJson.test.ts` (~90 lines, 8 tests).
- Modified: `ui-app/src/pages/TranslationProfiles.tsx` — Export + Import buttons, hidden file input, inline rename form, import-error state. Net ~80 lines.
- New or modified: `ui-app/src/pages/__tests__/TranslationProfiles.test.tsx` — 9 component tests covering the export + import flows.
- Modified: `ui-app/src/api/client.ts` — append one helper `createProfileWithStatus` (status-aware POST). The existing `createProfile` stays as-is.
- Docs: `CHANGELOG.md`, `README.md`.

## Out of scope (future ideas, not in this PR)

- Batch export (download all profiles as a ZIP).
- Drag-and-drop file area in addition to the button + file picker.
- An "import from URL" mode for sharing via gist or similar.
- A schema-version field on the exported JSON for forward-compat migrations.
- BE storage of "shared" profiles separately from the user's own list.
