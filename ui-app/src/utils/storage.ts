/**
 * Browser localStorage helpers for persisting API keys and preferences.
 */

const PREFIX = 'douyin_pipeline_';

export function storageGet(key: string): string {
  try {
    return localStorage.getItem(PREFIX + key) || '';
  } catch {
    return '';
  }
}

export function storageSet(key: string, value: string): void {
  try {
    localStorage.setItem(PREFIX + key, value);
  } catch {
    // localStorage unavailable (SSR, private browsing quota exceeded)
  }
}

export function storageRemove(key: string): void {
  try {
    localStorage.removeItem(PREFIX + key);
  } catch {
    // ignore
  }
}

// --- Typed accessors for specific settings ---

export interface LLMApiKeys {
  anthropic: string;
  openai: string;
  deepseek: string;
}

export function loadApiKeys(): LLMApiKeys {
  return {
    anthropic: storageGet('api_key_anthropic'),
    openai: storageGet('api_key_openai'),
    deepseek: storageGet('api_key_deepseek'),
  };
}

export function saveApiKey(provider: string, key: string): void {
  storageSet(`api_key_${provider}`, key);
}

export function loadLLMPrefs(): { backend: string; model: string } {
  return {
    backend: storageGet('llm_backend') || 'anthropic',
    model: storageGet('llm_model') || 'claude-sonnet-4-20250514',
  };
}

export function saveLLMPrefs(backend: string, model: string): void {
  storageSet('llm_backend', backend);
  storageSet('llm_model', model);
}
