import { useCallback, useEffect, useState } from 'react';
import {
  applyPalette,
  getInitialPalette,
  type DesignPaletteId,
} from './designThemes';

export function useDesignPalette() {
  const [palette, setPalette] = useState<DesignPaletteId>(() => getInitialPalette());

  useEffect(() => {
    applyPalette(palette);
  }, [palette]);

  const onSelect = useCallback((id: DesignPaletteId) => {
    setPalette(id);
    applyPalette(id);
  }, []);

  return { palette, onSelect };
}
