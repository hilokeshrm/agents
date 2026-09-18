import type { Me } from '../types';
import { IconBell, IconChevronLeft, IconMoon, IconPalette, IconPlus, IconSearch, IconSettings, IconSun } from './Icons';

type Props = {
  search: string;
  onSearch: (v: string) => void;
  onAddOpportunity: () => void;
  onReset: () => void;
  onToggleTheme: () => void;
  onOpenDesign: () => void;
  onToggleSidebar: () => void;
  sidebarCollapsed: boolean;
  isDark: boolean;
  busy: boolean;
  me: Me | null;
  title: string;
  subtitle?: string;
  searchDisabled?: boolean;
};

export default function TopBar({
  search,
  onSearch,
  onAddOpportunity,
  onReset,
  onToggleTheme,
  onOpenDesign,
  onToggleSidebar,
  sidebarCollapsed,
  isDark,
  busy,
  me,
  title,
  subtitle,
  searchDisabled,
}: Props) {
  return (
    <header className="topbar">
      <div className="topbar-main">
        <div className="topbar-start">
          <button
            type="button"
            className="icon-btn sidebar-toggle-top"
            onClick={onToggleSidebar}
            aria-label={sidebarCollapsed ? 'Open sidebar' : 'Close sidebar'}
            title={sidebarCollapsed ? 'Open sidebar' : 'Close sidebar'}
          >
            <IconChevronLeft className={sidebarCollapsed ? 'flip' : ''} />
          </button>

          <div className="page-header">
            <h1 className="page-title">{title}</h1>
            {subtitle && <p className="page-subtitle">{subtitle}</p>}
          </div>
        </div>

        <div className="topbar-end">
          <div className="topbar-tools" aria-label="Quick actions">
            <div className="icon-toolbar">
              <button
                type="button"
                className="icon-btn icon-btn-ghost"
                onClick={onToggleTheme}
                aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
                title={isDark ? 'Light mode' : 'Dark mode'}
              >
                {isDark ? <IconSun /> : <IconMoon />}
              </button>
              <button type="button" className="icon-btn icon-btn-ghost" aria-label="Notifications">
                <IconBell />
              </button>
              <button type="button" className="icon-btn icon-btn-ghost" aria-label="Settings">
                <IconSettings />
              </button>
            </div>

            <div className="profile-chip" title={me ? `${me.user_id} · ${me.role_label}` : 'Resolving identity…'}>
              <div className="avatar">{me ? me.user_id.slice(0, 2).toUpperCase() : '…'}</div>
              <div className="profile-text">
                <strong>{me?.role_label ?? 'Resolving…'}</strong>
                <span className="profile-email">{me?.user_id ?? ''}</span>
              </div>
            </div>
          </div>

          <div className="topbar-sep" aria-hidden />

          <div className="topbar-cta">
            <button type="button" className="btn-ghost btn-sm btn-design" onClick={onOpenDesign}>
              <IconPalette />
              <span>Design</span>
            </button>
            <button type="button" className="btn-ghost btn-sm" disabled={busy} onClick={onReset}>
              Refresh
            </button>
            <button type="button" className="btn-primary btn-add" disabled={busy} onClick={onAddOpportunity}>
              <IconPlus />
              <span>Add opportunity</span>
            </button>
          </div>
        </div>
      </div>

      {!searchDisabled && (
        <div className="topbar-search-row">
          <div className="search-wrap">
            <IconSearch />
            <input
              type="search"
              placeholder="Search projects, customers, opportunities…"
              value={search}
              onChange={(e) => onSearch(e.target.value)}
            />
          </div>
        </div>
      )}
    </header>
  );
}
