import { useEffect, useState } from 'react';
import { money } from '../calc';
import {
  getMe, getRubricDraft, getRubricFeedback, listRubricVersions, previewRubricImpact, publishRubricV1,
  publishRubricVersion,
} from '../store';
import type { Impact, Me, RubricDraft, RubricFeedback, RubricVersion } from '../types';

const ALLOWS = new Set(['yes', 'own_region', 'all_regions']);

type Tab = 'matrix' | 'factors' | 'impact' | 'versions';

/**
 * Rubric & Matrix A (WBS 10.7) -- L4 memory with a user interface.
 *
 * Editing produces a draft; publishing stamps a version id that every proposal
 * made afterwards records. Publishing re-runs nothing, so existing proposals
 * keep the version that produced them -- which is the whole reason the table
 * exists: two runs can be compared rather than argued about.
 *
 * The impact preview is deliberately narrow about what it claims. It does not
 * ask the model what it would say next month; it reports what this draft
 * asserts about today's rows, deterministically, and writes nothing.
 */
export default function RubricView({ onMessage }: { onMessage: (message: string, error?: boolean) => void }) {
  const [tab, setTab] = useState<Tab>('matrix');
  const [draft, setDraft] = useState<RubricDraft | null>(null);
  const [versions, setVersions] = useState<RubricVersion[]>([]);
  const [label, setLabel] = useState('');
  const [impact, setImpact] = useState<Impact | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<RubricFeedback | null>(null);

  function load() {
    getRubricDraft()
      .then((loaded) => {
        setDraft(loaded);
        setLabel(nextLabel(loaded.based_on_label));
      })
      .catch((error) => onMessage(String(error), true));
    listRubricVersions().then(setVersions).catch(() => setVersions([]));
    getRubricFeedback().then(setFeedback).catch(() => setFeedback(null));
    getMe().then(setMe).catch(() => setMe(null));
  }

  useEffect(load, []);

  function setCell(key: string, patch: Partial<{ baseline: number | null; allowed: boolean | null }>) {
    setDraft((current) => {
      if (!current) return current;
      const cells = { ...current.matrix_a.cells, [key]: { ...current.matrix_a.cells[key], ...patch } };
      return { ...current, matrix_a: { ...current.matrix_a, cells } };
    });
    setImpact(null); // the preview belonged to the grid as it was a moment ago
  }

  async function preview() {
    if (!draft) return;
    setBusy(true);
    try {
      setImpact(await previewRubricImpact(draft, label || 'draft'));
      setTab('impact');
    } catch (error) {
      onMessage(String(error), true);
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    if (!draft) return;
    setBusy(true);
    try {
      const version = await publishRubricVersion(draft, label);
      onMessage(`Published ${version.label} — proposals from now on cite this version; existing ones keep theirs`);
      load();
      setTab('versions');
    } catch (error) {
      onMessage(String(error), true);
    } finally {
      setBusy(false);
    }
  }

  if (!draft) return <div className="card empty-cell">Loading the rubric draft…</div>;

  const cells = Object.values(draft.matrix_a.cells);
  const setCount = cells.filter((c) => c.baseline != null || c.allowed != null).length;

  return (
    <div className="workflow-stack">
      <div className="card">
        <div className="card-head compact">
          <div>
            <p className="section-overline">Admin</p>
            <h3>Rubric &amp; Matrix A</h3>
            <p className="card-sub">
              {draft.based_on_label
                ? `Draft based on published version ${draft.based_on_label}`
                : 'Nothing published yet — this is the first draft'}
              {` · ${setCount} of ${cells.length} cells set`}
            </p>
          </div>
          <div className="workflow-actions">
            <input
              className="version-label"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              placeholder="Version label"
              aria-label="Version label"
            />
            <button className="btn-outline btn-sm" disabled={busy} onClick={preview}>Preview impact</button>
            <button className="btn-primary btn-sm" disabled={busy || !label.trim()} onClick={publish}>Publish</button>
          </div>
        </div>

        <div className="pill-tabs">
          {([['matrix', 'Matrix A'], ['factors', 'Factors & caps'], ['impact', 'Impact'], ['versions', 'Published versions']] as [Tab, string][])
            .map(([id, text]) => (
              <button key={id} type="button" className={`pill ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
                {text}
              </button>
            ))}
        </div>
      </div>

      {tab === 'matrix' && <MatrixGrid draft={draft} onCell={setCell} />}
      {tab === 'factors' && <FactorEditor draft={draft} onChange={setDraft} feedback={feedback} onPublishV1={async () => {
        setBusy(true);
        try {
          const v = await publishRubricV1();
          onMessage(`Published ${v.label} from the decision register`);
          load();
        } catch (error) {
          onMessage(String(error), true);
        } finally {
          setBusy(false);
        }
      }} />}
      {tab === 'impact' && (
        <ImpactPane
          impact={impact}
          busy={busy}
          onRun={preview}
          canSeePipeline={
            !me || ALLOWS.has(me.grants.view_own_region) || ALLOWS.has(me.grants.view_all_regions)
          }
          role={me?.role_label ?? 'This role'}
        />
      )}
      {tab === 'versions' && <VersionList versions={versions} />}
    </div>
  );
}

function nextLabel(current: string | null): string {
  const year = new Date().getFullYear();
  if (!current) return `${year}.1`;
  const match = current.match(/^(\d{4})\.(\d+)$/);
  return match ? `${match[1]}.${Number(match[2]) + 1}` : `${current}-next`;
}

function MatrixGrid({
  draft, onCell,
}: { draft: RubricDraft; onCell: (key: string, patch: Partial<{ baseline: number | null; allowed: boolean | null }>) => void }) {
  const { cells, design_statuses: statuses, stages } = draft.matrix_a;
  return (
    <div className="card">
      <div className="card-head compact">
        <div>
          <p className="section-overline">Baseline confidence</p>
          <h3>By design status and stage</h3>
          <p className="card-sub">
            A dash marks a pairing the rules forbid — a row landing on one is an internal
            contradiction. An empty cell is undecided, which is not the same thing.
          </p>
        </div>
      </div>
      <div className="table-wrap">
        <table className="acru-table matrix-table">
          <thead>
            <tr>
              <th>Design status</th>
              {stages.map((stage) => <th key={stage}>{stage}</th>)}
            </tr>
          </thead>
          <tbody>
            {statuses.map((status) => (
              <tr key={status}>
                <td><strong>{status}</strong></td>
                {stages.map((stage) => {
                  const key = `${status}|${stage}`;
                  const cell = cells[key] ?? { baseline: null, allowed: null };
                  const forbidden = cell.allowed === false;
                  return (
                    <td key={key}>
                      <div className="matrix-cell">
                        <input
                          type="number"
                          step="0.05"
                          min={0}
                          max={1}
                          className={forbidden ? 'forbidden' : ''}
                          disabled={forbidden}
                          placeholder="—"
                          value={cell.baseline ?? ''}
                          aria-label={`Baseline for ${status} at ${stage}`}
                          onChange={(event) => onCell(key, {
                            baseline: event.target.value === '' ? null : Number(event.target.value),
                            allowed: event.target.value === '' ? cell.allowed : true,
                          })}
                        />
                        <button
                          type="button"
                          className="cell-toggle"
                          title={forbidden ? 'Allow this pairing' : 'Mark this pairing forbidden'}
                          onClick={() => onCell(key, forbidden
                            ? { allowed: null }
                            : { allowed: false, baseline: null })}
                        >
                          {forbidden ? '✕' : '–'}
                        </button>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FactorEditor({ draft, onChange, feedback, onPublishV1 }: {
  draft: RubricDraft;
  onChange: (next: RubricDraft) => void;
  feedback: RubricFeedback | null;
  onPublishV1: () => void;
}) {
  const { caps, factors } = draft.rubric_factors;
  const policy = draft.rubric_factors.review_policy ?? 'gate_all';
  const feedbackByRule = new Map((feedback?.by_factor ?? []).map((f) => [f.rule_id, f]));

  function setPolicy(value: 'gate_all' | 'gate_band_crossing') {
    onChange({ ...draft, rubric_factors: { ...draft.rubric_factors, review_policy: value } });
  }

  function setFactorCap(index: number, value: string) {
    onChange({
      ...draft,
      rubric_factors: {
        ...draft.rubric_factors,
        factors: factors.map((f, i) => (i === index ? { ...f, cap_pp: value === '' ? null : Number(value) } : f)),
      },
    });
  }

  function setCap(field: 'factor_cap_pp' | 'confidence_ceiling' | 'run_cap_pp', value: string) {
    onChange({
      ...draft,
      rubric_factors: {
        ...draft.rubric_factors,
        caps: { ...caps, [field]: value === '' ? null : Number(value) },
      },
    });
  }

  return (
    <div className="workflow-stack">
      <div className="card">
        <div className="card-head compact">
          <div>
            <p className="section-overline">Policy</p>
            <h3>Caps</h3>
            <p className="card-sub">A cap change is a policy change, so it publishes and versions like everything else</p>
          </div>
        </div>
        <div className="form-grid">
          <label>
            Factor cap (percentage points)
            <input
              type="number"
              step="1"
              min={0}
              value={caps.factor_cap_pp ?? ''}
              placeholder="unset — nothing is clipped"
              onChange={(event) => setCap('factor_cap_pp', event.target.value)}
            />
            <span className="hint">
              The largest adjustment any single factor may apply. Left unset there is no default cap,
              because a cap is a decision.
            </span>
          </label>
          <label>
            Run cap (percentage points)
            <input
              type="number"
              step="1"
              min={0}
              value={caps.run_cap_pp ?? ''}
              placeholder="unset — 20 by default"
              onChange={(event) => setCap('run_cap_pp', event.target.value)}
            />
            <span className="hint">
              Total movement across every factor in one run. Over it, the proposal is clipped and flagged for a person.
            </span>
          </label>
          <label>
            Confidence ceiling
            <input
              type="number"
              step="0.05"
              min={0}
              max={1}
              value={caps.confidence_ceiling ?? ''}
              placeholder="unset"
              onChange={(event) => setCap('confidence_ceiling', event.target.value)}
            />
            <span className="hint">
              0.95 per the decision register: only a person may assert a certainty in either direction.
            </span>
          </label>
          <label>
            Review policy
            <select value={policy} onChange={(event) => setPolicy(event.target.value as 'gate_all' | 'gate_band_crossing')}>
              <option value="gate_all">gate_all — every proposal reaches a person</option>
              <option value="gate_band_crossing">gate_band_crossing — auto-apply when no lifecycle band is crossed</option>
            </select>
            <span className="hint">
              A policy setting, not a rewrite: the agent proposes either way; this decides whether a
              proposal that crosses no band and carries no flag may apply without a reviewer.
            </span>
          </label>
        </div>
        <div className="workflow-actions">
          <button className="btn-outline btn-sm" type="button" onClick={onPublishV1}>
            Publish v1 from the decision register
          </button>
          <span className="muted">
            Matrix A baselines, Matrix B caps, 0.05–0.95, 20pp run cap, lifecycle bands, gate_all. Idempotent.
          </span>
        </div>
      </div>

      <div className="card">
        <div className="card-head compact">
          <div>
            <p className="section-overline">Rubric</p>
            <h3>Factors</h3>
            <p className="card-sub">
              A disabled factor is an unknown rule to the reply guards — the model&apos;s answer for it is
              rejected and shown, not quietly ignored
            </p>
          </div>
        </div>
        <div className="workflow-list">
          {factors.map((factor, index) => (
            <div className="workflow-row" key={factor.key}>
              <label className="factor-toggle">
                <input
                  type="checkbox"
                  checked={factor.enabled}
                  onChange={(event) => onChange({
                    ...draft,
                    rubric_factors: {
                      ...draft.rubric_factors,
                      factors: factors.map((f, i) => (i === index ? { ...f, enabled: event.target.checked } : f)),
                    },
                  })}
                />
                <span>
                  <strong className="mono">{factor.label || factor.key}</strong>
                  {factor.guidance && <span className="muted">{factor.guidance}</span>}
                  {factor.requires && (
                    <span className="muted">
                      needs {factor.requires.join(', ')}
                      {factor.availability && factor.availability !== 'live' ? ` · ${factor.availability}` : ''}
                    </span>
                  )}
                </span>
              </label>
              <label className="factor-cap">
                cap pp
                <input
                  type="number"
                  step="1"
                  min={0}
                  value={factor.cap_pp ?? ''}
                  placeholder="Matrix B"
                  onChange={(event) => setFactorCap(index, event.target.value)}
                />
              </label>
              {(() => {
                const fb = factor.rule_id ? feedbackByRule.get(factor.rule_id) : undefined;
                if (!fb || fb.fired === 0) return <span className="muted">not fired yet</span>;
                const rate = fb.rejection_rate != null ? Math.round(fb.rejection_rate * 100) : 0;
                return (
                  <span className={`inline-chip ${rate >= 50 ? 'warn' : ''}`} title="rejections / times fired">
                    fired {fb.fired} · rejected {fb.rejected} ({rate}%) · overridden {fb.overridden}
                  </span>
                );
              })()}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function ImpactPane({
  impact, busy, onRun, canSeePipeline, role,
}: { impact: Impact | null; busy: boolean; onRun: () => void; canSeePipeline: boolean; role: string }) {
  // Region scope is enforced in the query, so a role with no view grant gets an
  // empty result rather than an error. Reporting that as "$0K, nothing changes"
  // would be the screen lying about a permission boundary.
  if (!canSeePipeline) {
    return (
      <div className="card empty-cell">
        <p className="muted">
          {role} has no view grant on opportunities, so there are no rows to measure this draft
          against — the preview would report zero for every figure, which is a permission boundary
          rather than a finding. A director or finance role can run it.
        </p>
      </div>
    );
  }
  if (!impact) {
    return (
      <div className="card empty-cell">
        <p className="muted">No preview yet — the grid may have changed since the last one.</p>
        <button className="btn-primary btn-sm" disabled={busy} onClick={onRun}>Preview impact on today&apos;s pipeline</button>
      </div>
    );
  }
  return (
    <div className="workflow-stack">
      <div className="dashboard-grid compact-grid">
        <div className="card summary-stack">
          <div className="summary-row"><span className="summary-label">Rows considered</span><strong className="summary-value">{impact.rows_considered}</strong></div>
          <div className="summary-row"><span className="summary-label">Off baseline</span><strong className="summary-value">{impact.rows_off_baseline}</strong></div>
          <div className="summary-row"><span className="summary-label">On a forbidden pairing</span><strong className="summary-value">{impact.rows_forbidden}</strong></div>
          <div className="summary-row"><span className="summary-label">Cell not set</span><strong className="summary-value">{impact.rows_unset_cell}</strong></div>
        </div>
        <div className="card card-hero">
          <p className="section-overline">If every row sat on this draft</p>
          <p className="card-label">Weighted at baseline</p>
          <h2 className="hero-value">{money(impact.at_baseline_weighted_k)}</h2>
          <p className="card-sub">
            {impact.delta_k >= 0 ? '+' : ''}{money(impact.delta_k)} against {money(impact.current_weighted_k)} today ·
            deterministic, nothing written
          </p>
        </div>
      </div>

      <div className="card">
        <div className="card-head compact">
          <div><p className="section-overline">Row by row</p><h3>What this draft asserts</h3></div>
        </div>
        <div className="table-wrap">
          <table className="acru-table">
            <thead>
              <tr>
                <th>Opportunity</th><th>Pairing</th><th>Entered</th><th>Baseline</th>
                <th>Δ</th><th>Weighted now</th><th>At baseline</th>
              </tr>
            </thead>
            <tbody>
              {impact.rows.map((row) => (
                <tr key={row.opportunity_id}>
                  <td><strong>{row.project}</strong><span className="muted">{row.region}</span></td>
                  <td>
                    {row.design_status} at {row.stage}
                    {row.forbidden && <span className="inline-chip warn">forbidden</span>}
                  </td>
                  <td className="mono">{row.entered_confidence.toFixed(2)}</td>
                  <td className="mono">{row.baseline == null ? '—' : row.baseline.toFixed(2)}</td>
                  <td className="mono">{row.delta_pp == null ? '—' : `${row.delta_pp >= 0 ? '+' : ''}${row.delta_pp.toFixed(0)}pp`}</td>
                  <td className="mono">{money(row.adjusted_revenue_k)}</td>
                  <td className="mono">{row.at_baseline_revenue_k == null ? '—' : money(row.at_baseline_revenue_k)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function VersionList({ versions }: { versions: RubricVersion[] }) {
  return (
    <div className="card">
      <div className="card-head compact">
        <div>
          <p className="section-overline">History</p>
          <h3>Published versions</h3>
          <p className="card-sub">A published version is never edited — that is what makes a proposal citable</p>
        </div>
      </div>
      <div className="workflow-list">
        {versions.length === 0 ? (
          <p className="empty-cell muted">Nothing published yet. A run needs a published version to stamp on its proposals.</p>
        ) : versions.map((version) => {
          const setCount = Object.values(version.matrix_a?.cells ?? {})
            .filter((cell) => cell.baseline != null || cell.allowed != null).length;
          return (
            <div className="workflow-row" key={version.id}>
              <div>
                <strong>
                  {version.label}
                  {version.is_current && <span className="inline-chip warn">current</span>}
                </strong>
                <span className="muted">
                  {new Date(version.published_at).toLocaleString()} · {version.published_by} ·
                  {` ${setCount} cells set · cap ${version.rubric_factors?.caps?.factor_cap_pp ?? '—'}`}
                </span>
              </div>
              <span className="muted">{version.proposal_count} proposals</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
