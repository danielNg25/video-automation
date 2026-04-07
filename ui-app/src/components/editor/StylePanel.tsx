import type { SubtitleStyle } from './SubtitleOverlay';

export interface BlurConfig {
  enabled: boolean;
  mode: 'blur' | 'fill' | 'pixelate';
  strength: number;
}

interface StylePanelProps {
  style: SubtitleStyle;
  onChange: (style: SubtitleStyle) => void;
  blur?: BlurConfig;
  onBlurChange?: (blur: BlurConfig) => void;
  hasOcrRegion?: boolean;
}

const FONTS = ['Arial', 'Helvetica', 'Roboto', 'Impact', 'Georgia', 'Courier New'];

export function StylePanel({ style, onChange, blur, onBlurChange, hasOcrRegion }: StylePanelProps) {
  const update = <K extends keyof SubtitleStyle>(key: K, value: SubtitleStyle[K]) =>
    onChange({ ...style, [key]: value });

  return (
    <div className="space-y-4 pr-1">
      {/* Font & Size */}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="font-mono text-[9px] uppercase text-on-surface-variant">Font</label>
          <select
            value={style.fontName}
            onChange={(e) => update('fontName', e.target.value)}
            className="w-full bg-surface-container-lowest border border-outline-variant/15 text-xs rounded h-8 px-2 focus:ring-1 focus:ring-primary text-on-surface"
          >
            {FONTS.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <div className="flex justify-between">
            <label className="font-mono text-[9px] uppercase text-on-surface-variant">Size</label>
            <span className="font-mono text-[9px] text-primary">{style.fontSize}px</span>
          </div>
          <input
            type="range" min={12} max={72} value={style.fontSize}
            onChange={(e) => update('fontSize', Number(e.target.value))}
            className="w-full h-1 accent-primary bg-zinc-700 rounded-full appearance-none cursor-pointer"
          />
        </div>
      </div>

      {/* Outline */}
      <div className="space-y-1">
        <div className="flex justify-between">
          <label className="font-mono text-[9px] uppercase text-on-surface-variant">Outline</label>
          <span className="font-mono text-[9px] text-primary">{style.outlineWidth}px</span>
        </div>
        <input
          type="range" min={0} max={4} step={0.5} value={style.outlineWidth}
          onChange={(e) => update('outlineWidth', Number(e.target.value))}
          className="w-full h-1 accent-primary bg-zinc-700 rounded-full appearance-none cursor-pointer"
        />
      </div>

      {/* Toggles */}
      <div className="flex items-center gap-5">
        {([
          ['bold', 'Bold', style.bold] as const,
          ['shadow', 'Shadow', style.shadow] as const,
        ]).map(([key, label, value]) => (
          <div key={key} className="flex items-center gap-2">
            <button
              onClick={() => update(key, !value)}
              className={`w-7 h-3.5 rounded-full relative cursor-pointer ${value ? 'bg-primary' : 'bg-surface-container-highest'}`}
            >
              <div className={`absolute top-0.5 w-2.5 h-2.5 bg-white rounded-full transition-all ${value ? 'right-0.5' : 'left-0.5'}`} />
            </button>
            <span className="font-mono text-[9px] uppercase text-on-surface">{label}</span>
          </div>
        ))}
      </div>

      {/* Background */}
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <button
            onClick={() => update('backgroundOpacity', style.backgroundOpacity > 0 ? 0 : 90)}
            className={`w-7 h-3.5 rounded-full relative cursor-pointer ${style.backgroundOpacity > 0 ? 'bg-primary' : 'bg-surface-container-highest'}`}
          >
            <div className={`absolute top-0.5 w-2.5 h-2.5 bg-white rounded-full transition-all ${style.backgroundOpacity > 0 ? 'right-0.5' : 'left-0.5'}`} />
          </button>
          <span className="font-mono text-[9px] uppercase text-on-surface">Background</span>
        </div>
      </div>
      {style.backgroundOpacity > 0 && <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <div className="flex justify-between">
            <label className="font-mono text-[9px] uppercase text-on-surface-variant">BG Opacity</label>
            <span className="font-mono text-[9px] text-primary">{style.backgroundOpacity}%</span>
          </div>
          <input
            type="range" min={1} max={100} value={style.backgroundOpacity}
            onChange={(e) => update('backgroundOpacity', Number(e.target.value))}
            className="w-full h-1 accent-primary bg-zinc-700 rounded-full appearance-none cursor-pointer"
          />
        </div>
        <div className="space-y-1">
          <label className="font-mono text-[9px] uppercase text-on-surface-variant">BG Color</label>
          <div className="flex items-center gap-2">
            <input
              type="color"
              value={style.backgroundColor || '#000000'}
              onChange={(e) => update('backgroundColor', e.target.value)}
              className="w-8 h-8 rounded cursor-pointer bg-transparent border border-outline-variant/20"
            />
            <button
              onClick={() => update('backgroundColor', '')}
              className="font-mono text-[8px] text-zinc-500 hover:text-on-surface"
              title="Reset to black"
            >Reset</button>
          </div>
        </div>
      </div>}

      {/* Position */}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1">
          <div className="flex justify-between">
            <label className="font-mono text-[9px] uppercase text-on-surface-variant">Vertical (Y)</label>
            <span className="font-mono text-[9px] text-primary">{style.marginV}px</span>
          </div>
          <input
            type="range" min={0} max={1920} value={style.marginV}
            onChange={(e) => update('marginV', Number(e.target.value))}
            className="w-full h-1 accent-primary bg-zinc-700 rounded-full appearance-none cursor-pointer"
          />
        </div>
        <div className="space-y-1">
          <div className="flex justify-between">
            <label className="font-mono text-[9px] uppercase text-on-surface-variant">Horizontal (X)</label>
            <span className="font-mono text-[9px] text-primary">{style.marginH}px</span>
          </div>
          <input
            type="range" min={-200} max={200} value={style.marginH}
            onChange={(e) => update('marginH', Number(e.target.value))}
            className="w-full h-1 accent-primary bg-zinc-700 rounded-full appearance-none cursor-pointer"
          />
        </div>
      </div>

      {/* Coordinate display */}
      <div className="flex gap-3 px-2 py-1.5 bg-surface-container-lowest rounded border border-outline-variant/10">
        <span className="font-mono text-[9px] text-on-surface-variant">
          X: <span className="text-on-surface">{style.marginH >= 0 ? '+' : ''}{style.marginH}px</span>
        </span>
        <span className="font-mono text-[9px] text-on-surface-variant">
          Y: <span className="text-on-surface">+{style.marginV}px</span>
        </span>
      </div>

      {/* Blur Config */}
      {blur && onBlurChange && (
        <div className="space-y-2 pt-3 border-t border-outline-variant/10">
          <div className="flex items-center gap-2">
            <button
              onClick={() => onBlurChange({ ...blur, enabled: !blur.enabled })}
              className={`w-7 h-3.5 rounded-full relative cursor-pointer ${blur.enabled ? 'bg-primary' : 'bg-surface-container-highest'}`}
            >
              <div className={`absolute top-0.5 w-2.5 h-2.5 bg-white rounded-full transition-all ${blur.enabled ? 'right-0.5' : 'left-0.5'}`} />
            </button>
            <span className="font-mono text-[9px] uppercase text-on-surface">Blur Original Subs</span>
            {!hasOcrRegion && <span className="text-[8px] text-zinc-600 font-mono">(no OCR data)</span>}
          </div>
          {blur.enabled && hasOcrRegion && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="font-mono text-[9px] uppercase text-on-surface-variant">Mode</label>
                <select value={blur.mode} onChange={e => onBlurChange({ ...blur, mode: e.target.value as BlurConfig['mode'] })}
                  className="w-full bg-surface-container-lowest border border-outline-variant/15 text-xs rounded h-8 px-2 focus:ring-1 focus:ring-primary text-on-surface">
                  <option value="blur">Gaussian</option>
                  <option value="pixelate">Pixelate</option>
                  <option value="fill">Solid Fill</option>
                </select>
              </div>
              <div className="space-y-1">
                <div className="flex justify-between">
                  <label className="font-mono text-[9px] uppercase text-on-surface-variant">Strength</label>
                  <span className="font-mono text-[9px] text-primary">{blur.strength}</span>
                </div>
                <input type="range" min={5} max={30} value={blur.strength}
                  onChange={e => onBlurChange({ ...blur, strength: Number(e.target.value) })}
                  className="w-full h-1 accent-primary bg-zinc-700 rounded-full appearance-none cursor-pointer" />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
