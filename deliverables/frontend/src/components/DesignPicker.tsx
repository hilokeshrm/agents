import { useEffect, useRef } from 'react';
import { DESIGN_PALETTES, getPaletteMeta, type DesignPalette, type DesignPaletteId } from '../designThemes';

type Props = {
  open: boolean;
  active: DesignPaletteId;
  isDark: boolean;
  onSelect: (id: DesignPaletteId) => void;
  onClose: () => void;
};

function PreviewHalf({
  colors,
  label,
}: {
  colors: DesignPalette['preview'];
  label: string;
}) {
  return (
    <div className="design-card-half" title={label}>
      <div className="design-card-sidebar" style={{ background: colors.sidebar }} />
      <div className="design-card-main" style={{ background: colors.main }}>
        <div className="design-card-bar" style={{ background: colors.accent }} />
        <div className="design-card-blocks">
          <span style={{ background: colors.accent2 }} />
          <span style={{ background: colors.accent, opacity: 0.55 }} />
        </div>
      </div>
      <span className="design-card-mode">{label}</span>
    </div>
  );
}

export default function DesignPicker({ open, active, isDark, onSelect, onClose }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const activeMeta = getPaletteMeta(active);

  return (
    <div className="design-picker-backdrop" onClick={onClose} role="presentation">
      <div
        ref={dialogRef}
        className="design-picker"
        role="dialog"
        aria-modal="true"
        aria-labelledby="design-picker-title"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="design-picker-head">
          <div>
            <h2 id="design-picker-title">Design themes</h2>
            <p>Pick a palette, then use the sun/moon button for light or dark mode on any theme.</p>
          </div>
          <button type="button" className="icon-btn design-picker-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>

        <div className="design-picker-grid">
          {DESIGN_PALETTES.map((palette) => {
            const selected = palette.id === active;
            return (
              <button
                key={palette.id}
                type="button"
                className={`design-card ${selected ? 'selected' : ''}`}
                onClick={() => {
                  onSelect(palette.id);
                  onClose();
                }}
                aria-pressed={selected}
              >
                <div className="design-card-preview design-card-split" aria-hidden>
                  <PreviewHalf colors={palette.preview} label="Light" />
                  <PreviewHalf colors={palette.previewDark} label="Dark" />
                </div>
                <div className="design-card-meta">
                  <strong>{palette.name}</strong>
                  <span>{palette.tagline}</span>
                </div>
                {selected && <span className="design-card-badge">Active</span>}
              </button>
            );
          })}
        </div>

        <footer className="design-picker-foot">
          Current: <strong>{activeMeta.name}</strong>
          {' · '}
          Mode: <strong>{isDark ? 'Dark' : 'Light'}</strong>
        </footer>
      </div>
    </div>
  );
}
