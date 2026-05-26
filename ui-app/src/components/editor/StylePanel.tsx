// ui-app/src/components/editor/StylePanel.tsx — full replacement
import { useState } from 'react';
import type { SubtitleStyleSpec } from '../../api/types';

interface Props {
  spec: SubtitleStyleSpec;
  onChange: (next: SubtitleStyleSpec) => void;
  sourceW: number;   // source video width  (px)
  sourceH: number;   // source video height (px)
  hasOcrRegion?: boolean;
  onResetField?: (groupKey: keyof SubtitleStyleSpec) => void;
  onRealignToOcr?: () => void;
}

const FONTS: SubtitleStyleSpec['text']['font_name'][] = [
  'Arial', 'Roboto', 'Impact', 'Georgia', 'Courier New', 'Helvetica',
];

const ALIGN: SubtitleStyleSpec['position']['alignment'][] = [
  'top-left',    'top-center',    'top-right',
  'center-left', 'center-center', 'center-right',
  'bottom-left', 'bottom-center', 'bottom-right',
];

export function StylePanel({ spec, onChange, sourceW, sourceH, hasOcrRegion, onResetField: _onResetField, onRealignToOcr }: Props) {
  const [open, setOpen] = useState({ text: true, position: true, outline: false, shadow: false, background: false, blur: false });

  // Helpers: percentage → px (display); px → percentage (write back).
  const pctToPx = (pct: number, base: number) => Math.round(pct * base / 100);
  const pxToPct = (px: number, base: number) => px * 100 / base;

  const patch = <K extends keyof SubtitleStyleSpec>(group: K, partial: Partial<SubtitleStyleSpec[K]>) =>
    onChange({ ...spec, [group]: { ...spec[group], ...partial } });

  return (
    <div className="space-y-4 pr-1 text-on-surface">
      {/* TEXT */}
      <Section title="Text" open={open.text} onToggle={() => setOpen({ ...open, text: !open.text })}>
        <Row label="Font">
          <select value={spec.text.font_name} onChange={(e) => patch('text', { font_name: e.target.value as SubtitleStyleSpec['text']['font_name'] })}
                  className="bg-surface-container-lowest border border-outline-variant/15 text-xs rounded h-7 px-2">
            {FONTS.map(f => <option key={f} value={f}>{f}</option>)}
          </select>
        </Row>
        <SliderRow label="Size" min={12} max={120}
                   value={pctToPx(spec.text.font_size, sourceH)}
                   onChange={(px) => patch('text', { font_size: pxToPct(px, sourceH) })} />
        <Row label="Color">
          <input type="color" value={spec.text.color}
                 onChange={(e) => patch('text', { color: e.target.value })}
                 className="w-8 h-7 rounded cursor-pointer" />
        </Row>
        <Row label="Bold">
          <Toggle on={spec.text.bold} onClick={() => patch('text', { bold: !spec.text.bold })} />
        </Row>
      </Section>

      {/* POSITION */}
      <Section title="Position" open={open.position} onToggle={() => setOpen({ ...open, position: !open.position })}>
        <Row label="Alignment">
          <div className="grid grid-cols-3 gap-1">
            {ALIGN.map(a => (
              <button key={a}
                onClick={() => patch('position', { alignment: a })}
                className={`w-6 h-6 rounded border ${spec.position.alignment === a ? 'bg-primary border-primary' : 'border-outline-variant/15'}`}
                title={a} />
            ))}
          </div>
        </Row>
        <SliderRow label="Vertical" min={0} max={Math.round(sourceH * 0.95)}
                   value={pctToPx(spec.position.margin_v, sourceH)}
                   onChange={(px) => patch('position', { margin_v: pxToPct(px, sourceH) })} />
        <SliderRow label="Horizontal" min={-Math.round(sourceW * 0.4)} max={Math.round(sourceW * 0.4)}
                   value={pctToPx(spec.position.margin_h, sourceW)}
                   onChange={(px) => patch('position', { margin_h: pxToPct(px, sourceW) })} />
        {hasOcrRegion && onRealignToOcr && (
          <button onClick={onRealignToOcr}
                  className="text-[10px] text-on-surface-variant hover:text-on-surface mt-1">
            ↺ Re-align to OCR region
          </button>
        )}
      </Section>

      {/* OUTLINE */}
      <Section title="Outline" open={open.outline} onToggle={() => setOpen({ ...open, outline: !open.outline })}>
        <SliderRow label="Width" min={0} max={Math.round(sourceH * 0.01)}
                   step={1}
                   value={pctToPx(spec.outline.width, sourceH)}
                   onChange={(px) => patch('outline', { width: pxToPct(px, sourceH) })} />
        <Row label="Color">
          <input type="color" value={spec.outline.color}
                 onChange={(e) => patch('outline', { color: e.target.value })}
                 className="w-8 h-7 rounded cursor-pointer" />
        </Row>
      </Section>

      {/* SHADOW */}
      <Section title="Shadow" open={open.shadow} onToggle={() => setOpen({ ...open, shadow: !open.shadow })}>
        <SliderRow label="Depth" min={0} max={Math.round(sourceH * 0.01)}
                   value={pctToPx(spec.shadow.depth, sourceH)}
                   onChange={(px) => patch('shadow', { depth: pxToPct(px, sourceH) })} />
        <Row label="Color">
          <input type="color" value={spec.shadow.color}
                 onChange={(e) => patch('shadow', { color: e.target.value })}
                 className="w-8 h-7 rounded cursor-pointer" />
        </Row>
      </Section>

      {/* BACKGROUND */}
      <Section title="Background" open={open.background} onToggle={() => setOpen({ ...open, background: !open.background })}>
        <Row label="Shape">
          <select value={spec.background.shape}
                  onChange={(e) => patch('background', { shape: e.target.value as SubtitleStyleSpec['background']['shape'] })}
                  className="bg-surface-container-lowest border border-outline-variant/15 text-xs rounded h-7 px-2">
            <option value="none">None</option>
            <option value="rect">Rectangle</option>
            <option value="rounded">Rounded</option>
          </select>
        </Row>
        {spec.background.shape !== 'none' && (
          <>
            <Row label="Color">
              <input type="color" value={spec.background.color}
                     onChange={(e) => patch('background', { color: e.target.value })}
                     className="w-8 h-7 rounded cursor-pointer" />
            </Row>
            <SliderRow label="Opacity" min={0} max={100} unit="%"
                       value={spec.background.opacity}
                       onChange={(v) => patch('background', { opacity: v })} />
            {spec.background.shape === 'rounded' && (
              <SliderRow label="Radius" min={0} max={Math.round(sourceH * 0.05)}
                         value={pctToPx(spec.background.radius, sourceH)}
                         onChange={(px) => patch('background', { radius: pxToPct(px, sourceH) })} />
            )}
            <SliderRow label="Padding X" min={0} max={Math.round(sourceW * 0.05)}
                       value={pctToPx(spec.background.padding_x, sourceW)}
                       onChange={(px) => patch('background', { padding_x: pxToPct(px, sourceW) })} />
            <SliderRow label="Padding Y" min={0} max={Math.round(sourceH * 0.05)}
                       value={pctToPx(spec.background.padding_y, sourceH)}
                       onChange={(px) => patch('background', { padding_y: pxToPct(px, sourceH) })} />
          </>
        )}
      </Section>

      {/* BLUR */}
      <Section title="Blur" open={open.blur} onToggle={() => setOpen({ ...open, blur: !open.blur })}>
        <Row label="Enabled">
          <Toggle on={spec.blur.enabled} onClick={() => patch('blur', { enabled: !spec.blur.enabled })} />
        </Row>
        {spec.blur.enabled && (
          <>
            <Row label="Mode">
              <select value={spec.blur.mode}
                      onChange={(e) => patch('blur', { mode: e.target.value as SubtitleStyleSpec['blur']['mode'] })}
                      className="bg-surface-container-lowest border border-outline-variant/15 text-xs rounded h-7 px-2">
                <option value="blur">Gaussian</option>
                <option value="pixelate">Pixelate</option>
                <option value="fill">Solid Fill</option>
              </select>
            </Row>
            <SliderRow label="Strength" min={5} max={30}
                       value={spec.blur.strength}
                       onChange={(v) => patch('blur', { strength: v })} />
          </>
        )}
      </Section>
    </div>
  );
}

// ── Small inline components ──────────────────────────────────────────

function Section({ title, open, onToggle, children }: { title: string; open: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <button onClick={onToggle} className="w-full flex items-center gap-2 text-[10px] uppercase font-mono tracking-tighter font-bold text-on-surface">
        <span className="material-symbols-outlined text-sm">{open ? 'expand_more' : 'chevron_right'}</span>
        {title}
      </button>
      {open && <div className="space-y-2 pl-2">{children}</div>}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <label className="font-mono text-[9px] uppercase text-on-surface-variant w-20">{label}</label>
      <div className="flex-1 flex justify-end">{children}</div>
    </div>
  );
}

function SliderRow({ label, value, min, max, step = 1, unit = 'px', onChange }: { label: string; value: number; min: number; max: number; step?: number; unit?: string; onChange: (v: number) => void }) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between">
        <label className="font-mono text-[9px] uppercase text-on-surface-variant">{label}</label>
        <span className="font-mono text-[9px] text-primary">{value}{unit}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(Number(e.target.value))}
             className="w-full h-1 accent-primary bg-zinc-700 rounded-full appearance-none cursor-pointer" />
    </div>
  );
}

function Toggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick}
            className={`w-7 h-3.5 rounded-full relative cursor-pointer ${on ? 'bg-primary' : 'bg-surface-container-highest'}`}>
      <div className={`absolute top-0.5 w-2.5 h-2.5 bg-white rounded-full transition-all ${on ? 'right-0.5' : 'left-0.5'}`} />
    </button>
  );
}
