export type DesignPaletteId =
  | 'classic-blue'
  | 'royal-purple'
  | 'earth-autumn'
  | 'forest-teal'
  | 'corporate-light'
  | 'rose-maroon'
  | 'gold-forest'
  | 'midnight-purple';

export type DesignPalette = {
  id: DesignPaletteId;
  name: string;
  tagline: string;
  preview: {
    sidebar: string;
    main: string;
    accent: string;
    accent2: string;
  };
  previewDark: {
    sidebar: string;
    main: string;
    accent: string;
    accent2: string;
  };
};

const STORAGE_KEY = 'ot-palette';

export const CANVAS = {
  light: { bg: '#f4f1ea', surface: '#ffffff' },
  dark: { bg: '#141414', surface: '#1e1e1e' },
} as const;

export const DESIGN_PALETTES: DesignPalette[] = [
  {
    id: 'classic-blue',
    name: 'Classic Blue',
    tagline: 'Navy · blue accents · light & dark',
    preview: { sidebar: '#1e3a5f', main: CANVAS.light.bg, accent: '#2563eb', accent2: '#60a5fa' },
    previewDark: { sidebar: '#152238', main: CANVAS.dark.bg, accent: '#3b82f6', accent2: '#60a5fa' },
  },
  {
    id: 'royal-purple',
    name: 'Royal Purple',
    tagline: 'Violet rail · lavender · light & dark',
    preview: { sidebar: '#4c1d95', main: CANVAS.light.bg, accent: '#7c3aed', accent2: '#c4b5fd' },
    previewDark: { sidebar: '#2e1065', main: CANVAS.dark.bg, accent: '#8b5cf6', accent2: '#a78bfa' },
  },
  {
    id: 'earth-autumn',
    name: 'Earth Autumn',
    tagline: 'Warm brown · peach · light & dark',
    preview: { sidebar: '#5c3d2e', main: CANVAS.light.bg, accent: '#c2410c', accent2: '#fb923c' },
    previewDark: { sidebar: '#3d2818', main: CANVAS.dark.bg, accent: '#ea580c', accent2: '#fb923c' },
  },
  {
    id: 'forest-teal',
    name: 'Forest Teal',
    tagline: 'Deep teal · mint · light & dark',
    preview: { sidebar: '#134e4a', main: CANVAS.light.bg, accent: '#0d9488', accent2: '#5eead4' },
    previewDark: { sidebar: '#0f3330', main: CANVAS.dark.bg, accent: '#14b8a6', accent2: '#5eead4' },
  },
  {
    id: 'corporate-light',
    name: 'Corporate Light',
    tagline: 'Clean chrome · blue · light & dark',
    preview: { sidebar: '#ffffff', main: CANVAS.light.bg, accent: '#3b82f6', accent2: '#93c5fd' },
    previewDark: { sidebar: '#161b22', main: CANVAS.dark.bg, accent: '#58a6ff', accent2: '#79b8ff' },
  },
  {
    id: 'rose-maroon',
    name: 'Rose Maroon',
    tagline: 'Burgundy · blush · light & dark',
    preview: { sidebar: '#7f1d1d', main: CANVAS.light.bg, accent: '#be123c', accent2: '#fda4af' },
    previewDark: { sidebar: '#4c0519', main: CANVAS.dark.bg, accent: '#f43f5e', accent2: '#fb7185' },
  },
  {
    id: 'gold-forest',
    name: 'Gold Forest',
    tagline: 'Forest green · gold · light & dark',
    preview: { sidebar: '#1a3d30', main: CANVAS.light.bg, accent: '#3a8f6a', accent2: '#d4b06a' },
    previewDark: { sidebar: '#1a3d30', main: CANVAS.dark.bg, accent: '#3a8f6a', accent2: '#d4b06a' },
  },
  {
    id: 'midnight-purple',
    name: 'Midnight Purple',
    tagline: 'Indigo · violet glow · light & dark',
    preview: { sidebar: '#312e81', main: CANVAS.light.bg, accent: '#7c3aed', accent2: '#a78bfa' },
    previewDark: { sidebar: '#1e1b4b', main: CANVAS.dark.bg, accent: '#8b5cf6', accent2: '#a78bfa' },
  },
];

export const DEFAULT_PALETTE: DesignPaletteId = 'gold-forest';

export function getInitialPalette(): DesignPaletteId {
  if (typeof window === 'undefined') return DEFAULT_PALETTE;
  const stored = localStorage.getItem(STORAGE_KEY);
  if (DESIGN_PALETTES.some((p) => p.id === stored)) return stored as DesignPaletteId;
  return DEFAULT_PALETTE;
}

export function applyPalette(id: DesignPaletteId) {
  document.documentElement.setAttribute('data-palette', id);
  localStorage.setItem(STORAGE_KEY, id);
}

export function getPaletteMeta(id: DesignPaletteId): DesignPalette {
  return DESIGN_PALETTES.find((p) => p.id === id) ?? DESIGN_PALETTES[6];
}
