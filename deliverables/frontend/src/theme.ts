export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'ot-theme';

export function getInitialTheme(): Theme {
  if (typeof window === 'undefined') return 'dark';
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return 'dark';
}

export function applyTheme(theme: Theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem(STORAGE_KEY, theme);
}

export function toggleTheme(current: Theme): Theme {
  const next = current === 'light' ? 'dark' : 'light';
  applyTheme(next);
  return next;
}
