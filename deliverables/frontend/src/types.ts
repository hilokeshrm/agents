export type Project = {
  id: string;
  external_id?: string | null;
  region: string;
  customer: string;
  end_customer?: string | null;
  project: string;
  part_number: string;
  design_status: string;
  stage?: string | null;
  mp_date?: string | null;
  eau_kpcs: number;
  unit_per_set?: number | null;
  disty_asp: number;
  resale_asp?: number | null;
  /** One-off engineering charge in $K (V29) -- never inside sales revenue. */
  nre_charge_k?: number | null;
  confidence: number;
  calibrated_confidence?: number | null;
  competitor_part?: string | null;
  application?: string | null;
  product_line?: string | null;
  owner: string;
  evidence?: string | null;
  confidence_rationale: string;
  bucket: string;
  sales_revenue_k: number;
  adjusted_revenue_k: number;
  /** Reported beside volume revenue by the calc engine, never added into it. */
  nre_revenue_k?: number;
  nre_weighted_k?: number;
};

export type Rollup = {
  total_sales_revenue_k: number;
  total_adjusted_revenue_k: number;
  stretch_revenue_k: number;
  projection_revenue_k: number;
  project_count: number;
  by_region: Record<string, { sales_revenue_k: number; adjusted_revenue_k: number }>;
};

export type ConfidenceFactor = {
  rule_id?: string | null;   // Matrix B id, J-01..J-13
  quote?: string;            // verbatim from the evidence bundle
  key: string;
  applies: boolean;
  confidence_adjustment_pct: number;
  rationale: string;
  confidence: number;
  // Written by the eight reply guards (app/judgment/reply_guards.py). A factor
  // the guards rejected, or could not assess, is kept on the proposal rather
  // than dropped -- a reviewer who only sees what the model got right has no way
  // to calibrate how much to trust the next one.
  accepted?: boolean;
  guard?: string | null;
  detail?: string | null;
  clipped_from?: number | null;
};

export type ConfidenceResult = {
  mode: string;
  base_confidence: number;
  calibrated_confidence: number;
  factors: ConfidenceFactor[];
};

export type Proposal = {
  id: string;
  opportunity_id: string;
  status: string;
  base_confidence: number;
  proposed_confidence: number;
  factors: ConfidenceFactor[];
  actionable: boolean;
  blocked_reason: string | null;
  // Row context the API already returns, so the queue reads as opportunities
  // rather than as a list of UUIDs.
  project?: string;
  region?: string;
  owner?: string;
  design_status?: string;
  stage?: string;
  rubric_version_label?: string | null;
  matrix_a_baseline?: number | null;
  base_adjusted_revenue_k?: number;
  proposed_adjusted_revenue_k?: number;
  band_crossing?: boolean | null;
  // "confidence" or "transition" (WBS 8.3): a transition proposal asks a
  // person with the close grant to move the record; it changes no number.
  kind?: 'confidence' | 'transition';
  transition?: {
    field: string; from_value: string; to_value: string; reason: string;
    evidence_quote: string; requires_reason_code: boolean;
  } | null;
  // What the bounds did: run_cap_clipped_from_pp, clamped_from, contract_violation.
  flags?: Record<string, unknown>;
};

/** Mirrors app/schemas/review.py ProposalResolve. */
export type ResolveInput = {
  action: 'approve' | 'reject' | 'override';
  value?: number | null;
  reason_code?: string | null;
  note?: string | null;
  rejected_factors?: string[] | null;
};

/** Mirrors app/schemas/state_history.py StateTransitionCreate. */
export type TransitionInput = {
  field: 'design_status' | 'stage';
  to_value: string;
  actor: string;
  reason_code?: string | null;
};

export type StateEvent = {
  id: number;
  field: string;
  from_value: string | null;
  to_value: string;
  actor: string;
  reason_code: string | null;
  occurred_at: string;
};

export type ReasonVocabulary = {
  name: string;
  codes: string[];
  /** false = the enforcement is real but the category list is still draft. */
  ratified: boolean;
  required_when: string | null;
};

/**
 * Served by GET /registry so a dropdown cannot offer a value the API rejects.
 * Nothing in this app should hardcode a status, a stage or a reason code.
 */
export type Registry = {
  design_statuses: string[];
  stages: string[];
  approval_required_statuses: string[];
  reason_codes: {
    loss_reason: ReasonVocabulary;
    stage_exit_reason: ReasonVocabulary;
    override_reason: ReasonVocabulary;
    rejection_reason: ReasonVocabulary;
  };
};

/** Mirrors app/api/v1/rubric.py FeedbackRead (WBS 8.7). */
export type FactorFeedback = {
  rule_id: string; label: string; fired: number; rejected: number; overridden: number;
  rejection_rate: number | null;
};
export type RubricFeedback = { proposals: number; rejections: number; overrides: number; by_factor: FactorFeedback[] };

export type ProjectInput = {
  region: string;
  customer: string;
  end_customer?: string | null;
  project: string;
  part_number: string;
  design_status: string;
  stage?: string | null;
  mp_date?: string | null;
  eau_kpcs: number;
  unit_per_set?: number | null;
  disty_asp: number;
  resale_asp?: number | null;
  nre_charge_k?: number | null;
  confidence: number;
  competitor_part?: string | null;
  application?: string | null;
  product_line?: string | null;
  owner: string;
  evidence?: string | null;
  confidence_rationale: string;
  /** Required when design_status is Lost; from registry.reason_codes.loss_reason. */
  loss_reason?: string | null;
};

// --------------------------------------------------------------------------- //
// Rubric & Matrix A (app/api/v1/rubric.py)
// --------------------------------------------------------------------------- //

export type MatrixCell = {
  /** null = nobody has set this pairing. Not the same as 0.0. */
  baseline: number | null;
  /** false = a pairing the rules forbid; null = undecided. */
  allowed: boolean | null;
};

export type MatrixA = {
  cells: Record<string, MatrixCell>;
  design_statuses: string[];
  stages: string[];
};

export type RubricFactorDraft = {
  key: string; label: string; guidance: string; enabled: boolean;
  rule_id?: string; cap_pp?: number | null; direction?: string; requires?: string[]; availability?: string;
};

export type RubricFactors = {
  factors: RubricFactorDraft[];
  caps: {
    factor_cap_pp: number | null;
    run_cap_pp?: number | null;
    confidence_ceiling: number | null;
    confidence_floor: number | null;
  };
  lifecycle_bands?: { label: string; min: number | null; max: number | null }[];
  review_policy?: 'gate_all' | 'gate_band_crossing';
  source?: string;
};

export type RubricDraft = {
  based_on_version_id: string | null;
  based_on_label: string | null;
  matrix_a: MatrixA;
  rubric_factors: RubricFactors;
};

export type RubricVersion = {
  id: string;
  label: string;
  matrix_a: MatrixA;
  rubric_factors: RubricFactors;
  published_at: string;
  published_by: string;
  is_current: boolean;
  proposal_count: number;
};

export type ImpactRow = {
  opportunity_id: string;
  project: string;
  region: string;
  design_status: string;
  stage: string;
  entered_confidence: number;
  baseline: number | null;
  delta_pp: number | null;
  forbidden: boolean;
  adjusted_revenue_k: number;
  at_baseline_revenue_k: number | null;
};

export type Impact = {
  rows_considered: number;
  rows_forbidden: number;
  rows_off_baseline: number;
  rows_unset_cell: number;
  current_weighted_k: number;
  at_baseline_weighted_k: number;
  delta_k: number;
  rows: ImpactRow[];
};

// --------------------------------------------------------------------------- //
// Import wizard (app/api/v1/imports.py)
// --------------------------------------------------------------------------- //

export type ImportFinding = {
  rule_id: string;
  severity: string;
  field: string | null;
  raw_value: string | null;
  message: string;
};

export type ImportRow = {
  index: number;
  values: Record<string, string | number | null>;
  findings: ImportFinding[];
  blocking: boolean;
};

export type DryRun = {
  snapshot_id: string;
  sha256: string;
  filename: string;
  headers: string[];
  mapping: Record<string, string>;
  unmapped_headers: string[];
  row_count: number;
  would_create: number;
  would_block: number;
  advisory_count: number;
  findings_stored: number;
  rows: ImportRow[];
};

export type CommitResult = {
  snapshot_id: string;
  created: number;
  blocked: number;
  opportunity_ids: string[];
};

export type SnapshotSummary = {
  id: string;
  sha256: string;
  source_uri: string;
  row_counts: Record<string, unknown>;
  captured_at: string;
  sealed_at: string | null;
  finding_count: number;
  blocking_count: number;
};

// --------------------------------------------------------------------------- //
// Users & access (app/api/v1/access.py)
// --------------------------------------------------------------------------- //

export type AccessMatrix = {
  roles: string[];
  role_labels: Record<string, string>;
  allows: string[];
  rows: { action: string; label: string; grants: Record<string, string> }[];
  enforcement: { n: number; point: string; detail: string; where: string; status: string }[];
};

export type Me = {
  user_id: string;
  role: string;
  role_label: string;
  regions: string[];
  sees_all_regions: boolean;
  grants: Record<string, string>;
  identity_source: string;
};

/** Identities observed in the data -- not a provisioned user list; there is none. */
export type ObservedActor = {
  name: string;
  appears_as: string[];
  opportunities_owned: number;
  events: number;
  last_seen: string | null;
};
