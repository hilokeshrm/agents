import { useEffect, useState } from 'react';
import { commitImport, dryRunImport, listSnapshots } from '../store';
import type { CommitResult, DryRun, SnapshotSummary } from '../types';

/**
 * Import wizard and findings view (WBS 10.11).
 *
 * Import is migration and backfill, not the intake path: direct entry is
 * primary and is the only route that captures owner, evidence and a reason for
 * the confidence figure at the moment a person knows them. Everything imported
 * here lands at the lowest trust level, below every connector.
 *
 * The dry run is the wizard. Nothing is created until a person has seen what
 * would fail, and the commit sends the snapshot id rather than the file again,
 * so what gets written is what was approved.
 */
export default function ImportView({ onMessage }: { onMessage: (message: string, error?: boolean) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [dryRun, setDryRun] = useState<DryRun | null>(null);
  const [result, setResult] = useState<CommitResult | null>(null);
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [blockingOnly, setBlockingOnly] = useState(false);
  const [busy, setBusy] = useState(false);

  function loadSnapshots() {
    listSnapshots().then(setSnapshots).catch(() => setSnapshots([]));
  }

  useEffect(loadSnapshots, []);

  async function runDry() {
    if (!file) return;
    setBusy(true);
    setResult(null);
    try {
      const preview = await dryRunImport(file);
      setDryRun(preview);
      loadSnapshots();
      onMessage(`${preview.row_count} rows read · ${preview.would_create} would be created, ${preview.would_block} blocked`);
    } catch (error) {
      onMessage(String(error), true);
    } finally {
      setBusy(false);
    }
  }

  async function commit() {
    if (!dryRun) return;
    setBusy(true);
    try {
      const committed = await commitImport(dryRun.snapshot_id);
      setResult(committed);
      loadSnapshots();
      onMessage(`Created ${committed.created} opportunities · ${committed.blocked} rows left out`);
    } catch (error) {
      onMessage(String(error), true);
    } finally {
      setBusy(false);
    }
  }

  const rows = (dryRun?.rows ?? []).filter((row) => !blockingOnly || row.blocking);
  const fields = dryRun ? Array.from(new Set(Object.values(dryRun.mapping))) : [];

  return (
    <div className="workflow-stack">
      <div className="card">
        <div className="card-head compact">
          <div>
            <p className="section-overline">Intake</p>
            <h3>Import</h3>
            <p className="card-sub">
              Workbook or CSV, column-mapped, with a dry-run validation pass before anything is
              written. Migration and backfill only — every value lands at the lowest trust level.
            </p>
          </div>
        </div>
        <div className="workflow-actions import-bar">
          <span className="step-number">1</span>
          <input
            type="file"
            accept=".csv,.xlsx,.xlsm"
            aria-label="File to import"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setDryRun(null);
              setResult(null);
            }}
          />
          <button className="btn-primary btn-sm" disabled={!file || busy} onClick={runDry}>
            {busy && !dryRun ? 'Validating…' : 'Dry run'}
          </button>
          <span className="muted">Nothing is created by a dry run.</span>
        </div>
      </div>

      {dryRun && (
        <>
          <div className="dashboard-grid compact-grid">
            <div className="card summary-stack">
              <div className="summary-row"><span className="summary-label">Rows read</span><strong className="summary-value">{dryRun.row_count}</strong></div>
              <div className="summary-row"><span className="summary-label">Would create</span><strong className="summary-value">{dryRun.would_create}</strong></div>
              <div className="summary-row"><span className="summary-label">Would block</span><strong className="summary-value">{dryRun.would_block}</strong></div>
              <div className="summary-row"><span className="summary-label">Advisory findings</span><strong className="summary-value">{dryRun.advisory_count}</strong></div>
            </div>
            <div className="card">
              <div className="card-head compact">
                <div>
                  <p className="section-overline">Step 2</p>
                  <h3>Column mapping</h3>
                  <p className="card-sub mono">{dryRun.filename} · sha256 {dryRun.sha256.slice(0, 16)}… · snapshot sealed</p>
                </div>
              </div>
              <div className="chip-row">
                {Object.entries(dryRun.mapping).map(([header, field]) => (
                  <span className="inline-chip" key={header}>{header} → {field}</span>
                ))}
                {dryRun.unmapped_headers.map((header) => (
                  <span className="inline-chip warn" key={header} title="Not an intake field — this column is ignored">
                    {header} → ignored
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head compact">
              <div><p className="section-overline">Step 3</p><h3>Preview</h3></div>
              <div className="workflow-actions">
                <div className="pill-tabs">
                  <button type="button" className={`pill ${blockingOnly ? '' : 'active'}`} onClick={() => setBlockingOnly(false)}>All rows</button>
                  <button type="button" className={`pill ${blockingOnly ? 'active' : ''}`} onClick={() => setBlockingOnly(true)}>Blocking only</button>
                </div>
                <button
                  className="btn-primary btn-sm"
                  disabled={busy || dryRun.would_create === 0 || !!result}
                  onClick={commit}
                >
                  Commit {dryRun.would_create} rows
                </button>
              </div>
            </div>

            <div className="table-wrap">
              <table className="acru-table">
                <thead>
                  <tr>
                    <th>#</th>
                    {fields.map((field) => <th key={field}>{field}</th>)}
                    <th>Findings</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.index} className={row.blocking ? 'blocked-row' : ''}>
                      <td className="mono">{row.index}</td>
                      {fields.map((field) => (
                        <td key={field} className="mono">
                          {row.values[field] === null || row.values[field] === undefined ? '—' : String(row.values[field])}
                        </td>
                      ))}
                      <td>
                        {row.findings.length === 0
                          ? <span className="muted">clean</span>
                          : row.findings.map((finding, index) => (
                            <div key={index} className="finding-line">
                              <span className={`inline-chip ${finding.severity === 'blocking' ? 'warn' : ''}`}>{finding.rule_id}</span>
                              <span className="muted">{finding.message}</span>
                            </div>
                          ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {result && (
              <p className="toast success">
                Committed {result.created} opportunities, {result.blocked} rows left out. The commit re-read
                the sealed snapshot and re-checked its sha256 first, so what was written is what you approved.
              </p>
            )}
          </div>
        </>
      )}

      <div className="card">
        <div className="card-head compact">
          <div>
            <p className="section-overline">History</p>
            <h3>Snapshots</h3>
            <p className="card-sub">Write-once: sha256, source and row counts, sealed at capture</p>
          </div>
        </div>
        <div className="workflow-list">
          {snapshots.length === 0 ? (
            <p className="empty-cell muted">No imports yet.</p>
          ) : snapshots.map((snapshot) => (
            <div className="workflow-row" key={snapshot.id}>
              <div>
                <strong>{new Date(snapshot.captured_at).toLocaleString()}</strong>
                <span className="muted mono">
                  {snapshot.sha256.slice(0, 16)}… · {snapshot.sealed_at ? 'sealed' : 'not sealed'}
                </span>
              </div>
              <span className="muted">
                {snapshot.finding_count} findings · {snapshot.blocking_count} blocking
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
