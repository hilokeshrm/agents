import type { Me } from '../types';
import { getToken } from '../session';
import { signOut } from './AuthScreens';
import {
  IconBrand,
  IconChart,
  IconChevronLeft,
  IconDatabase,
  IconLayout,
  IconPlus,
  IconRocket,
  IconSettings,
  IconTable,
  IconTarget,
  IconUsers,
} from './Icons';

type View = 'dashboard' | 'pipeline' | 'intake' | 'review' | 'rollups' | 'audit' | 'import' | 'rubric' | 'access'
  | 'analyses' | 'findings' | 'connectors' | 'notifications' | 'users' | 'assistant' | 'dev';

type Props = {
  active: View;
  onNavigate: (v: View) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  /** Grants from GET /access/me -- the same copy the API enforces. */
  grants: Record<string, string>;
  /** The resolved identity from the same call; null until it answers. */
  me: Me | null;
};

function initials(id: string): string {
  const parts = id.replace(/[@.].*$/, '').split(/[-_\s]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : id.slice(0, 2)).toUpperCase();
}

const ALLOWS = new Set(['yes', 'own_region', 'all_regions']);

// `needs` names the permission the API checks for that screen. A control a role
// cannot use is removed rather than disabled: a disabled button teaches someone
// that the job is theirs and is being withheld.
const NAV = [
  { id: 'dashboard' as const, label: 'Dashboard', icon: IconLayout },
  { id: 'pipeline' as const, label: 'Pipeline', icon: IconTable },
  { id: 'intake' as const, label: 'Intake', icon: IconPlus, needs: 'create_edit_opportunity' },
  { id: 'review' as const, label: 'Review Queue', icon: IconRocket, needs: 'approve_reject_proposal' },
  { id: 'rollups' as const, label: 'Roll-ups', icon: IconChart },
  { id: 'audit' as const, label: 'Runs & Audit', icon: IconTable },
  { id: 'import' as const, label: 'Import', icon: IconTarget, needs: 'create_edit_opportunity' },
  { id: 'analyses' as const, label: 'Analyses', icon: IconChart },
  { id: 'findings' as const, label: 'Findings', icon: IconTarget, needs: 'create_edit_opportunity' },
  { id: 'notifications' as const, label: 'Notices', icon: IconRocket },
  { id: 'assistant' as const, label: 'Ask', icon: IconSettings },
  { id: 'rubric' as const, label: 'Rubric', icon: IconSettings, needs: 'publish_rubric' },
  { id: 'connectors' as const, label: 'Connectors', icon: IconTable, needs: 'trigger_run' },
  { id: 'users' as const, label: 'Users', icon: IconUsers, needs: 'provision_users' },
  { id: 'access' as const, label: 'Access', icon: IconUsers, needs: 'provision_users' },
  // Not access-matrix gated (no grant exists for it) -- adminOnly instead,
  // matching the backend router's own "local machine only, not really
  // authenticated" posture (app/api/v1/dev.py).
  { id: 'dev' as const, label: 'Dev Portal', icon: IconDatabase, adminOnly: true },
];

export default function Sidebar({ active, onNavigate, collapsed, onToggleCollapse, grants, me }: Props) {
  // Before /access/me answers, show only the screens no grant gates.
  const visible = NAV.filter(
    (item) => (!item.needs || ALLOWS.has(grants[item.needs] ?? 'no')) && (!item.adminOnly || me?.role === 'admin'),
  );

  return (
    <aside className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-brand">
        <span className="brand-mark">
          <IconBrand />
        </span>
        {!collapsed && (
          <div>
            <span className="brand-name">AXCELAI</span>
            <span className="brand-tagline">Opportunity Tracking</span>
          </div>
        )}
      </div>

      <nav className="sidebar-nav">
        {!collapsed && <div className="nav-group-label">Workspace</div>}
        {visible.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            className={`nav-item ${active === id ? 'active' : ''}`}
            onClick={() => onNavigate(id)}
            title={label}
          >
            <Icon />
            {!collapsed && <span>{label}</span>}
          </button>
        ))}

      </nav>

      <div className="sidebar-footer">
        {/* Who the API says you are. In development the identity comes from the
            X-OppTrack-* headers (no password); under SSO it is the token's user. */}
        <div
          className={`profile-card ${collapsed ? 'compact' : ''}`}
          title={me ? `${me.user_id} · ${me.role_label} · regions ${me.regions.join(', ')}` : 'Resolving identity…'}
          data-testid="profile-card"
        >
          <div className="avatar">{me ? initials(me.user_id) : '…'}</div>
          {!collapsed && (
            <div className="profile-card-text">
              <strong>{me?.user_id ?? 'Resolving…'}</strong>
              <span className="profile-role">{me?.role_label ?? ''}</span>
              {me && (
                <>
                  <span className="profile-meta">
                    Regions: {me.sees_all_regions ? 'all' : me.regions.join(', ') || 'none'}
                  </span>
                  <span className="profile-meta">
                    Signed in via {getToken() ? 'email + password' : me.identity_source.startsWith('request header') ? 'dev headers (no password)' : 'SSO'}
                  </span>
                  {getToken() ? (
                    <button type="button" className="btn-ghost btn-sm profile-signout" onClick={() => void signOut()}>Sign out</button>
                  ) : (
                    <code className="profile-cred">
                      X-OppTrack-Actor: {me.user_id}{'\n'}X-OppTrack-Role: {me.role}{'\n'}X-OppTrack-Regions: {me.sees_all_regions ? '*' : me.regions.join(',')}
                    </code>
                  )}
                </>
              )}
            </div>
          )}
        </div>
        <button
          type="button"
          className="nav-item collapse-btn"
          onClick={onToggleCollapse}
          title={collapsed ? 'Open sidebar' : 'Close sidebar'}
        >
          <IconChevronLeft className={collapsed ? 'flip' : ''} />
          {!collapsed && <span>Close sidebar</span>}
        </button>
      </div>
    </aside>
  );
}
