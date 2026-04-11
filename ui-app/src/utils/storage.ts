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
  elevenlabs: string;
  google: string;
  [key: string]: string;
}

export function loadApiKeys(): LLMApiKeys {
  return {
    anthropic: storageGet('api_key_anthropic'),
    openai: storageGet('api_key_openai'),
    deepseek: storageGet('api_key_deepseek'),
    elevenlabs: storageGet('api_key_elevenlabs'),
    google: storageGet('api_key_google'),
  };
}

export function saveApiKey(provider: string, key: string): void {
  storageSet(`api_key_${provider}`, key);
}

export function loadLLMPrefs(): { backend: string; model: string } {
  return {
    backend: storageGet('llm_backend') || 'deepseek',
    model: storageGet('llm_model') || 'deepseek-chat',
  };
}

export function saveLLMPrefs(backend: string, model: string): void {
  storageSet('llm_backend', backend);
  storageSet('llm_model', model);
}
