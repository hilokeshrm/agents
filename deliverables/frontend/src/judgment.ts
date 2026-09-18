import { calibratedConfidence } from './calc';
import type { ConfidenceFactor, ConfidenceResult } from './types';

/** Mirrors opptrack POC MOCK scorer — frontend-only, no API. */
const RUBRIC_KEYS = [
  'stage_status_mismatch',
  'named_competitor_threat',
  'design_win_lock_in',
  'early_stage_optimism',
  'customer_concentration',
  'submitter_calibration',
] as const;

export function mockScoreConfidence(project: Record<string, unknown>): ConfidenceFactor[] {
  const designStatus = String(project.design_status || '').toLowerCase();
  const stage = String(project.stage || '').toLowerCase();
  const hasCompetitor = Boolean(project.competitor_part);
  const confidence = Number(project.confidence ?? 0);

  return RUBRIC_KEYS.map((key) => {
    let applies = false;
    let confidence_adjustment_pct = 0;
    let rationale = 'No supporting evidence found in context (MOCK scorer).';
    let factorConfidence = 0.3;

    if (key === 'stage_status_mismatch') {
      const mismatch =
        (designStatus.includes('win') && (stage === 'concept' || stage === 'evt')) ||
        (designStatus.includes('promotion') && (stage === 'pvt' || stage === 'dvt'));
      if (mismatch) {
        applies = true;
        confidence_adjustment_pct = -20;
        factorConfidence = 0.5;
        rationale = `Design status '${project.design_status}' looks inconsistent with stage '${project.stage}' (MOCK scorer).`;
      }
    } else if (key === 'named_competitor_threat' && hasCompetitor) {
      applies = true;
      confidence_adjustment_pct = -10;
      factorConfidence = 0.5;
      rationale = `Competitor part ${project.competitor_part} is named against this socket (MOCK scorer).`;
    } else if (key === 'design_win_lock_in' && designStatus.includes('win') && (stage === 'dvt' || stage === 'pvt')) {
      applies = true;
      confidence_adjustment_pct = 8;
      factorConfidence = 0.5;
      rationale = 'Design Win at DVT/PVT stage supports the reported confidence (MOCK scorer).';
    } else if (key === 'early_stage_optimism' && (stage === 'concept' || stage === 'evt') && confidence >= 0.5) {
      applies = true;
      confidence_adjustment_pct = -15;
      factorConfidence = 0.45;
      rationale = `Confidence of ${confidence} looks high for a ${project.stage}-stage opportunity (MOCK scorer).`;
    }

    return { key, applies, confidence_adjustment_pct, rationale, confidence: factorConfidence };
  });
}

export function scoreConfidence(project: Record<string, unknown>): ConfidenceResult {
  const base = Number(project.confidence ?? 0);
  const factors = mockScoreConfidence(project);
  return {
    mode: 'mock',
    base_confidence: base,
    calibrated_confidence: calibratedConfidence(base, factors),
    factors,
  };
}
