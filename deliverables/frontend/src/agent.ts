import type { ConfidenceResult } from './types';

export type ActivityKind = 'info' | 'calc' | 'agent' | 'success' | 'warn';

export type ActivityEntry = {
  id: string;
  kind: ActivityKind;
  message: string;
  detail?: string;
  at: Date;
};

export function formatTime(d: Date): string {
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function summarizeJudgment(result: ConfidenceResult): string {
  const applied = result.factors.filter((f) => f.applies);
  if (!applied.length) return 'No factors applied';
  return applied.map((f) => `${f.key} (${f.confidence_adjustment_pct >= 0 ? '+' : ''}${f.confidence_adjustment_pct}pp)`).join(', ');
}
