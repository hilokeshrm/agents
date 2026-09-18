/** Client-side mirror of calc_engine.py — preview only; API is source of truth. */

export function salesRevenueK(eauKpcs: number, distyAsp: number): number {
  return eauKpcs * distyAsp;
}

export function adjustedRevenueK(salesK: number, confidence: number): number {
  return salesK * confidence;
}

export function calibratedConfidence(
  base: number,
  factors: Array<{ applies: boolean; confidence_adjustment_pct: number }>,
): number {
  const totalPct = factors.filter((f) => f.applies).reduce((s, f) => s + f.confidence_adjustment_pct, 0);
  return Math.max(0, Math.min(1, base + totalPct / 100));
}

export function money(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 1 })}K`;
}
