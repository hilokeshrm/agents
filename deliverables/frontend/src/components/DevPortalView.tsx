import { useCallback, useEffect, useState } from 'react';
import { apiGet } from '../api';

/**
 * Dev portal (local debugging aid, not a WBS task): a browser over the
 * backend's /dev/* introspection routes -- the live database, every table,
 * and the real stdout/stderr the dev scripts redirect to disk. Nothing here
 * is computed in the browser; every figure is what /dev/status, /dev/tables
 * and /dev/logs answer right now.
 */

type DevStatus = {
  uptime_seconds: number;
  db: { dialect: string; url: string; table_count: number; total_rows: number; file_size_bytes: number | null };
  config: Record<string, string | number>;
  logs: { count: number; total_size_bytes: number };
};
type DevTable = { name: string; row_count: number };
type DevTableDetail = { table: string; columns: string[]; rows: (string | null)[][] };
type DevLogEntry = { source: string; path: string; exists: boolean; size_bytes: number; modified_at: number | null };
type DevLog = { source: string; path: string; lines: string[]; note?: string };

function Card({ title, overline, sub, children, actions }: { title: string; overline?: string; sub?: string; children?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="card">
      <div className="card-head compact">
        <div>
          {overline && <p className="section-overline">{overline}</p>}
          <h3>{title}</h3>
          {sub && <p className="card-sub">{sub}</p>}
        </div>
        {actions}
      </div>
      {children}
    </div>
  );
}

function formatBytes(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

const LOG_FLAG = /error|traceback|exception/i;

export default function DevPortalView() {
  const [status, setStatus] = useState<DevStatus | null>(null);
  const [tables, setTables] = useState<DevTable[]>([]);
  const [selectedTable, setSelectedTable] = useState<string | null>(null);
  const [tableDetail, setTableDetail] = useState<DevTableDetail | null>(null);
  const [logList, setLogList] = useState<DevLogEntry[]>([]);
  const [selectedLog, setSelectedLog] = useState<string | null>(null);
  const [logDetail, setLogDetail] = useState<DevLog | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const loadOverview = useCallback(() => {
    Promise.all([
      apiGet<DevStatus>('/dev/status'),
      apiGet<DevTable[]>('/dev/tables'),
      apiGet<DevLogEntry[]>('/dev/logs'),
    ])
      .then(([s, t, l]) => {
        setStatus(s);
        setTables(t);
        setLogList(l);
        setSelectedLog((cur) => cur ?? l.find((x) => x.source === 'backend')?.source ?? l[0]?.source ?? null);
        setErr(null);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => { loadOverview(); }, [loadOverview]);

  useEffect(() => {
    if (!selectedTable) { setTableDetail(null); return; }
    apiGet<DevTableDetail>(`/dev/tables/${encodeURIComponent(selectedTable)}?limit=200`)
      .then(setTableDetail)
      .catch((e) => setErr(String(e)));
  }, [selectedTable]);

  const loadLog = useCallback(() => {
    if (!selectedLog) return;
    apiGet<DevLog>(`/dev/logs/${encodeURIComponent(selectedLog)}?lines=300`)
      .then(setLogDetail)
      .catch((e) => setErr(String(e)));
  }, [selectedLog]);

  useEffect(() => { loadLog(); }, [loadLog]);

  useEffect(() => {
    if (!autoRefresh) return;
    const t = window.setInterval(() => { loadOverview(); loadLog(); }, 5000);
    return () => window.clearInterval(t);
  }, [autoRefresh, loadOverview, loadLog]);

  if (err && !status) return <div className="card empty-cell">{err}</div>;
  if (!status) return <div className="card empty-cell">Reading backend status…</div>;

  return (
    <div className="workflow-stack">
      <div className="dashboard-grid compact-grid">
        <div className="card card-hero">
          <p className="section-overline">Database</p>
          <p className="card-label">{status.db.dialect}</p>
          <h2 className="hero-value">{status.db.table_count} tables</h2>
          <p className="card-sub">
            {status.db.total_rows.toLocaleString()} rows total
            {status.db.file_size_bytes != null ? ` · ${formatBytes(status.db.file_size_bytes)} on disk` : ''}
          </p>
        </div>
        <div className="card card-hero">
          <p className="section-overline">Backend</p>
          <p className="card-label">Uptime</p>
          <h2 className="hero-value">{formatUptime(status.uptime_seconds)}</h2>
          <p className="card-sub mono">{status.db.url}</p>
        </div>
        <div className="card card-hero">
          <p className="section-overline">Logs</p>
          <p className="card-label">On disk</p>
          <h2 className="hero-value">{status.logs.count} file(s)</h2>
          <p className="card-sub">{formatBytes(status.logs.total_size_bytes)} combined</p>
        </div>
      </div>

      {err && <p className="toast error">{err}</p>}

      <Card overline="Config" title="Runtime configuration" sub="Non-secret settings this process booted with">
        <div className="chip-row">
          {Object.entries(status.config).map(([k, v]) => (
            <span className="inline-chip" key={k}>{k.replace(/_/g, ' ')}: <strong>{String(v)}</strong></span>
          ))}
        </div>
      </Card>

      <Card overline="Tables" title="Database tables" sub="Every table SQLAlchemy's inspector can see · click a row to browse it">
        <div className="table-wrap">
          <table className="acru-table">
            <thead><tr><th>Table</th><th>Rows</th></tr></thead>
            <tbody>
              {tables.map((t) => (
                <tr key={t.name} className={selectedTable === t.name ? 'selected' : ''} onClick={() => setSelectedTable(t.name === selectedTable ? null : t.name)}>
                  <td className="mono">{t.name}</td>
                  <td className="mono">{t.row_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {tableDetail && (
        <Card
          overline="Rows"
          title={tableDetail.table}
          sub={`First ${tableDetail.rows.length} row(s) · all columns`}
          actions={<button type="button" className="btn-ghost btn-sm" onClick={() => setSelectedTable(null)}>Close</button>}
        >
          <div className="table-wrap">
            <table className="acru-table">
              <thead><tr>{tableDetail.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>
                {tableDetail.rows.map((row, i) => (
                  <tr key={i}>{row.map((v, j) => <td key={j} className="mono">{v ?? '—'}</td>)}</tr>
                ))}
                {tableDetail.rows.length === 0 && (
                  <tr><td colSpan={tableDetail.columns.length} className="muted empty-cell">Empty table.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <Card
        overline="Logs"
        title="Process logs"
        sub="The real stdout/stderr redirected by the dev scripts, tailed on demand"
        actions={
          <div className="workflow-actions">
            <select value={selectedLog ?? ''} onChange={(e) => setSelectedLog(e.target.value)}>
              {logList.map((l) => (
                <option key={l.source} value={l.source}>{l.source}{l.exists ? '' : ' (no output yet)'}</option>
              ))}
            </select>
            <label className="factor-toggle">
              <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} /> <span>Auto-refresh (5s)</span>
            </label>
            <button type="button" className="btn-outline btn-sm" onClick={() => { loadOverview(); loadLog(); }}>Refresh</button>
          </div>
        }
      >
        {logDetail?.note && <p className="muted">{logDetail.note}</p>}
        <pre className="dev-log-pane">
          {(logDetail?.lines ?? []).map((line, i) => (
            <div key={i} className={LOG_FLAG.test(line) ? 'dev-log-error' : undefined}>{line}</div>
          ))}
          {logDetail && logDetail.lines.length === 0 && !logDetail.note && <div className="muted">No output yet.</div>}
        </pre>
      </Card>
    </div>
  );
}
