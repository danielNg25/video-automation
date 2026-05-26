import { describe, it, expect } from 'vitest';
import { diffSpec } from '../diffSpec';
import type { SubtitleStyleSpec } from '../../api/types';

const baseSpec: SubtitleStyleSpec = {
  text:       { font_name: 'Arial', font_size: 3.0, color: '#FFFFFF', bold: true },
  position:   { alignment: 'bottom-center', margin_v: 5.0, margin_h: 0.0 },
  outline:    { width: 0.15, color: '#000000' },
  shadow:     { depth: 0.05, color: '#000000' },
  background: { shape: 'none', color: '#000000', opacity: 0, radius: 0.94, padding_x: 0.83, padding_y: 0.5 },
  blur:       { enabled: false, mode: 'blur', strength: 15 },
};

describe('diffSpec', () => {
  it('returns empty object when draft equals global', () => {
    expect(diffSpec(baseSpec, baseSpec)).toEqual({});
  });

  it('emits a single changed leaf', () => {
    const draft = structuredClone(baseSpec);
    draft.text.font_size = 5.5;
    expect(diffSpec(draft, baseSpec)).toEqual({ text: { font_size: 5.5 } });
  });

  it('emits multiple changed leaves in same group', () => {
    const draft = structuredClone(baseSpec);
    draft.background.color = '#FFFF00';
    draft.background.opacity = 90;
    expect(diffSpec(draft, baseSpec)).toEqual({
      background: { color: '#FFFF00', opacity: 90 },
    });
  });

  it('drops empty groups', () => {
    const draft = structuredClone(baseSpec);
    draft.text.color = '#FF0000';
    const result = diffSpec(draft, baseSpec);
    expect(result.position).toBeUndefined();
    expect(result.outline).toBeUndefined();
    expect(result).toEqual({ text: { color: '#FF0000' } });
  });
});
