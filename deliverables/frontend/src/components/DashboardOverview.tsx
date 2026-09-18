import { money } from '../calc';
import type { Project, Rollup } from '../types';
import { IconTarget, IconTrendUp, IconUsers } from './Icons';

type Props = {
  rollup: Rollup;
  projects: Project[];
  pendingReview: number;
  onSelect: (id: string) => void;
  onNavigatePipeline: () => void;
};

const AVATAR_CLASS = ['a', 'b', 'c'] as const;

export default function DashboardOverview({
  rollup,
  projects,
  pendingReview,
  onSelect,
  onNavigatePipeline,
}: Props) {
  const regions = Object.entries(rollup.by_region);
  const maxSales = Math.max(...regions.map(([, v]) => v.sales_revenue_k), 1);
  const weightedPct = rollup.stretch_revenue_k
    ? Math.round((rollup.projection_revenue_k / rollup.stretch_revenue_k) * 100)
    : 0;

  const topProjects = [...projects]
    .sort((a, b) => b.adjusted_revenue_k - a.adjusted_revenue_k)
    .slice(0, 3);

  const donutStyle = {
    background: `conic-gradient(var(--forest) 0% ${weightedPct}%, var(--gold-muted) ${weightedPct}% 100%)`,
  };

  return (
    <div className="dashboard-grid compact-grid">
      <div className="card card-hero span-2">
        <div className="card-head">
          <div>
            <p className="section-overline">Revenue</p>
            <p className="card-label">Weighted projection</p>
            <h2 className="hero-value">{money(rollup.projection_revenue_k)}</h2>
            <p className="card-sub">
              Weighted projection · {rollup.project_count} opportunities
              {pendingReview > 0 && (
                <span className="inline-chip warn"> · {pendingReview} flagged for review</span>
              )}
            </p>
          </div>
          <div className="pill-tabs">
            <button type="button" className="pill active">
              Project Track
            </button>
          </div>
        </div>

        <div className="chart-legend">
          <span><i className="dot dot-sales" /> Stretch (Sales)</span>
          <span><i className="dot dot-adj" /> Projection (Adjusted)</span>
        </div>

        <div className="bar-chart">
          {regions.map(([region, vals]) => (
            <div key={region} className="bar-group">
              <div className="bar-stack" style={{ height: '96px' }}>
                <div
                  className="bar bar-sales bar-animate"
                  style={{ height: `${(vals.sales_revenue_k / maxSales) * 100}%` }}
                  title={`Sales ${money(vals.sales_revenue_k)}`}
                />
                <div
                  className="bar bar-adj bar-animate"
                  style={{ height: `${(vals.adjusted_revenue_k / maxSales) * 100}%` }}
                  title={`Adjusted ${money(vals.adjusted_revenue_k)}`}
                />
              </div>
              <span className="bar-label">{region}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="card summary-stack">
        <div className="summary-row">
          <div className="summary-icon purple">
            <IconTrendUp />
          </div>
          <span className="summary-label">Stretch (Sales)</span>
          <strong className="summary-value">{money(rollup.stretch_revenue_k)}</strong>
          <span className="trend up">Unweighted</span>
        </div>
        <div className="summary-row">
          <div className="summary-icon teal">
            <IconTarget />
          </div>
          <span className="summary-label">Projection (Adjusted)</span>
          <strong className="summary-value">{money(rollup.projection_revenue_k)}</strong>
          <span className="trend up">{weightedPct}% of stretch</span>
        </div>
        <div className="summary-row">
          <div className="summary-icon orange">
            <IconUsers />
          </div>
          <span className="summary-label">Agent queue</span>
          <strong className="summary-value">{pendingReview}</strong>
          <span className="trend muted">Awaiting review</span>
        </div>
      </div>

      <div className="card pipeline-card">
        <div className="card-head compact">
          <div>
            <p className="section-overline">Pipeline</p>
            <h3>Confidence weighting</h3>
            <p className="card-sub">Rollup from user-entered confidence scores</p>
          </div>
        </div>
        <div className="confidence-card-inner">
          <div className="donut-wrap">
            <div className="donut" style={donutStyle} />
            <div className="donut-hole">
              <span className="donut-value">{weightedPct}%</span>
            </div>
          </div>
          <div className="donut-side">
            <div className="gradient-gauge-track">
              <div className="gradient-gauge-fill" style={{ width: `${weightedPct}%` }} />
            </div>
            <div className="gauge-labels">
              <span>0%</span>
              <span>100%</span>
            </div>
            <p className="gauge-caption">{weightedPct}% of stretch revenue weighted</p>
          </div>
        </div>
      </div>

      <div className="card span-2">
        <div className="card-head compact">
          <div>
            <p className="section-overline">Ranked</p>
            <h3>Top opportunities</h3>
          </div>
          <button type="button" className="link-btn" onClick={onNavigatePipeline}>
            View pipeline →
          </button>
        </div>
        <div className="opp-list">
          {topProjects.map((p, i) => {
            const conf = p.calibrated_confidence ?? p.confidence;
            const pct = Math.round(conf * 100);
            return (
              <button key={p.id} type="button" className="opp-row" onClick={() => onSelect(p.id)}>
                <div className={`opp-avatar ${AVATAR_CLASS[i] ?? 'a'}`}>
                  {p.project.slice(0, 2).toUpperCase()}
                </div>
                <div className="opp-info">
                  <strong>{p.project}</strong>
                  <div className="opp-bar">
                    <div className="opp-bar-fill bar-animate" style={{ width: `${pct}%` }} />
                  </div>
                </div>
                <span className="opp-value">{money(p.adjusted_revenue_k)}</span>
                <span className="opp-pct">{pct}%</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
