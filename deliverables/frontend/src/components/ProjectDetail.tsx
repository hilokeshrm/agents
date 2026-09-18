import type { ConfidenceResult, Project, Registry, TransitionInput } from '../types';
import { adjustedRevenueK, money, salesRevenueK } from '../calc';
import LifecycleControls from './LifecycleControls';

type Props = {
  project: Project;
  judgment: ConfidenceResult | null;
  analyzing: boolean;
  onSuggest: () => void;
  onApply: () => void;
  busy: boolean;
  registry: Registry | null;
  grants: Record<string, string>;
  onTransition: (input: TransitionInput) => Promise<void>;
};

const LLM_FIELDS = [
  'design_status',
  'stage',
  'confidence',
  'competitor_part',
  'evidence',
  'confidence_rationale',
  'region',
  'customer',
  'end_customer',
] as const;

export default function ProjectDetail({
  project, judgment, analyzing, onSuggest, onApply, busy, registry, grants, onTransition,
}: Props) {
  const suggestedConf = judgment
    ? judgment.calibrated_confidence
    : project.calibrated_confidence ?? project.confidence;

  const previewAdjusted = adjustedRevenueK(project.sales_revenue_k, suggestedConf);
  const delta = judgment ? judgment.calibrated_confidence - judgment.base_confidence : 0;

  return (
    <div className="detail-grid">
      {analyzing && (
        <div className="analyzing-banner">
          <span className="spinner" />
          Agent analyzing opportunity context…
        </div>
      )}

      <section className="detail-col user-col">
        <p className="section-overline">Inputs</p>
        <h3>User inputs</h3>
        <p className="hint">Entered by sales — feeds calc + judgment</p>
        <dl className="kv">
          <dt>EAU (Kpcs)</dt>
          <dd className="mono">{project.eau_kpcs.toLocaleString()}</dd>
          <dt>Disty ASP</dt>
          <dd className="mono">${project.disty_asp}</dd>
          <dt>Confidence</dt>
          <dd className="mono">{project.confidence.toFixed(2)}</dd>
          <dt>Design status</dt>
          <dd>{project.design_status}</dd>
          <dt>Stage</dt>
          <dd>{project.stage || '—'}</dd>
          <dt>Region</dt>
          <dd>{project.region}</dd>
          <dt>Customer</dt>
          <dd>{project.customer}</dd>
          <dt>Competitor</dt>
          <dd>{project.competitor_part || '—'}</dd>
          <dt>NRE charge</dt>
          <dd className="mono">{project.nre_charge_k ? money(project.nre_charge_k) : '—'}</dd>
        </dl>
      </section>

      <section className="detail-col calc-col">
        <p className="section-overline">Formula</p>
        <h3>Calculated</h3>
        <p className="hint">Deterministic · never LLM</p>
        <div className="formula-card">
          <div className="formula-line">
            <span>Sales Revenue</span>
            <code>{project.eau_kpcs} × {project.disty_asp}</code>
            <strong className="mono">{money(project.sales_revenue_k)}</strong>
          </div>
          <div className="formula-line">
            <span>Adjusted Revenue</span>
            <code>Sales × {project.confidence.toFixed(2)}</code>
            <strong className="mono">{money(project.adjusted_revenue_k)}</strong>
          </div>
          {judgment && (
            <div className="formula-line highlight">
              <span>Suggested adjusted</span>
              <code>Sales × {suggestedConf.toFixed(2)}</code>
              <strong className="mono">{money(previewAdjusted)}</strong>
            </div>
          )}
          {!!project.nre_revenue_k && (
            <div className="formula-line">
              <span>NRE (separate)</span>
              <code>one-off, not phased</code>
              <strong className="mono">{money(project.nre_revenue_k)}</strong>
            </div>
          )}
        </div>
        {!!project.nre_revenue_k && (
          <p className="hint">
            Engineering charge, reported beside silicon revenue and never added into it — it is
            recognised whole in the M/P quarter rather than spread across the ramp.
          </p>
        )}
      </section>

      <section className="detail-col llm-col">
        <div className="detail-col-head">
          <div>
            <p className="section-overline">Agent</p>
            <h3>Agent judgment</h3>
          </div>
          <span className="pro-badge">Backend</span>
        </div>
        <p className="hint">Confidence adjustments only — revenue unchanged</p>

        {judgment ? (
          <div className="suggestion-banner">
            <span className={`delta-badge ${delta >= 0 ? 'up' : 'down'}`}>
              {delta >= 0 ? '+' : ''}{(delta * 100).toFixed(0)}pp
            </span>
            <span className="mono">
              {judgment.base_confidence.toFixed(2)} → {judgment.calibrated_confidence.toFixed(2)}
            </span>
          </div>
        ) : (
          <p className="muted analyze-hint">Select a project with auto-analyze, or run analysis manually.</p>
        )}

        <div className="detail-actions">
          <button type="button" className="btn-primary" disabled={busy || analyzing} onClick={onSuggest}>
            Re-analyze
          </button>
          {judgment && (
            <button type="button" className="btn-outline" disabled={busy} onClick={onApply}>
              Apply recommendation
            </button>
          )}
        </div>

        {judgment && (
          <ul className="factor-list">
            {judgment.factors.map((f) => (
              <li key={f.key} className={f.applies ? 'active' : 'idle'}>
                <div className="factor-head">
                  <strong className="mono">{f.key}</strong>
                  {f.applies && (
                    <span className="factor-pp">
                      {f.confidence_adjustment_pct >= 0 ? '+' : ''}
                      {f.confidence_adjustment_pct}pp
                    </span>
                  )}
                </div>
                <div className="muted">{f.rationale}</div>
              </li>
            ))}
          </ul>
        )}

        <details className="context-details">
          <summary>Context payload</summary>
          <pre className="mono context-pre">
            {JSON.stringify(
              Object.fromEntries(LLM_FIELDS.map((k) => [k, (project as Record<string, unknown>)[k] ?? null])),
              null,
              2,
            )}
          </pre>
        </details>
      </section>

      <LifecycleControls
        project={project}
        registry={registry}
        grants={grants}
        busy={busy}
        onTransition={onTransition}
      />
    </div>
  );
}

export function LiveCalcPreview({
  eauKpcs,
  distyAsp,
  confidence,
}: {
  eauKpcs: number;
  distyAsp: number;
  confidence: number;
}) {
  const sales = salesRevenueK(eauKpcs, distyAsp);
  const adjusted = adjustedRevenueK(sales, confidence);

  return (
    <div className="live-calc">
      <span className="mini-label">Auto-calculated preview</span>
      <div className="formula-card compact">
        <div className="formula-line">
          <span>Sales</span>
          <code>{eauKpcs} × {distyAsp}</code>
          <strong className="mono">{money(sales)}</strong>
        </div>
        <div className="formula-line">
          <span>Adjusted</span>
          <code>Sales × {confidence.toFixed(2)}</code>
          <strong className="mono">{money(adjusted)}</strong>
        </div>
      </div>
    </div>
  );
}
