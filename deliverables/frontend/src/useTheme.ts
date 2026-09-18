import { useCallback, useEffect, useState } from 'react';
import { applyTheme, getInitialTheme, toggleTheme, type Theme } from './theme';

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => getInitialTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const onToggle = useCallback(() => {
    setTheme((current) => toggleTheme(current));
  }, []);

  return { theme, onToggle, isDark: theme === 'dark' };
}
