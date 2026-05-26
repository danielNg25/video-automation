import { describe, it, expect } from 'vitest';
import { specToCss } from '../SubtitleRenderer';
import type { SubtitleStyleSpec } from '../../../api/types';

const baseSpec: SubtitleStyleSpec = {
  text:       { font_name: 'Arial', font_size: 3.0, color: '#FFFFFF', bold: true },
  position:   { alignment: 'bottom-center', margin_v: 5.0, margin_h: 0.0 },
  outline:    { width: 0.15, color: '#000000' },
  shadow:     { depth: 0.05, color: '#000000' },
  background: { shape: 'none', color: '#000000', opacity: 0, radius: 0.94, padding_x: 0.83, padding_y: 0.5 },
  blur:       { enabled: false, mode: 'blur', strength: 15 },
};

describe('specToCss', () => {
  it('scales font_size by canvas height', () => {
    const css = specToCss(baseSpec, 1080, 1920);
    // 3.0% of 1920 = 57.6px
    expect(css.fontSize).toBeCloseTo(57.6, 1);
  });

  it('places subtitle at bottom for bottom-center alignment', () => {
    const css = specToCss(baseSpec, 1080, 1920);
    expect(css.bottom).toBeCloseTo(5.0 * 1920 / 100, 1);
    expect(css.top).toBeUndefined();
  });

  it('places subtitle at top for top-center alignment', () => {
    const spec = structuredClone(baseSpec);
    spec.position.alignment = 'top-center';
    const css = specToCss(spec, 1080, 1920);
    expect(css.top).toBeCloseTo(5.0 * 1920 / 100, 1);
    expect(css.bottom).toBeUndefined();
  });

  it('hides background when shape is none', () => {
    const css = specToCss(baseSpec, 1080, 1920);
    expect(css.backgroundColor).toBeFalsy();
  });

  it('emits rgba background when shape is rounded', () => {
    const spec = structuredClone(baseSpec);
    spec.background.shape = 'rounded';
    spec.background.color = '#FFFF00';
    spec.background.opacity = 90;
    const css = specToCss(spec, 1080, 1920);
    expect(css.backgroundColor).toBe('rgba(255,255,0,0.9)');
    expect(css.borderRadius).toBe(`${0.94 * 1920 / 100}px`);
  });
});
