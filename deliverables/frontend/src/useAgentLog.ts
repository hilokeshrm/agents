import { useCallback, useState } from 'react';
import type { ActivityEntry, ActivityKind } from './agent';

let seq = 0;

export function useAgentLog() {
  const [entries, setEntries] = useState<ActivityEntry[]>([]);

  const log = useCallback((kind: ActivityKind, message: string, detail?: string) => {
    const entry: ActivityEntry = {
      id: `${Date.now()}-${++seq}`,
      kind,
      message,
      detail,
      at: new Date(),
    };
    setEntries((prev) => [entry, ...prev].slice(0, 12));
    return entry;
  }, []);

  const clear = useCallback(() => setEntries([]), []);

  return { entries, log, clear };
}

export async function simulateAgentDelay(ms = 650): Promise<void> {
  await new Promise((r) => setTimeout(r, ms));
}
