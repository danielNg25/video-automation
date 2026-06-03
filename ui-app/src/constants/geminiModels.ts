export const GEMINI_TTS_MODELS = [
  { id: 'gemini-2.5-flash-preview-tts', label: 'Gemini 2.5 Flash (faster, cheaper)' },
  { id: 'gemini-2.5-pro-preview-tts',   label: 'Gemini 2.5 Pro (higher quality)' },
] as const;

export type GeminiTTSModelId = (typeof GEMINI_TTS_MODELS)[number]['id'];

export const DEFAULT_GEMINI_TTS_MODEL: GeminiTTSModelId = 'gemini-2.5-flash-preview-tts';

/** localStorage key that holds the user's last picked Gemini model. */
export const GEMINI_MODEL_STORAGE_KEY = 'gemini_tts_model';
