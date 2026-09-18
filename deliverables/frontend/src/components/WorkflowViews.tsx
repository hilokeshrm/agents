import { useEffect, useState } from 'react';
import { apiGet, apiPost } from '../api';
import { money } from '../calc';
import { getRegistry, resolveProposal } from '../store';
import { RunCompare } from './PlatformViews';
import type { Proposal, Registry } from '../types';

type DashboardData = {
  total_pipeline_k: number;
  open_pipeline_k: number;
  weighted_forecast_k: number;
  closed_won_k: number;
  opportunity_count: number;
  total_nre_revenue_k?: number;
  funnel_by_design_status: { design_status: string; amount_k: number; count: number }[];
};

type AuditEvent = {
  at: string;
  source: string;
  kind: string;
  project: string | null;
  summary: string;
  detail: string | null;
  actor: string;
};

type Run = {
  id: string;
  status: string;
  mode: string;
  actor: string;
  counts: Record<string, number>;
  started_at: string;
  finished_at: string | null;
};

export function ReviewQueueView({
  onMessage,
  onChanged,
}: {
  onMessage: (message: string, error?: boolean) => void;
  // A decision changes the pipeline too (confidence, status, pending markers),
  // so the shell reloads its own copy rather than showing a stale count.
  onChanged?: () => void;
}) {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  function load() {
    apiGet<Proposal[]>('/proposals?status=pending').then(setProposals).catch((error) => onMessage(String(error), true));
  }

  useEffect(() => {
    load();
    getRegistry().then(setRegistry).catch((error) => onMessage(String(error), true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="card workflow-card">
      <div className="card-head compact">
        <div>
          <p className="section-overline">Human gate</p>
          <h3>Review queue</h3>
          <p className="card-sub">Approve, override or reject — all three write an audit event</p>
        </div>
        <span className="inline-chip warn">{proposals.length} pending</span>
      </div>

      {proposals.length === 0 ? (
        <p className="empty-cell muted">No pending proposals. Request a review from an opportunity or run a backend scan.</p>
      ) : (
        <div className="workflow-list">
          {proposals.map((proposal) => (
            <ProposalRow
              key={proposal.id}
              proposal={proposal}
              registry={registry}
              open={openId === proposal.id}
              busy={busy === proposal.id}
              onToggle={() => setOpenId(openId === proposal.id ? null : proposal.id)}
              onResolved={(message) => {
                onMessage(message);
                setOpenId(null);
                load();
                onChanged?.();
              }}
              onError={(message) => onMessage(message, true)}
              onBusy={(value) => setBusy(value ? proposal.id : null)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ProposalRow({
  proposal, registry, open, busy, onToggle, onResolved, onError, onBusy,
}: {
  proposal: Proposal;
  registry: Registry | null;
  open: boolean;
  busy: boolean;
  onToggle: () => void;
  onResolved: (message: string) => void;
  onError: (message: string) => void;
  onBusy: (value: boolean) => void;
}) {
  const [overriding, setOverriding] = useState(false);
  const [value, setValue] = useState(proposal.proposed_confidence.toFixed(2));
  const [reasonCode, setReasonCode] = useState('');
  const [note, setNote] = useState('');

  const [rejecting, setRejecting] = useState(false);
  const isTransition = proposal.kind === 'transition';
  const needsLossReason = isTransition && proposal.transition?.requires_reason_code;
  // The vocabulary the API will enforce for the action being taken.
  const vocabulary = overriding
    ? registry?.reason_codes.override_reason
    : rejecting
      ? registry?.reason_codes.rejection_reason
      : needsLossReason
        ? registry?.reason_codes.loss_reason
        : undefined;
  const label = proposal.project ?? proposal.opportunity_id;
  const flags = Object.keys(proposal.flags ?? {});
  const delta =
    proposal.proposed_adjusted_revenue_k != null && proposal.base_adjusted_revenue_k != null
      ? proposal.proposed_adjusted_revenue_k - proposal.base_adjusted_revenue_k
      : null;

  async function decide(action: 'approve' | 'reject' | 'override') {
    if (action === 'override') {
      const parsed = Number(value);
      if (Number.isNaN(parsed) || parsed < 0 || parsed > 1) {
        onError('A confidence override must be a number between 0 and 1.');
        return;
      }
      if (!reasonCode) {
        onError('An override must cite a reason code — the API enforces the vocabulary, not just the dropdown.');
        return;
      }
    }
    if (action === 'reject' && !reasonCode) {
      setRejecting(true);
      onError('A rejection must cite a reason code — it is the signal that tells the rubric which factor is wrong.');
      return;
    }
    if (action === 'approve' && needsLossReason && !reasonCode) {
      onError('Approving a Design Lost move needs the loss reason — the agent proposes the move, you record why.');
      return;
    }
    onBusy(true);
    try {
      await resolveProposal(proposal.id, {
        action,
        value: isTransition ? null : Number(value),
        reason_code: reasonCode || null,
        note,
      });
      const verb = action === 'approve' ? 'Approved' : action === 'reject' ? 'Rejected' : 'Overrode';
      onResolved(`${verb} ${label}`);
    } catch (error) {
      onError(String(error));
    } finally {
      onBusy(false);
    }
  }

  return (
    <div className={`workflow-row ${open ? 'expanded' : ''}`}>
      <div className="workflow-row-main">
        <div>
          <strong>{label}{isTransition && <span className="inline-chip"> lifecycle</span>}</strong>
          <span className="muted">
            {isTransition
              ? `${proposal.transition?.from_value} → ${proposal.transition?.to_value}`
              : `${proposal.base_confidence.toFixed(2)} → ${proposal.proposed_confidence.toFixed(2)}`}
            {!isTransition && delta != null ? ` · ${money(delta)} weighted` : ''}
            {proposal.region ? ` · ${proposal.region}` : ''}
            {proposal.owner ? ` · owner ${proposal.owner}` : ''}
            {proposal.rubric_version_label ? ` · rubric ${proposal.rubric_version_label}` : ''}
          </span>
        </div>
        <div className="workflow-actions">
          {proposal.actionable ? (
            <button className="btn-ghost btn-sm" onClick={onToggle}>{open ? 'Close' : 'Decide'}</button>
          ) : (
            <span className="muted">{proposal.blocked_reason}</span>
          )}
        </div>
      </div>

      {open && proposal.actionable && (
        <div className="decision-panel">
          {isTransition && proposal.transition && (
            <p className="hint">
              The agent proposes moving this record to <strong>{proposal.transition.to_value}</strong>:{' '}
              {proposal.transition.reason} — citing <span className="mono">{proposal.transition.evidence_quote}</span>.
              The agent moves nothing itself; approving writes the same state-history row a manual move would.
            </p>
          )}
          {!isTransition && proposal.band_crossing === null && (
            <p className="hint">
              This rubric version publishes no lifecycle bands, so band crossing is undecidable — which is why
              this queued for a person rather than applying on its own.
            </p>
          )}
          {flags.length > 0 && (
            <p className="hint">
              Bounds applied: {flags.map((f) => `${f} = ${JSON.stringify((proposal.flags ?? {})[f])}`).join(' · ')}.
              A flagged proposal always reaches a person.
            </p>
          )}

          {proposal.factors.length > 0 && (
            <ul className="factor-list compact">
              {proposal.factors
                .filter((factor) => factor.applies || factor.guard)
                .map((factor, index) => (
                  <li key={`${factor.key}-${index}`} className={factor.applies && factor.accepted !== false ? 'active' : 'idle'}>
                    <div className="factor-head">
                      <strong className="mono">{factor.rule_id ? `${factor.rule_id} ` : ''}{factor.key}</strong>
                      {factor.applies && factor.accepted !== false && (
                        <span className="factor-pp">
                          {factor.confidence_adjustment_pct >= 0 ? '+' : ''}
                          {factor.confidence_adjustment_pct}pp
                        </span>
                      )}
                      {factor.guard && <span className="inline-chip warn">{factor.guard}</span>}
                    </div>
                    <div className="muted">{factor.detail || factor.rationale}</div>
                    {factor.quote && <div className="muted mono">“{factor.quote}”</div>}
                  </li>
                ))}
            </ul>
          )}

          <div className="form-grid">
            <label className="span-2">
              Note (optional, written to the audit event)
              <input value={note} onChange={(event) => setNote(event.target.value)} placeholder="Why this decision" />
            </label>

            {(rejecting || needsLossReason) && !overriding && (
              <label>
                {rejecting ? 'Rejection reason' : 'Loss reason'}
                <select value={reasonCode} onChange={(event) => setReasonCode(event.target.value)}>
                  <option value="">Select a reason…</option>
                  {(vocabulary?.codes ?? []).map((code) => (
                    <option key={code} value={code}>{code}</option>
                  ))}
                </select>
              </label>
            )}

            {overriding && (
              <>
                <label>
                  Your value
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    max="1"
                    value={value}
                    onChange={(event) => setValue(event.target.value)}
                  />
                </label>
                <label>
                  Override reason
                  <select value={reasonCode} onChange={(event) => setReasonCode(event.target.value)}>
                    <option value="">Select a reason…</option>
                    {(vocabulary?.codes ?? []).map((code) => (
                      <option key={code} value={code}>{code}</option>
                    ))}
                  </select>
                </label>
              </>
            )}
          </div>

          {(overriding || rejecting || needsLossReason) && vocabulary && !vocabulary.ratified && (
            <p className="hint">
              This vocabulary is enforced at the API but not yet ratified — the categories are still draft.
            </p>
          )}

          <div className="workflow-actions">
            <button className="btn-primary btn-sm" disabled={busy} onClick={() => decide('approve')}>
              {isTransition ? `Approve move to ${proposal.transition?.to_value}` : `Approve ${proposal.proposed_confidence.toFixed(2)}`}
            </button>
            {isTransition ? null : overriding ? (
              <>
                <button className="btn-primary btn-sm" disabled={busy} onClick={() => decide('override')}>
                  Save override
                </button>
                <button className="btn-ghost btn-sm" disabled={busy} onClick={() => setOverriding(false)}>Cancel</button>
              </>
            ) : (
              <button className="btn-outline btn-sm" disabled={busy} onClick={() => setOverriding(true)}>Override…</button>
            )}
            <button
              className="btn-ghost btn-sm"
              disabled={busy}
              onClick={() => (rejecting || reasonCode ? decide('reject') : setRejecting(true))}
            >
              {rejecting ? 'Confirm reject' : 'Reject…'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function RollupsView() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { apiGet<DashboardData>('/dashboard').then(setData).catch((e) => setError(String(e))); }, []);
  if (error) return <div className="card empty-cell">{error}</div>;
  if (!data) return <div className="card empty-cell">Loading roll-ups…</div>;
  return (
    <div className="dashboard-grid compact-grid">
      <div className="card card-hero"><p className="section-overline">Forecast</p><p className="card-label">Weighted forecast</p><h2 className="hero-value">{money(data.weighted_forecast_k)}</h2><p className="card-sub">Computed by the backend calculation engine</p></div>
      <div className="card summary-stack"><div className="summary-row"><span className="summary-label">Open pipeline</span><strong className="summary-value">{money(data.open_pipeline_k)}</strong></div><div className="summary-row"><span className="summary-label">Closed won</span><strong className="summary-value">{money(data.closed_won_k)}</strong></div><div className="summary-row"><span className="summary-label">Opportunities</span><strong className="summary-value">{data.opportunity_count}</strong></div><div className="summary-row"><span className="summary-label" title="One-off engineering charges, reported beside silicon revenue and never inside it">NRE (separate)</span><strong className="summary-value">{money(data.total_nre_revenue_k ?? 0)}</strong></div></div>
      <div className="card span-2"><div className="card-head compact"><div><p className="section-overline">Portfolio</p><h3>Design status roll-up</h3></div></div><div className="workflow-list">{data.funnel_by_design_status.map((row) => <div className="workflow-row" key={row.design_status}><strong>{row.design_status}</strong><span className="muted">{row.count} opportunities</span><strong className="mono">{money(row.amount_k)}</strong></div>)}</div></div>
    </div>
  );
}

export function AuditView() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  function load() { Promise.all([apiGet<Run[]>('/runs'), apiGet<AuditEvent[]>('/audit?limit=50')]).then(([loadedRuns, loadedEvents]) => { setRuns(loadedRuns); setEvents(loadedEvents); }).catch((e) => setError(String(e))); }
  useEffect(load, []);
  async function trigger() { setBusy(true); try { await apiPost('/runs'); load(); } catch (e) { setError(String(e)); } finally { setBusy(false); } }
  return <div className="workflow-stack">
    <div className="card"><div className="card-head compact"><div><p className="section-overline">Traceability</p><h3>Runs &amp; audit</h3><p className="card-sub">Append-only backend events and judgment runs</p></div><button className="btn-primary btn-sm" disabled={busy} onClick={trigger}>{busy ? 'Running…' : 'Trigger run'}</button></div>{error && <p className="toast error">{error}</p>}<div className="workflow-list">{runs.length === 0 ? <p className="empty-cell muted">No runs recorded.</p> : runs.map((run) => <div className="workflow-row" key={run.id}><div><strong>{new Date(run.started_at).toLocaleString()}</strong><span className="muted">{run.mode} · {run.actor}</span></div><span className={`status-pill ${run.status === 'completed' ? 'win' : ''}`}>{run.status}</span></div>)}</div></div>
    <RunCompare runIds={runs.map((r) => r.id)} />
    <div className="card"><div className="card-head compact"><div><p className="section-overline">Audit feed</p><h3>Recent decisions</h3></div></div><div className="workflow-list">{events.length === 0 ? <p className="empty-cell muted">No audit events in scope.</p> : events.map((event, index) => <div className="workflow-row" key={`${event.at}-${index}`}><div><strong>{event.project ?? event.kind}</strong><span className="muted">{event.summary}{event.detail ? ` · ${event.detail}` : ''}</span></div><span className="muted">{new Date(event.at).toLocaleString()}</span></div>)}</div></div>
  </div>;
}
