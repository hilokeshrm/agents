import { useState } from 'react';
import type { Project, Registry, TransitionInput } from '../types';

type Props = {
  project: Project;
  registry: Registry | null;
  grants: Record<string, string>;
  busy: boolean;
  onTransition: (input: TransitionInput) => Promise<void>;
};

const ALLOWS = new Set(['yes', 'own_region', 'all_regions']);

/**
 * Design status and stage moves (WBS 9.2). Every change here writes a
 * state_history event rather than overwriting a column, which is what makes
 * time-in-stage, stall detection and win rate computable from the stream later.
 *
 * Two API rules are surfaced rather than discovered by being refused:
 *  - Lost and Mass Production are terminal for the forecast, so they need the
 *    close/Design-Lost grant (manager or director). Without it the control is
 *    disabled and says why, instead of failing on click.
 *  - Lost requires a code from the loss_reason vocabulary. The select is
 *    populated from GET /registry, so it cannot offer a value the API rejects.
 */
export default function LifecycleControls({ project, registry, grants, busy, onTransition }: Props) {
  const [status, setStatus] = useState(project.design_status);
  const [stage, setStage] = useState(project.stage ?? '');
  const [lossReason, setLossReason] = useState('');
  const [stageReason, setStageReason] = useState('');
  const [error, setError] = useState<string | null>(null);

  const approvalRequired = new Set((registry?.approval_required_statuses ?? []).map((s) => s.toLowerCase()));
  const canClose = ALLOWS.has(grants.close_design_lost ?? 'no');
  const canMove = ALLOWS.has(grants.move_stage_status ?? 'no');

  const statusNeedsApproval = approvalRequired.has(status.toLowerCase());
  const statusNeedsLossReason = status.toLowerCase() === 'lost';
  const statusBlocked = statusNeedsApproval && !canClose;
  const statusUnchanged = status === project.design_status;
  const stageUnchanged = (stage || null) === (project.stage ?? null);

  async function move(field: 'design_status' | 'stage') {
    setError(null);
    const isStatus = field === 'design_status';
    if (isStatus && statusNeedsLossReason && !lossReason) {
      setError('A loss reason code is required before an opportunity can be marked Lost.');
      return;
    }
    try {
      await onTransition({
        field,
        to_value: isStatus ? status : stage,
        actor: '',
        reason_code: isStatus ? (statusNeedsLossReason ? lossReason : null) : stageReason || null,
      });
      setLossReason('');
      setStageReason('');
    } catch (caught) {
      setError(String(caught));
    }
  }

  const lossVocabulary = registry?.reason_codes.loss_reason;
  const stageVocabulary = registry?.reason_codes.stage_exit_reason;

  return (
    <section className="detail-col lifecycle-col">
      <p className="section-overline">Lifecycle</p>
      <h3>Move this opportunity</h3>
      <p className="hint">Each move writes an audit event — never an overwritten cell</p>

      {!canMove && (
        <p className="lifecycle-note">
          The current role cannot move stage or status. Ask an owner, manager or director.
        </p>
      )}

      <div className="lifecycle-grid">
        <div className="lifecycle-row">
          <span className="mini-label">Design status · now {project.design_status}</span>
          <div className="lifecycle-controls">
            <select value={status} disabled={!canMove || busy} onChange={(event) => setStatus(event.target.value)}>
              {(registry?.design_statuses ?? [project.design_status]).map((value) => (
                <option key={value} value={value}>
                  {value}
                  {approvalRequired.has(value.toLowerCase()) ? ' (needs approval)' : ''}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn-primary btn-sm"
              disabled={!canMove || busy || statusUnchanged || statusBlocked}
              onClick={() => move('design_status')}
            >
              Move
            </button>
          </div>

          {statusNeedsLossReason && (
            <div className="lifecycle-controls">
              <select value={lossReason} disabled={!canMove || busy} onChange={(event) => setLossReason(event.target.value)}>
                <option value="">Loss reason (required)…</option>
                {(lossVocabulary?.codes ?? []).map((code) => (
                  <option key={code} value={code}>{code}</option>
                ))}
              </select>
            </div>
          )}

          {statusBlocked && (
            <p className="lifecycle-note">
              {status} is terminal for the forecast, so it needs manager or director approval. The API
              enforces the same rule — this is not a hidden button.
            </p>
          )}

          {statusNeedsLossReason && lossVocabulary && !lossVocabulary.ratified && (
            <p className="lifecycle-note">
              The loss_reason categories are still draft, but the API enforces the list.
            </p>
          )}
        </div>

        <div className="lifecycle-row">
          <span className="mini-label">Stage · now {project.stage || '—'}</span>
          <div className="lifecycle-controls">
            <select value={stage} disabled={!canMove || busy} onChange={(event) => setStage(event.target.value)}>
              {(registry?.stages ?? []).map((value) => (
                <option key={value} value={value}>{value}</option>
              ))}
            </select>
            <button
              type="button"
              className="btn-outline btn-sm"
              disabled={!canMove || busy || stageUnchanged || !stage}
              onClick={() => move('stage')}
            >
              Move
            </button>
          </div>
          <div className="lifecycle-controls">
            <select value={stageReason} disabled={!canMove || busy} onChange={(event) => setStageReason(event.target.value)}>
              <option value="">Stage exit reason (optional)…</option>
              {(stageVocabulary?.codes ?? []).map((code) => (
                <option key={code} value={code}>{code}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {error && <p className="toast error">{error}</p>}
    </section>
  );
}
