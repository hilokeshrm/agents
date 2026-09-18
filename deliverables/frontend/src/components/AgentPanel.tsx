import { formatTime, type ActivityEntry } from '../agent';
import { IconStar } from './Icons';

type Props = {
  entries: ActivityEntry[];
  pendingReview: number;
  autoAnalyze: boolean;
  onToggleAuto: () => void;
  onRunScan: () => void;
  canRunScan: boolean;
  busy: boolean;
  expanded: boolean;
  onToggleExpand: () => void;
  showWorkflow?: boolean;
};

export default function AgentStatusBar({
  entries,
  pendingReview,
  autoAnalyze,
  onToggleAuto,
  onRunScan,
  canRunScan,
  busy,
  expanded,
  onToggleExpand,
  showWorkflow = true,
}: Props) {
  const latest = entries[0];

  return (
    <div className={`agent-bar ${expanded ? 'expanded' : 'collapsed'}`}>
      <div className="agent-bar-top">
        <div className="agent-bar-left">
          <div className="agent-bar-title-row">
            <span className="agent-live">
              <span className={`pulse ${busy ? 'busy' : ''}`} />
              {busy ? 'Scanning pipeline…' : 'Automation console'}
            </span>
            <span className="pro-badge">Backend</span>
          </div>
          <span className="agent-meta">
            {busy
              ? 'Evaluating confidence against 13-rule rubric…'
              : latest
                ? `${formatTime(latest.at)} · ${latest.message}`
                : 'Monitoring pipeline · auto-analyze enabled'}
          </span>
        </div>

        <div className="agent-bar-center">
          {pendingReview > 0 && (
            <span className="agent-chip warn">{pendingReview} need review</span>
          )}
          {expanded && (
            <button
              type="button"
              className={`btn-text-link ${autoAnalyze ? 'active' : ''}`}
              onClick={onToggleAuto}
            >
              {autoAnalyze ? 'Auto-analyze on' : 'Auto-analyze off'}
            </button>
          )}
          {!expanded && autoAnalyze && (
            <span className="agent-chip auto-mini">Auto</span>
          )}
        </div>

        <div className="agent-bar-actions">
          {expanded && canRunScan && (
            <button type="button" className="btn-scan" disabled={busy} onClick={onRunScan}>
              {busy ? 'Running…' : 'Run agent scan'}
            </button>
          )}
          <button
            type="button"
            className="agent-toggle-btn"
            onClick={onToggleExpand}
            aria-expanded={expanded}
            title={expanded ? 'Collapse automation panel' : 'Expand automation panel'}
          >
            <span className={`agent-toggle-icon ${expanded ? 'open' : ''}`} aria-hidden />
            {expanded ? 'Collapse' : 'Expand'}
          </button>
        </div>
      </div>

      <div className="agent-bar-body">
        <div className="agent-bar-expandable">
          {showWorkflow && <WorkflowStrip pendingReview={pendingReview} />}
          <div className="agent-feed-inline">
            <AgentActivityFeed entries={entries} compact />
          </div>
        </div>
      </div>
    </div>
  );
}

type FeedProps = { entries: ActivityEntry[]; compact?: boolean };

export function AgentActivityFeed({ entries, compact }: FeedProps) {
  return (
    <div className={`card agent-feed-card ${compact ? 'compact' : ''}`}>
      {!compact && (
        <div className="card-head compact">
          <div>
            <h3>Agent activity</h3>
            <p className="card-sub">Automated pipeline steps · newest first</p>
          </div>
        </div>
      )}
      {compact && <p className="agent-feed-label">Live activity</p>}
      <ul className="activity-list">
        {entries.length === 0 && (
          <li className="activity-item idle">No activity yet — automation will log here.</li>
        )}
        {entries.slice(0, compact ? 4 : undefined).map((e) => (
          <li key={e.id} className={`activity-item ${e.kind}`}>
            <span className="activity-time">{formatTime(e.at)}</span>
            <div>
              <strong>{e.message}</strong>
              {e.detail && <p>{e.detail}</p>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

const STEPS = [
  { label: 'Intake', sub: 'User inputs', tone: 'step-forest', done: true },
  { label: 'Calculate', sub: 'Revenue math', tone: 'step-gold', done: true },
  { label: 'Analyze', sub: '13-rule rubric', tone: 'step-forest', done: true },
  { label: 'Recommend', sub: 'Confidence pp', tone: 'step-gold', done: false },
] as const;

export function WorkflowStrip({ pendingReview }: { pendingReview: number }) {
  return (
    <div className="workflow-strip">
      {STEPS.map((s, i) => (
        <div key={s.label} className="workflow-step-wrap">
          <div className={`workflow-step ${s.tone} ${s.done ? 'done' : 'next'}`}>
            <span className="step-num">
              {s.done ? '✓' : s.label === 'Recommend' ? <IconStar /> : i + 1}
              {!s.done && pendingReview > 0 && s.label === 'Recommend' && (
                <span className="step-badge">{pendingReview}</span>
              )}
            </span>
            <div>
              <strong>{s.label}</strong>
              <span>{s.sub}</span>
            </div>
          </div>
          {i < STEPS.length - 1 && <div className="workflow-line" />}
        </div>
      ))}
    </div>
  );
}
