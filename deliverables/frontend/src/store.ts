import { actingIdentity, apiGet, apiPost, apiUpload } from './api';
import { adjustedRevenueK, salesRevenueK } from './calc';
import type { AccessMatrix, CommitResult, ConfidenceResult, DryRun, Impact, Me, ObservedActor, Project,
  ProjectInput, Proposal, Registry, ResolveInput, Rollup, RubricDraft, RubricVersion,
  SnapshotSummary, StateEvent, TransitionInput, RubricFeedback } from './types';

type OpportunityRead = Omit<Project, 'bucket' | 'calibrated_confidence' | 'comments' | 'loss_reason' | 'unit_per_set'> & {
  unit_set: number | null;
};

function mapProject(row: OpportunityRead): Project {
  return {
    ...row,
    id: String(row.id),
    unit_per_set: row.unit_set,
    bucket: 'project_track',
  };
}

export async function listProjects(): Promise<Project[]> {
  const rows = await apiGet<OpportunityRead[]>('/opportunities');
  return rows.map(mapProject);
}

export function computeRollup(list: Project[]): Rollup {
  const by_region: Rollup['by_region'] = {};
  let totalSales = 0;
  let totalAdjusted = 0;
  for (const project of list) {
    totalSales += project.sales_revenue_k;
    totalAdjusted += project.adjusted_revenue_k;
    by_region[project.region] ??= { sales_revenue_k: 0, adjusted_revenue_k: 0 };
    by_region[project.region].sales_revenue_k += project.sales_revenue_k;
    by_region[project.region].adjusted_revenue_k += project.adjusted_revenue_k;
  }
  return {
    total_sales_revenue_k: totalSales,
    total_adjusted_revenue_k: totalAdjusted,
    stretch_revenue_k: totalSales,
    projection_revenue_k: totalAdjusted,
    project_count: list.length,
    by_region,
  };
}

export async function createProject(input: ProjectInput): Promise<Project> {
  const row = await apiPost<OpportunityRead>('/opportunities', {
    ...input,
    end_customer: input.end_customer ?? '',
    application: input.application ?? null,
    product_line: input.product_line ?? null,
    mp_date: input.mp_date ?? null,
    unit_set: input.unit_per_set ?? null,
    nre_charge_k: input.nre_charge_k ?? null,
    owner: input.owner,
    evidence: input.evidence ?? null,
    confidence_rationale: input.confidence_rationale,
  });
  return mapProject(row);
}

export async function listPendingProposals(): Promise<Proposal[]> {
  return apiGet<Proposal[]>('/proposals?status=pending');
}

export async function suggestConfidence(id: string): Promise<{ proposal: Proposal; result: ConfidenceResult }> {
  const proposal = await apiPost<Proposal>(`/opportunities/${id}/request-review`);
  return {
    proposal,
    result: {
      mode: 'backend',
      base_confidence: proposal.base_confidence,
      calibrated_confidence: proposal.proposed_confidence,
      factors: proposal.factors,
    },
  };
}

export async function applyConfidence(proposalId: string): Promise<void> {
  await apiPost(`/proposals/${proposalId}/resolve`, { action: 'approve' });
}

export async function runAgentScan(): Promise<void> {
  await apiPost('/runs');
}

export function projectRevenue(eauKpcs: number, distyAsp: number, confidence: number) {
  const sales = salesRevenueK(eauKpcs, distyAsp);
  return { sales, adjusted: adjustedRevenueK(sales, confidence) };
}

// --------------------------------------------------------------------------- //
// Review decisions and lifecycle transitions
// --------------------------------------------------------------------------- //

/**
 * The vocabularies and canonical values the API enforces. Fetched once and
 * shared, so no screen has to hardcode a status, a stage or a reason code --
 * a hardcoded list is one backend edit away from offering a value the server
 * rejects.
 */
let registryPromise: Promise<Registry> | null = null;

export function getRegistry(): Promise<Registry> {
  registryPromise ??= apiGet<Registry>('/registry');
  return registryPromise;
}

export async function getGrants(): Promise<Record<string, string>> {
  return (await getMe()).grants;
}

/**
 * Approve, reject or override a proposal. An override carries the reviewer's
 * own value and a code from the override_reason vocabulary -- the API rejects
 * one without the other, so both are required here rather than optional.
 */
export async function resolveProposal(proposalId: string, input: ResolveInput): Promise<void> {
  await apiPost(`/proposals/${proposalId}/resolve`, {
    action: input.action,
    value: input.action === 'override' ? input.value : null,
    // A reason travels with an override (override_reason), a rejection
    // (rejection_reason) and a lifecycle or reconciliation approval to Lost
    // (loss_reason); the API enforces which vocabulary applies.
    reason_code: input.reason_code || null,
    note: input.note?.trim() ? input.note.trim() : null,
    rejected_factors: input.rejected_factors ?? null,
  });
}

/**
 * The only sanctioned way to change design status or stage (WBS 9.2): it writes
 * a state_history event rather than overwriting a column, which is what makes
 * time-in-stage, stall detection and win rate computable later.
 */
export async function transitionOpportunity(id: string, input: TransitionInput): Promise<StateEvent> {
  return apiPost<StateEvent>(`/opportunities/${id}/transition`, {
    field: input.field,
    to_value: input.to_value,
    // Falls back to the acting identity so a write can never record a blank
    // actor -- the audit chain is only worth having if every row names someone.
    actor: input.actor || actingIdentity.actor,
    reason_code: input.reason_code ?? null,
  });
}

export function listStateHistory(id: string): Promise<StateEvent[]> {
  return apiGet<StateEvent[]>(`/opportunities/${id}/state-history`);
}

// --------------------------------------------------------------------------- //
// Rubric & Matrix A
// --------------------------------------------------------------------------- //

export function getRubricDraft(): Promise<RubricDraft> {
  return apiGet<RubricDraft>('/rubric/draft');
}

export function listRubricVersions(): Promise<RubricVersion[]> {
  return apiGet<RubricVersion[]>('/rubric/versions');
}

/** WBS 8.7: rejections and overrides aggregated per rubric factor. */
export function getRubricFeedback(): Promise<RubricFeedback> {
  return apiGet<RubricFeedback>('/rubric/feedback');
}

/**
 * Publishes the decision register's v1 rubric as-is -- Matrix A baselines,
 * Matrix B caps, the 0.05-0.95 bounds, a 20pp run cap, lifecycle bands and
 * the gate_all review policy. Idempotent.
 */
export function publishRubricV1(): Promise<RubricVersion> {
  return apiPost<RubricVersion>('/rubric/publish-v1');
}

/** Deterministic: no model call, no proposal, nothing written. */
export function previewRubricImpact(draft: RubricDraft, label: string): Promise<Impact> {
  return apiPost<Impact>('/rubric/impact', {
    label, matrix_a: draft.matrix_a, rubric_factors: draft.rubric_factors,
  });
}

/**
 * Publishing stamps a version id that every proposal made afterwards records.
 * It re-runs nothing: existing proposals keep the version that produced them,
 * which is what lets two runs be compared rather than argued about.
 */
export function publishRubricVersion(draft: RubricDraft, label: string): Promise<RubricVersion> {
  return apiPost<RubricVersion>('/rubric/versions', {
    label, matrix_a: draft.matrix_a, rubric_factors: draft.rubric_factors,
  });
}

// --------------------------------------------------------------------------- //
// Import
// --------------------------------------------------------------------------- //

export function dryRunImport(file: File): Promise<DryRun> {
  const form = new FormData();
  form.append('file', file);
  return apiUpload<DryRun>('/imports/dry-run', form);
}

/**
 * Takes the snapshot id, not a second upload: the commit re-reads the sealed
 * bytes and re-checks their sha256, so what gets written is what was approved.
 */
export function commitImport(snapshotId: string): Promise<CommitResult> {
  return apiUpload<CommitResult>(`/imports/${snapshotId}/commit`, new FormData());
}

export function listSnapshots(): Promise<SnapshotSummary[]> {
  return apiGet<SnapshotSummary[]>('/imports');
}

// --------------------------------------------------------------------------- //
// Access
// --------------------------------------------------------------------------- //

export function getAccessMatrix(): Promise<AccessMatrix> {
  return apiGet<AccessMatrix>('/access/matrix');
}

export function getMe(): Promise<Me> {
  return apiGet<Me>('/access/me');
}

export function listObservedActors(): Promise<ObservedActor[]> {
  return apiGet<ObservedActor[]>('/access/actors');
}
