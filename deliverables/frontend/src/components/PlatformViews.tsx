import { useEffect, useState } from 'react';
import { apiGet, apiPost, apiUpload } from '../api';
import { money } from '../calc';

/**
 * The platform screens that landed with the WBS completion pass:
 *
 * - RoleLanding      (10.10) what the role is *for*, at the top of the dashboard
 * - AnalysesView     (6.2)   every analysis, what ran, what is dark and why; Finance enters targets (6.4)
 * - FindingsView     (10.11) the Phase 0 report over the canonical workbook, generated
 * - ConnectorsView   (11.x)  the catalogue, a pull (dry run first), the reconciliation queue
 * - NotificationsView(11.7)  what the sweeps raised for this person
 * - UsersView        (9.4)   admin provisioning; no self-registration
 * - RunCompare       (6.6)   two runs side by side, every difference attributed
 * - EmbeddedAssistant(14.6)  the panel standalone, driven over postMessage
 *
 * Every figure here is read from the API; nothing is computed in the browser.
 */

type Analysis = {
  key: string; label: string; status: string; headline: string; figures: Record<string, unknown>;
  rows: Record<string, unknown>[]; missing: string[]; note: string;
};
type AnalysesRead = { as_of: string; scorable_rows: number; excluded_rows: number; available_parameters: string[]; ran: Analysis[]; dark: Analysis[] };

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

// --------------------------------------------------------------------------- //
// 10.10 -- per-role landing
// --------------------------------------------------------------------------- //

export function RoleLanding({ role, actor, onNavigate }: { role: string; actor: string; onNavigate: (view: string) => void }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    const loads: Promise<unknown>[] = [];
    if (role === 'owner' || role === 'manager' || role === 'director') loads.push(apiGet('/proposals').catch(() => []));
    if (role !== 'admin') loads.push(apiGet('/notifications').catch(() => []));
    if (role === 'director' || role === 'finance') loads.push(apiGet<AnalysesRead>('/analyses').catch(() => null));
    if (role === 'admin') loads.push(apiGet('/rubric/versions').catch(() => []), apiGet('/users').catch(() => []), apiGet('/metrics').catch(() => null));
    Promise.all(loads).then((results) => setData({ role, results })).catch(() => setData({ role, results: [] }));
  }, [role]);
  if (!data) return null;
  const r = data.results as unknown[];
  const proposals = (r[0] as { project?: string; owner?: string; kind?: string }[]) ?? [];
  if (role === 'owner') {
    const notes = (r[1] as { subject: string; kind: string }[]) ?? [];
    const mine = proposals.filter((p) => p.owner === actor);
    return (
      <div className="card card-hero span-2">
        <p className="section-overline">Your rows</p>
        <h3>{mine.length} of your rows carry an open proposal · {notes.length} notice(s) for you</h3>
        <p className="card-sub">You enter and evidence opportunities; a manager decides the number. Ask for a review from the opportunity page.</p>
        <div className="workflow-actions">
          <button className="btn-primary btn-sm" onClick={() => onNavigate('intake')}>Add an opportunity</button>
          <button className="btn-outline btn-sm" onClick={() => onNavigate('notifications')}>Notices</button>
        </div>
      </div>
    );
  }
  if (role === 'manager' || role === 'director') {
    const notes = (r[1] as { kind: string }[]) ?? [];
    const analyses = r[2] as AnalysesRead | null;
    const stalls = notes.filter((n) => n.kind === 'stall').length;
    const transitions = proposals.filter((p) => p.kind === 'transition').length;
    return (
      <div className="card card-hero span-2">
        <p className="section-overline">{role === 'manager' ? 'Your region' : 'All regions'}</p>
        <h3>{proposals.length} proposal(s) waiting for you{transitions ? ` (${transitions} lifecycle moves)` : ''} · {stalls} stalled row(s)</h3>
        {analyses && <p className="card-sub">{analyses.ran.find((a) => a.key === 'concentration_risk')?.headline}</p>}
        <div className="workflow-actions">
          <button className="btn-primary btn-sm" onClick={() => onNavigate('review')}>Open the review queue</button>
          <button className="btn-outline btn-sm" onClick={() => onNavigate('analyses')}>Analyses</button>
        </div>
      </div>
    );
  }
  if (role === 'finance') {
    const analyses = r[1] as AnalysesRead | null;
    const coverage = analyses?.ran.find((a) => a.key === 'coverage') ?? analyses?.dark.find((a) => a.key === 'coverage');
    return (
      <div className="card card-hero span-2">
        <p className="section-overline">Finance</p>
        <h3>{coverage ? coverage.headline : 'Coverage against target'}</h3>
        <p className="card-sub">The forecast is yours; this agent feeds it. Targets are entered under Analyses; the ROI feed is at /api/v1/exports/roi-feed.json.</p>
        <div className="workflow-actions">
          <button className="btn-primary btn-sm" onClick={() => onNavigate('analyses')}>Coverage and targets</button>
          <button className="btn-outline btn-sm" onClick={() => onNavigate('rollups')}>Forecast feed</button>
        </div>
      </div>
    );
  }
  if (role === 'admin') {
    const versions = (r[1] as { label: string; is_current: boolean }[]) ?? [];
    const users = (r[2] as unknown[]) ?? [];
    const metrics = r[3] as Record<string, number> | null;
    return (
      <div className="card card-hero span-2">
        <p className="section-overline">Configuration</p>
        <h3>Rubric {versions.find((v) => v.is_current)?.label ?? '— none published'} · {users.length} provisioned user(s) · {metrics?.runs ?? 0} run(s) this month</h3>
        <p className="card-sub">Admin publishes configuration and provisions people; it never approves a proposal and sees no pipeline data.</p>
        <div className="workflow-actions">
          <button className="btn-primary btn-sm" onClick={() => onNavigate('rubric')}>Rubric &amp; Matrix A</button>
          <button className="btn-outline btn-sm" onClick={() => onNavigate('users')}>Users</button>
          <button className="btn-outline btn-sm" onClick={() => onNavigate('connectors')}>Connectors</button>
        </div>
      </div>
    );
  }
  return null;
}

// --------------------------------------------------------------------------- //
// 6.2 / 6.4 -- analyses and targets
// --------------------------------------------------------------------------- //

export function AnalysesView({ role, onMessage }: { role: string; onMessage: (m: string, err?: boolean) => void }) {
  const [data, setData] = useState<AnalysesRead | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [target, setTarget] = useState({ region: '*', period: String(new Date().getFullYear()), amount_k: '' });
  function load() { apiGet<AnalysesRead>('/analyses').then(setData).catch((e) => onMessage(String(e), true)); }
  useEffect(load, []);
  async function saveTarget() {
    if (!target.amount_k || Number(target.amount_k) <= 0) return onMessage('A target needs an amount', true);
    try {
      await apiPut('/targets', { region: target.region, period: target.period, amount_k: Number(target.amount_k) });
      onMessage(`Target saved for ${target.region} ${target.period}`);
      load();
    } catch (e) { onMessage(String(e), true); }
  }
  if (!data) return <div className="card empty-cell">Loading analyses…</div>;
  return (
    <div className="workflow-stack">
      <Card overline="Layer 4" title="Analyses" sub={`${data.ran.length} ran, ${data.dark.length} waiting on data · ${data.scorable_rows} scorable rows, ${data.excluded_rows} excluded as blocking · as of ${data.as_of}`}>
        <div className="workflow-list">
          {data.ran.map((a) => (
            <div className="workflow-row" key={a.key}>
              <div style={{ flex: 1 }}>
                <strong>{a.label} <span className={`inline-chip ${a.status === 'live' ? '' : 'warn'}`}>{a.status}</span></strong>
                <span className="muted">{a.headline}</span>
                {open === a.key && (
                  <div className="muted" style={{ marginTop: 8 }}>
                    <p>{a.note}</p>
                    {a.rows.length > 0 && (
                      <div className="table-wrap"><table className="acru-table"><thead><tr>{Object.keys(a.rows[0]).slice(0, 7).map((k) => <th key={k}>{k}</th>)}</tr></thead>
                        <tbody>{a.rows.slice(0, 25).map((r, i) => <tr key={i}>{Object.keys(a.rows[0]).slice(0, 7).map((k) => <td key={k}>{typeof r[k] === 'number' ? (Math.abs(r[k] as number) >= 100 ? money(r[k] as number) : String(Math.round((r[k] as number) * 1000) / 1000)) : Array.isArray(r[k]) ? (r[k] as unknown[]).length + ' item(s)' : String(r[k] ?? '')}</td>)}</tr>)}</tbody></table></div>
                    )}
                  </div>
                )}
              </div>
              <button className="btn-ghost btn-sm" onClick={() => setOpen(open === a.key ? null : a.key)}>{open === a.key ? 'Close' : 'Rows'}</button>
            </div>
          ))}
          {data.dark.map((a) => (
            <div className="workflow-row" key={a.key}>
              <div><strong>{a.label} <span className="inline-chip">dark</span></strong><span className="muted">{a.note}</span></div>
            </div>
          ))}
        </div>
      </Card>
      {(role === 'finance' || role === 'admin') && (
        <Card overline="Decision #67" title="Targets" sub="Finance's top-down commitment by region and period; coverage lights up the moment one exists">
          <div className="form-grid">
            <label>Region<input value={target.region} onChange={(e) => setTarget({ ...target, region: e.target.value })} placeholder="* or Korea" /></label>
            <label>Period<input value={target.period} onChange={(e) => setTarget({ ...target, period: e.target.value })} placeholder="2027 or 2027-Q1" /></label>
            <label>Amount (USD K)<input type="number" value={target.amount_k} onChange={(e) => setTarget({ ...target, amount_k: e.target.value })} /></label>
          </div>
          <div className="workflow-actions"><button className="btn-primary btn-sm" onClick={saveTarget}>Save target</button></div>
        </Card>
      )}
    </div>
  );
}

async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const { request } = await import('../api');
  return request<T>(path, { method: 'PUT', body: JSON.stringify(body) });
}

// --------------------------------------------------------------------------- //
// 10.11 -- the workbook findings report
// --------------------------------------------------------------------------- //

type Report = { workbook: string; matrix_a_source: string; row_counts: Record<string, number>; by_severity: Record<string, number>;
  spec_findings_reproduced: string[]; spec_findings_missing: string[]; findings: { rule_id: string; severity: string; where: string; message: string; spec_ref: string | null }[] };

export function FindingsView({ onMessage }: { onMessage: (m: string, err?: boolean) => void }) {
  const [report, setReport] = useState<Report | null>(null);
  useEffect(() => { apiGet<Report>('/imports/workbook-report').then(setReport).catch((e) => onMessage(String(e), true)); }, []);
  if (!report) return <div className="card empty-cell">Reading the workbook…</div>;
  return (
    <Card overline="Phase 0" title="Findings report" sub={`${report.by_severity.blocking} blocking, ${report.by_severity.advisory} advisory, ${report.by_severity.cosmetic} cosmetic · documented findings reproduced: ${report.spec_findings_reproduced.length} of 12 · Matrix A: ${report.matrix_a_source}`}>
      <p className="muted">Rows read: {Object.entries(report.row_counts).map(([k, v]) => `${k} ${v}`).join(', ')} · rules V-a..V-i over {report.workbook.split(/[\\/]/).pop()}</p>
      <div className="table-wrap"><table className="acru-table"><thead><tr><th>Severity</th><th>Rule</th><th>Where</th><th>Finding</th><th>Spec</th></tr></thead>
        <tbody>{report.findings.map((f, i) => (
          <tr key={i}><td><span className={`inline-chip ${f.severity === 'blocking' ? 'warn' : ''}`}>{f.severity}</span></td><td className="mono">{f.rule_id}</td><td className="mono">{f.where}</td><td>{f.message}</td><td className="mono">{f.spec_ref ?? ''}</td></tr>
        ))}</tbody></table></div>
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// 11.x -- connectors and the reconciliation queue
// --------------------------------------------------------------------------- //

type Connector = { name: string; label: string; supplies: string[]; trust: number; cadence: string; description: string };
type Reconciliation = { id: string; project: string; region: string; field: string; current_value: unknown; observed_value: unknown; source: string; trust: number; current_trust: number; gated: boolean; reason: string };

export function ConnectorsView({ onMessage }: { onMessage: (m: string, err?: boolean) => void }) {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [queue, setQueue] = useState<Reconciliation[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState('crm');
  const [dryRun, setDryRun] = useState(true);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  function load() {
    apiGet<Connector[]>('/connectors').then(setConnectors).catch(() => setConnectors([]));
    apiGet<Reconciliation[]>('/connectors/reconciliation').then(setQueue).catch(() => setQueue([]));
  }
  useEffect(load, []);
  async function pull() {
    if (!file) return onMessage('Choose a file first', true);
    const form = new FormData();
    form.append('file', file);
    form.append('dry_run', dryRun ? 'true' : 'false');
    try {
      const r = await apiUpload<Record<string, unknown>>(`/connectors/${name}/pull`, form);
      setResult(r);
      onMessage(`${name}: ${r.applied} applied, ${r.reconciliation_items} to reconcile${dryRun ? ' (dry run, nothing written)' : ''}`);
      load();
    } catch (e) { onMessage(String(e), true); }
  }
  async function resolve(item: Reconciliation, action: 'approve' | 'reject') {
    try {
      await apiPost(`/proposals/${item.id}/resolve`, { action, reason_code: action === 'reject' ? 'data_error_on_row' : (String(item.observed_value).toLowerCase() === 'lost' ? 'other' : null) });
      onMessage(`${action === 'approve' ? 'Took' : 'Kept the row over'} the ${item.source} value for ${item.project}.${item.field}`);
      load();
    } catch (e) { onMessage(String(e), true); }
  }
  return (
    <div className="workflow-stack">
      <Card overline="Package 11" title="Connectors" sub="Each supplies named parameters at a declared trust; a lower rung never overwrites a higher one silently (decision #63)">
        <div className="workflow-list">{connectors.map((c) => (
          <div className="workflow-row" key={c.name}><div><strong>{c.label} <span className="inline-chip">trust {c.trust} · {c.cadence}</span></strong><span className="muted">{c.description} · supplies {c.supplies.join(', ')}</span></div></div>
        ))}</div>
        <div className="form-grid" style={{ marginTop: 12 }}>
          <label>Connector<select value={name} onChange={(e) => setName(e.target.value)}>{connectors.map((c) => <option key={c.name} value={c.name}>{c.label}</option>)}</select></label>
          <label>Export file<input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
          <label className="factor-toggle"><input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} /> <span>Dry run — record what would change, write nothing</span></label>
        </div>
        <div className="workflow-actions"><button className="btn-primary btn-sm" onClick={pull}>Pull</button></div>
        {result && <pre className="muted" style={{ whiteSpace: 'pre-wrap', fontSize: '0.8rem' }}>{JSON.stringify({ ...result, details: (result.details as unknown[]).slice(0, 10) }, null, 2)}</pre>}
      </Card>
      <Card overline="11.2" title="Reconciliation queue" sub={`${queue.length} value(s) a connector observed that did not out-rank the row — a person decides`}>
        <div className="workflow-list">
          {queue.length === 0 ? <p className="empty-cell muted">Nothing to reconcile.</p> : queue.map((q) => (
            <div className="workflow-row" key={q.id}>
              <div><strong>{q.project} · {q.field}{q.gated && <span className="inline-chip warn"> lifecycle</span>}</strong>
                <span className="muted">row: {String(q.current_value ?? '—')} (trust {q.current_trust}) · {q.source}: {String(q.observed_value)} (trust {q.trust}) · {q.reason}</span></div>
              <div className="workflow-actions">
                <button className="btn-outline btn-sm" onClick={() => resolve(q, 'approve')}>Take {q.source}</button>
                <button className="btn-ghost btn-sm" onClick={() => resolve(q, 'reject')}>Keep row</button>
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 11.7 -- notifications
// --------------------------------------------------------------------------- //

type Notice = { id: string; kind: string; subject: string; body: string; status: string; created_at: string };

export function NotificationsView() {
  const [rows, setRows] = useState<Notice[]>([]);
  useEffect(() => { apiGet<Notice[]>('/notifications').then(setRows).catch(() => setRows([])); }, []);
  return (
    <Card overline="11.7" title="Notices" sub="What the nightly sweeps and the queue raised for you: stalls, overdue milestones, proposals waiting">
      <div className="workflow-list">{rows.length === 0 ? <p className="empty-cell muted">Nothing for you right now.</p> : rows.map((n) => (
        <div className="workflow-row" key={n.id}><div><strong>{n.subject} <span className="inline-chip">{n.kind}</span></strong><span className="muted">{n.body}</span></div><span className="muted">{new Date(n.created_at).toLocaleString()} · {n.status}</span></div>
      ))}</div>
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// 9.4 -- users and provisioning
// --------------------------------------------------------------------------- //

type User = { user_id: string; display_name: string; email: string | null; role: string; region_scope: string; active: boolean; anonymised_at: string | null; connector: string | null };

export function UsersView({ onMessage }: { onMessage: (m: string, err?: boolean) => void }) {
  const [users, setUsers] = useState<User[]>([]);
  const [draft, setDraft] = useState({ user_id: '', display_name: '', email: '', role: 'owner', region_scope: '*' });
  const [serviceKey, setServiceKey] = useState<string | null>(null);
  function load() { apiGet<User[]>('/users').then(setUsers).catch((e) => onMessage(String(e), true)); }
  useEffect(load, []);
  async function provision(service = false) {
    try {
      const body = { ...draft, email: draft.email || null, ...(service ? { role: 'service', connector: draft.role } : {}) };
      const r = await apiPost<User & { api_key?: string }>(service ? '/users/service' : '/users', body);
      if (r.api_key) setServiceKey(r.api_key);
      onMessage(`Provisioned ${r.user_id}`);
      load();
    } catch (e) { onMessage(String(e), true); }
  }
  async function toggle(u: User) {
    try { await request(`/users/${u.user_id}`, 'PATCH', { active: !u.active }); load(); } catch (e) { onMessage(String(e), true); }
  }
  async function anonymise(u: User) {
    if (!window.confirm(`Anonymise ${u.user_id}? The name and email go; every decision stays under the id.`)) return;
    try { await request(`/users/${u.user_id}`, 'DELETE'); load(); } catch (e) { onMessage(String(e), true); }
  }
  return (
    <div className="workflow-stack">
      <Card overline="9.4" title="Provision a user" sub="No self-registration: a row exists because an admin created it. Role and scope come from here, never from a token claim.">
        <div className="form-grid">
          <label>User id<input value={draft.user_id} onChange={(e) => setDraft({ ...draft, user_id: e.target.value })} /></label>
          <label>Display name<input value={draft.display_name} onChange={(e) => setDraft({ ...draft, display_name: e.target.value })} /></label>
          <label>Email (binds the SSO subject on first sign-in)<input value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} /></label>
          <label>Role / connector<select value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })}>
            {['owner', 'manager', 'director', 'finance', 'admin', 'crm', 'erp', 'disty_pos', 'market_data'].map((r) => <option key={r} value={r}>{r}</option>)}</select></label>
          <label>Region scope<input value={draft.region_scope} onChange={(e) => setDraft({ ...draft, region_scope: e.target.value })} placeholder="* or Korea,Europe" /></label>
        </div>
        <div className="workflow-actions">
          <button className="btn-primary btn-sm" onClick={() => provision(false)}>Provision person</button>
          <button className="btn-outline btn-sm" onClick={() => provision(true)}>Provision service account for connector</button>
        </div>
        {serviceKey && <p className="hint">API key (shown once): <span className="mono">{serviceKey}</span></p>}
      </Card>
      <Card overline="Directory" title="Users" sub={`${users.length} provisioned`}>
        <div className="workflow-list">{users.map((u) => (
          <div className="workflow-row" key={u.user_id}>
            <div><strong>{u.display_name} <span className="mono muted">{u.user_id}</span> <span className="inline-chip">{u.role}{u.connector ? ` · ${u.connector}` : ''}</span></strong>
              <span className="muted">{u.email ?? '—'} · scope {u.region_scope}{u.anonymised_at ? ' · anonymised' : u.active ? '' : ' · deactivated'}</span></div>
            {!u.anonymised_at && <div className="workflow-actions">
              <button className="btn-ghost btn-sm" onClick={() => toggle(u)}>{u.active ? 'Deactivate' : 'Reactivate'}</button>
              <button className="btn-ghost btn-sm" onClick={() => anonymise(u)}>Anonymise</button>
            </div>}
          </div>
        ))}</div>
      </Card>
    </div>
  );
}

async function request(path: string, method: string, body?: unknown) {
  const { request: req } = await import('../api');
  return req(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
}

// --------------------------------------------------------------------------- //
// 6.6 -- run comparison
// --------------------------------------------------------------------------- //

type Comparison = { run_a: string; run_b: string; stamp_differences: string[]; identical: boolean; unattributed_differences: number;
  stamps_a: Record<string, unknown>; stamps_b: Record<string, unknown>;
  rows: { project: string; a_proposed: number | null; b_proposed: number | null; a_rules: string[]; b_rules: string[]; same: boolean; attributed_to: string[] }[] };

export function RunCompare({ runIds }: { runIds: string[] }) {
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [cmp, setCmp] = useState<Comparison | null>(null);
  const [err, setErr] = useState<string | null>(null);
  // Runs arrive after the first render; default to the two most recent once they do.
  useEffect(() => {
    if (runIds.length >= 2 && (!a || !b)) { setA(runIds[1]); setB(runIds[0]); }
  }, [runIds]);
  async function compare() {
    if (!a || !b) return;
    try { setCmp(await apiGet<Comparison>(`/runs/${a}/compare/${b}`)); setErr(null); } catch (e) { setErr(String(e)); }
  }
  if (runIds.length < 2) return null;
  return (
    <Card overline="6.6" title="Compare two runs" sub="Every difference is attributed to a recorded version change — rubric, prompt, model — or labelled unattributed, which is the finding">
      <div className="form-grid">
        <label>Run A<select value={a} onChange={(e) => setA(e.target.value)}>{runIds.map((id) => <option key={id} value={id}>{id.slice(0, 8)}</option>)}</select></label>
        <label>Run B<select value={b} onChange={(e) => setB(e.target.value)}>{runIds.map((id) => <option key={id} value={id}>{id.slice(0, 8)}</option>)}</select></label>
      </div>
      <div className="workflow-actions"><button className="btn-outline btn-sm" onClick={compare}>Compare</button></div>
      {err && <p className="toast error">{err}</p>}
      {cmp && (
        <div>
          <p className="muted">{cmp.identical ? 'Identical.' : `${cmp.rows.filter((r) => !r.same).length} row(s) differ`} · stamps differ on: {cmp.stamp_differences.join(', ') || 'nothing'} · unattributed: {cmp.unattributed_differences}</p>
          <div className="table-wrap"><table className="acru-table"><thead><tr><th>Project</th><th>A</th><th>B</th><th>Rules A</th><th>Rules B</th><th>Attributed to</th></tr></thead>
            <tbody>{cmp.rows.map((r) => <tr key={r.project} className={r.same ? '' : 'needs-review'}><td>{r.project}</td><td>{r.a_proposed?.toFixed(2) ?? '—'}</td><td>{r.b_proposed?.toFixed(2) ?? '—'}</td><td className="mono">{r.a_rules.join(' ')}</td><td className="mono">{r.b_rules.join(' ')}</td><td>{r.same ? '' : r.attributed_to.join(', ') || 'unattributed'}</td></tr>)}</tbody></table></div>
        </div>
      )}
    </Card>
  );
}
