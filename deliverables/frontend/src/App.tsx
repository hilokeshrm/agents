import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import DashboardOverview from './components/DashboardOverview';
import AgentStatusBar from './components/AgentPanel';
import DesignPicker from './components/DesignPicker';
import ProjectDetail, { LiveCalcPreview } from './components/ProjectDetail';
import Sidebar from './components/Sidebar';
import TopBar from './components/TopBar';
import { AuditView, ReviewQueueView, RollupsView } from './components/WorkflowViews';
import ImportView from './components/ImportView';
import RubricView from './components/RubricView';
import AccessView from './components/AccessView';
import { AnalysesView, ConnectorsView, FindingsView, NotificationsView, RoleLanding, UsersView } from './components/PlatformViews';
import EmbeddedAssistant from './components/EmbeddedAssistant';
import DevPortalView from './components/DevPortalView';
import { actingIdentity } from './api';
import { summarizeJudgment } from './agent';
import { money } from './calc';
import { useAgentLog, simulateAgentDelay } from './useAgentLog';
import { useDesignPalette } from './useDesignPalette';
import { useTheme } from './useTheme';
import {
  applyConfidence,
  computeRollup,
  createProject,
  getMe,
  getRegistry,
  listProjects,
  listPendingProposals,
  runAgentScan as requestAgentScan,
  suggestConfidence,
  transitionOpportunity,
} from './store';
import type { ConfidenceResult, Project, Proposal, Registry, TransitionInput, Me } from './types';

type View = 'dashboard' | 'pipeline' | 'intake' | 'review' | 'rollups' | 'audit' | 'import' | 'rubric' | 'access'
  | 'analyses' | 'findings' | 'connectors' | 'notifications' | 'users' | 'assistant' | 'dev';

const BUCKETS = [
  { id: 'project_track', label: 'Project Track' },
];

const emptyForm = {
  region: 'Korea',
  customer: '',
  end_customer: '',
  project: '',
  part_number: '',
  design_status: 'Evaluation',
  stage: 'EVT',
  eau_kpcs: 1000,
  unit_per_set: 10,
  disty_asp: 3,
  resale_asp: 3.2,
  nre_charge_k: 0,
  confidence: 0.5,
  loss_reason: '',
  competitor_part: '',
  owner: import.meta.env.VITE_OPPTRACK_ACTOR ?? 'sales@axcelai.com',
  application: '',
  product_line: '',
  evidence: '',
  confidence_rationale: 'Entered by sales during intake',
};

const PAGE_META: Record<View, { title: string; subtitle: string }> = {
  analyses: { title: 'Analyses', subtitle: 'Deterministic reports · what ran, what waits on data' },
  findings: { title: 'Findings', subtitle: 'The workbook, read by rules V-a..V-i · Phase 0' },
  connectors: { title: 'Connectors', subtitle: 'CRM, ERP, POS/POR, market data · precedence and reconciliation' },
  notifications: { title: 'Notices', subtitle: 'Stalls, overdue milestones, proposals waiting' },
  users: { title: 'Users', subtitle: 'Admin provisioning · no self-registration' },
  assistant: { title: 'Ask OppTrack', subtitle: 'Read-only · every figure traced to a tool' },
  dev: { title: 'Dev Portal', subtitle: 'Live database, tables and process logs · local debugging only' },
  dashboard: {
    title: 'Dashboard',
    subtitle: 'Revenue rollups · Project Track · live automation',
  },
  pipeline: {
    title: 'Pipeline',
    subtitle: 'Opportunity register · confidence & revenue detail',
  },
  intake: {
    title: 'Intake',
    subtitle: 'Capture inputs · auto-calculate on save',
  },
  review: {
    title: 'Review Queue',
    subtitle: 'Human approval for forecast-impacting judgment',
  },
  rollups: {
    title: 'Roll-ups',
    subtitle: 'Backend forecast and portfolio status',
  },
  audit: {
    title: 'Runs & Audit',
    subtitle: 'Judgment runs and append-only decisions',
  },
  import: {
    title: 'Import',
    subtitle: 'Migration and backfill · dry run before anything is written',
  },
  rubric: {
    title: 'Rubric & Matrix A',
    subtitle: 'Published versions · every proposal cites the one that produced it',
  },
  access: {
    title: 'Users & Access',
    subtitle: 'Roles, region scope, and where each rule is enforced',
  },
};

function statusClass(s: string) {
  if (s.includes('Win') || s.includes('Mass')) return 'win';
  if (s === 'Lost') return 'lost';
  if (s === 'Promotion' || s === 'Evaluation') return 'warn';
  return '';
}

export default function App() {
  const [view, setView] = useState<View>('dashboard');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem('ot-sidebar-collapsed') === 'true',
  );
  const [agentPanelOpen, setAgentPanelOpen] = useState(
    () => localStorage.getItem('ot-agent-panel') !== 'false',
  );
  const [search, setSearch] = useState('');
  const [bucket, setBucket] = useState('project_track');
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [judgment, setJudgment] = useState<ConfidenceResult | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [pendingProposals, setPendingProposals] = useState<Proposal[]>([]);
  const [canRunScan, setCanRunScan] = useState(false);
  const [autoAnalyze, setAutoAnalyze] = useState(() => localStorage.getItem('ot-auto-analyze') !== 'false');
  const [designOpen, setDesignOpen] = useState(false);
  const { isDark, onToggle: onToggleTheme } = useTheme();
  const { palette, onSelect: onSelectPalette } = useDesignPalette();
  const { entries, log } = useAgentLog();
  const [booted, setBooted] = useState(false);
  const [grants, setGrants] = useState<Record<string, string>>({});
  const [me, setMe] = useState<Me | null>(null);
  const [registry, setRegistry] = useState<Registry | null>(null);

  const refresh = useCallback(async () => {
    const [loadedProjects, loadedProposals] = await Promise.all([listProjects(), listPendingProposals()]);
    setProjects(loadedProjects);
    setPendingProposals(loadedProposals);
  }, []);

  useEffect(() => {
    void refresh().catch((ex) => setErr(String((ex as Error).message || ex)));
    getMe()
      .then((loaded) => {
        setMe(loaded);
        setGrants(loaded.grants);
        setCanRunScan(loaded.grants.trigger_run === 'yes');
      })
      .catch(() => setCanRunScan(false));
    getRegistry().then(setRegistry).catch(() => setRegistry(null));
  }, [refresh]);

  useEffect(() => {
    if (!msg && !err) return;
    const t = window.setTimeout(() => {
      setMsg(null);
      setErr(null);
    }, 4000);
    return () => window.clearTimeout(t);
  }, [msg, err]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return projects;
    return projects.filter(
      (p) =>
        p.project.toLowerCase().includes(q) ||
        p.customer.toLowerCase().includes(q) ||
        p.region.toLowerCase().includes(q) ||
        p.part_number.toLowerCase().includes(q),
    );
  }, [projects, search]);

  const dashboardProjects = projects;
  const rollup = useMemo(() => computeRollup(projects), [projects]);
  const pendingReview = pendingProposals.length;
  const pendingIds = useMemo(() => new Set(pendingProposals.map((proposal) => proposal.opportunity_id)), [pendingProposals]);

  const selected = useMemo(
    () => projects.find((p) => p.id === selectedId) ?? null,
    [projects, selectedId],
  );

  useEffect(() => {
    // Log the boot roll-up once the first fetch has landed, not with the empty initial state.
    if (booted || projects.length === 0) return;
    setBooted(true);
    const track = projects;
    const r = computeRollup(projects);
    log('calc', 'Pipeline rollups computed', `${track.length} projects · Stretch ${money(r.stretch_revenue_k)} · Projection ${money(r.projection_revenue_k)}`);
    log('agent', 'Agent initialized', 'Backend judgment service ready · review gate enabled');
  }, [booted, log, projects]);

  function toggleSidebar() {
    setSidebarCollapsed((c) => {
      const next = !c;
      localStorage.setItem('ot-sidebar-collapsed', String(next));
      return next;
    });
  }

  function toggleAgentPanel() {
    setAgentPanelOpen((o) => {
      const next = !o;
      localStorage.setItem('ot-agent-panel', String(next));
      return next;
    });
  }

  useEffect(() => {
    if (!autoAnalyze || !selectedId || view !== 'pipeline') return;
    const p = projects.find((x) => x.id === selectedId);
    if (!p) return;

    let cancelled = false;
    (async () => {
      setAnalyzing(true);
      await simulateAgentDelay();
      if (cancelled) return;
      const { result } = await suggestConfidence(p.id);
      if (cancelled) return;
      setJudgment(result);
      setAnalyzing(false);
      log('agent', `Analyzed ${p.project}`, summarizeJudgment(result));
    })();

    return () => {
      cancelled = true;
      setAnalyzing(false);
    };
  }, [selectedId, autoAnalyze, view, projects, log]);

  async function runAgentScan() {
    setBusy(true);
    log('agent', 'Pipeline scan started', 'Evaluating confidence against rubric…');
    try {
      await requestAgentScan();
      await refresh();
      log('success', 'Run complete', 'Backend judgment run finished and proposals are queued for review.');
      setMsg('Backend run complete; review queue refreshed');
    } catch (ex) {
      setErr(String((ex as Error).message || ex));
    } finally {
      setBusy(false);
    }
  }

  function toggleAutoAnalyze() {
    setAutoAnalyze((v) => {
      const next = !v;
      localStorage.setItem('ot-auto-analyze', String(next));
      log('info', next ? 'Auto-analyze enabled' : 'Auto-analyze disabled');
      return next;
    });
  }

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    setErr(null);
    try {
      await createProject({
        region: form.region,
        customer: form.customer,
        end_customer: form.end_customer || null,
        project: form.project,
        part_number: form.part_number,
        design_status: form.design_status,
        stage: form.stage,
        eau_kpcs: form.eau_kpcs,
        unit_per_set: form.unit_per_set || null,
        disty_asp: form.disty_asp,
        resale_asp: form.resale_asp || null,
        nre_charge_k: form.nre_charge_k || null,
        confidence: form.design_status === 'Lost' ? 0 : form.confidence,
        loss_reason: form.design_status === 'Lost' ? form.loss_reason || null : null,
        competitor_part: form.competitor_part || null,
        owner: form.owner,
        application: form.application || null,
        product_line: form.product_line || null,
        evidence: form.evidence || null,
        confidence_rationale: form.confidence_rationale,
      });
      setForm(emptyForm);
      setMsg(`Created ${form.project}`);
      setView('pipeline');
      await refresh();
    } catch (ex) {
      setErr(String((ex as Error).message || ex));
    } finally {
      setBusy(false);
    }
  }

  async function onSuggest(p: Project) {
    setBusy(true);
    setErr(null);
    try {
      const { proposal, result } = await suggestConfidence(p.id);
      setJudgment(result);
      setPendingProposals((current) => [proposal, ...current.filter((item) => item.id !== proposal.id)]);
      log('agent', `Analyzed ${p.project}`, summarizeJudgment(result));
      setMsg(
        `${p.project}: ${result.base_confidence.toFixed(2)} → ${result.calibrated_confidence.toFixed(2)}`,
      );
    } catch (ex) {
      setErr(String((ex as Error).message || ex));
    } finally {
      setBusy(false);
    }
  }

  async function onApply(p: Project) {
    const proposal = pendingProposals.find((item) => item.opportunity_id === p.id);
    if (!proposal || !judgment) return;
    setBusy(true);
    setErr(null);
    try {
      await applyConfidence(proposal.id);
      log('success', `Applied calibration · ${p.project}`, `Confidence ${judgment.base_confidence.toFixed(2)} → ${judgment.calibrated_confidence.toFixed(2)}`);
      setMsg(`Applied calibration for ${p.project}`);
      await refresh();
    } catch (ex) {
      setErr(String((ex as Error).message || ex));
    } finally {
      setBusy(false);
    }
  }

  function onReset() {
    setSelectedId(null);
    setJudgment(null);
    void refresh().then(() => setMsg('Pipeline refreshed from backend')).catch((ex) => setErr(String((ex as Error).message || ex)));
  }

  function openProject(id: string) {
    setSelectedId(id);
    setJudgment(null);
    setView('pipeline');
  }

  async function onTransition(project: Project, input: TransitionInput) {
    setBusy(true);
    try {
      const event = await transitionOpportunity(project.id, input);
      await refresh();
      const label = input.field === 'stage' ? 'Stage' : 'Design status';
      setMsg(`${label} → ${event.to_value}${event.reason_code ? ` (${event.reason_code})` : ''}`);
    } finally {
      setBusy(false);
    }
  }

  function showMessage(message: string, error = false) {
    if (error) setErr(message);
    else setMsg(message);
  }

  return (
    <div className={`shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar
        grants={grants}
        me={me}
        active={view}
        onNavigate={setView}
        collapsed={sidebarCollapsed}
        onToggleCollapse={toggleSidebar}
      />

      <div className="main">
        <TopBar
          title={PAGE_META[view].title}
          subtitle={PAGE_META[view].subtitle}
          search={search}
          onSearch={setSearch}
          onAddOpportunity={() => setView('intake')}
          onReset={onReset}
          onToggleTheme={onToggleTheme}
          onOpenDesign={() => setDesignOpen(true)}
          onToggleSidebar={toggleSidebar}
          sidebarCollapsed={sidebarCollapsed}
          isDark={isDark}
          busy={busy}
          me={me}
          searchDisabled={!['pipeline', 'intake'].includes(view)}
        />

        <div className={`content ${busy ? 'busy-overlay' : ''}`}>
          <AgentStatusBar
            entries={entries}
            pendingReview={pendingReview}
            autoAnalyze={autoAnalyze}
            onToggleAuto={toggleAutoAnalyze}
            onRunScan={runAgentScan}
            canRunScan={canRunScan}
            busy={busy}
            expanded={agentPanelOpen}
            onToggleExpand={toggleAgentPanel}
          />

          {(msg || err) && (
            <div className={`toast ${err ? 'error' : 'success'} toast-animate`}>{err || msg}</div>
          )}

          <div key={view} className="view-panel view-enter">
          {view === 'dashboard' && (
            <div className="dashboard-grid compact-grid" style={{ marginBottom: 16 }}>
              <RoleLanding role={actingIdentity.role} actor={actingIdentity.actor} onNavigate={(v) => setView(v as View)} />
            </div>
          )}
          {view === 'dashboard' && (
            <DashboardOverview
              rollup={rollup}
              projects={dashboardProjects}
              pendingReview={pendingReview}
              onSelect={openProject}
              onNavigatePipeline={() => setView('pipeline')}
            />
          )}

          {view === 'pipeline' && (
            <div className="pipeline-layout">
              <div className="card pipeline-table-card">
                <div className="card-head compact">
                  <div>
                    <h3>Opportunity pipeline</h3>
                    <p className="card-sub">TrackF sample · formulas in browser</p>
                  </div>
                  <div className="pill-tabs">
                    {BUCKETS.map((b) => (
                      <button
                        key={b.id}
                        type="button"
                        className={`pill ${bucket === b.id ? 'active' : ''}`}
                        onClick={() => {
                          setBucket(b.id);
                          setSelectedId(null);
                          setJudgment(null);
                        }}
                      >
                        {b.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="table-wrap">
                  <table className="acru-table">
                    <thead>
                      <tr>
                        <th>Project</th>
                        <th>Region</th>
                        <th>Status</th>
                        <th>Stage</th>
                        <th>Confidence</th>
                        <th>Sales</th>
                        <th>Adjusted</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filtered.map((p) => (
                        <tr
                          key={p.id}
                          className={`${selectedId === p.id ? 'selected' : ''} ${pendingIds.has(p.id) ? 'needs-review' : ''}`}
                          onClick={() => {
                            setSelectedId(p.id);
                            setJudgment(null);
                          }}
                        >
                          <td>
                            <div className="cell-project">
                              <span className="txn-icon sm">{p.project.slice(0, 2).toUpperCase()}</span>
                              <div>
                                <strong>{p.project}</strong>
                                <span className="muted mono">{p.part_number}</span>
                                {pendingIds.has(p.id) && (
                                  <span className="row-flag">Review</span>
                                )}
                              </div>
                            </div>
                          </td>
                          <td>{p.region}</td>
                          <td>
                            <span className={`status-pill ${statusClass(p.design_status)}`}>{p.design_status}</span>
                          </td>
                          <td>{p.stage || '—'}</td>
                          <td className="mono">
                            {p.confidence.toFixed(2)}
                            {p.calibrated_confidence != null && p.calibrated_confidence !== p.confidence && (
                              <span className="llm-delta"> → {p.calibrated_confidence.toFixed(2)}</span>
                            )}
                          </td>
                          <td className="mono">{money(p.sales_revenue_k)}</td>
                          <td className="mono">{money(p.adjusted_revenue_k)}</td>
                        </tr>
                      ))}
                      {!filtered.length && (
                        <tr>
                          <td colSpan={7} className="muted empty-cell">
                            No projects match your search.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {selected ? (
                <div className="card detail-card">
                  <div className="card-head compact">
                    <h3>{selected.project}</h3>
                    <span className="muted">
                      {selected.customer} · {selected.end_customer || '—'}
                    </span>
                  </div>
                  <ProjectDetail
                    project={selected}
                    judgment={judgment}
                    analyzing={analyzing}
                    busy={busy}
                    onSuggest={() => onSuggest(selected)}
                    onApply={() => onApply(selected)}
                    registry={registry}
                    grants={grants}
                    onTransition={(input) => onTransition(selected, input)}
                  />
                </div>
              ) : (
                <div className="card detail-card empty-detail">
                  <p>Select a project to view inputs, calculations, and judgment.</p>
                </div>
              )}
            </div>
          )}

          {view === 'intake' && (
            <div className="intake-layout">
              <form className="card intake-form" onSubmit={onCreate}>
                <div className="card-head compact">
                  <div>
                    <h3>New opportunity</h3>
                    <p className="card-sub">21 user fields · 3 drive revenue math</p>
                  </div>
                </div>

                <div className="form-grid">
                  <label>
                    Region
                    <input value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} required />
                  </label>
                  <label>
                    Customer
                    <input value={form.customer} onChange={(e) => setForm({ ...form, customer: e.target.value })} required />
                  </label>
                  <label>
                    End customer
                    <input value={form.end_customer} onChange={(e) => setForm({ ...form, end_customer: e.target.value })} />
                  </label>
                  <label>
                    Project
                    <input value={form.project} onChange={(e) => setForm({ ...form, project: e.target.value })} required />
                  </label>
                  <label>
                    Part #
                    <input value={form.part_number} onChange={(e) => setForm({ ...form, part_number: e.target.value })} required />
                  </label>
                  <label>
                    Competitor part
                    <input
                      value={form.competitor_part}
                      onChange={(e) => setForm({ ...form, competitor_part: e.target.value })}
                      placeholder="Optional"
                    />
                  </label>
                  <label>
                    Design status
                    <select value={form.design_status} onChange={(e) => setForm({ ...form, design_status: e.target.value })}>
                      {['Promotion', 'Evaluation', 'Sample', 'Design In', 'Design Win', 'Mass Production', 'Lost'].map(
                        (s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ),
                      )}
                    </select>
                  </label>
                  {form.design_status === 'Lost' && (
                    <label>
                      Loss reason (required)
                      <select value={form.loss_reason} onChange={(e) => setForm({ ...form, loss_reason: e.target.value })} required>
                        <option value="">Choose a reason…</option>
                        {(registry?.reason_codes.loss_reason.codes ?? []).map((c) => (
                          <option key={c} value={c}>{c}</option>
                        ))}
                      </select>
                      <span className="muted">A Lost row is entered at confidence 0.00 (Matrix A).</span>
                    </label>
                  )}
                  <label>
                    Stage
                    <select value={form.stage} onChange={(e) => setForm({ ...form, stage: e.target.value })}>
                      {['Concept', 'EVT', 'DVT', 'PVT'].map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="highlight-field">
                    EAU (Kpcs)
                    <input
                      type="number"
                      value={form.eau_kpcs}
                      onChange={(e) => setForm({ ...form, eau_kpcs: Number(e.target.value) })}
                    />
                  </label>
                  <label className="highlight-field">
                    Disty ASP
                    <input
                      type="number"
                      step="0.01"
                      value={form.disty_asp}
                      onChange={(e) => setForm({ ...form, disty_asp: Number(e.target.value) })}
                    />
                  </label>
                  <label>
                    NRE charge ($K)
                    <input
                      type="number"
                      step="1"
                      min={0}
                      value={form.nre_charge_k}
                      onChange={(e) => setForm({ ...form, nre_charge_k: Number(e.target.value) })}
                    />
                  </label>
                  <label className="highlight-field">
                    Confidence
                    <input
                      type="number"
                      step="0.05"
                      min={0}
                      max={1}
                      value={form.confidence}
                      onChange={(e) => setForm({ ...form, confidence: Number(e.target.value) })}
                    />
                  </label>
                  <label>
                    Resale ASP
                    <input
                      type="number"
                      step="0.01"
                      value={form.resale_asp}
                      onChange={(e) => setForm({ ...form, resale_asp: Number(e.target.value) })}
                    />
                  </label>
                  <label>
                    Unit / Set
                    <input
                      type="number"
                      value={form.unit_per_set}
                      onChange={(e) => setForm({ ...form, unit_per_set: Number(e.target.value) })}
                    />
                  </label>
                  <label className="full">
                    Evidence
                    <textarea rows={3} value={form.evidence} onChange={(e) => setForm({ ...form, evidence: e.target.value })} />
                  </label>
                  <label className="full">
                    Confidence rationale
                    <textarea rows={3} value={form.confidence_rationale} onChange={(e) => setForm({ ...form, confidence_rationale: e.target.value })} required />
                  </label>
                </div>

                <div className="form-footer">
                  <button type="submit" className="btn-primary" disabled={busy}>
                    Add opportunity
                  </button>
                </div>
              </form>

              <div className="card preview-card">
                <h3>Live calculation</h3>
                <p className="card-sub">Deterministic — same as production formulas</p>
                <LiveCalcPreview eauKpcs={form.eau_kpcs} distyAsp={form.disty_asp} confidence={form.confidence} />
                <div className="legend-inline stacked">
                  <span><i className="legend-dot user" /> User input</span>
                  <span><i className="legend-dot calc" /> Calculated</span>
                  <span><i className="legend-dot llm" /> Judgment after save</span>
                </div>
              </div>
            </div>
          )}

          {view === 'review' && <ReviewQueueView onMessage={showMessage} onChanged={() => void refresh().catch((ex) => setErr(String((ex as Error).message || ex)))} />}
          {view === 'rollups' && <RollupsView />}
          {view === 'audit' && <AuditView />}
          {view === 'import' && <ImportView onMessage={showMessage} />}
          {view === 'rubric' && <RubricView onMessage={showMessage} />}
          {view === 'access' && <AccessView onMessage={showMessage} />}
          {view === 'analyses' && <AnalysesView role={actingIdentity.role} onMessage={showMessage} />}
          {view === 'findings' && <FindingsView onMessage={showMessage} />}
          {view === 'connectors' && <ConnectorsView onMessage={showMessage} />}
          {view === 'notifications' && <NotificationsView />}
          {view === 'users' && <UsersView onMessage={showMessage} />}
          {view === 'assistant' && <EmbeddedAssistant />}
          {view === 'dev' && <DevPortalView />}
          </div>
        </div>
      </div>

      <DesignPicker
        open={designOpen}
        active={palette}
        isDark={isDark}
        onSelect={onSelectPalette}
        onClose={() => setDesignOpen(false)}
      />
    </div>
  );
}
