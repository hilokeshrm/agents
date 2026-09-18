import { useEffect, useState } from 'react';
import { getAccessMatrix, getMe, listObservedActors } from '../store';
import type { AccessMatrix, Me, ObservedActor } from '../types';

const ALLOWS = new Set(['yes', 'own_region', 'all_regions']);

/**
 * Users & access (WBS 10.8).
 *
 * Two halves, and the screen is explicit about which is which. The permission
 * matrix and the six enforcement points are real: they are served from
 * app/security/roles.py, the single copy the API itself checks, so this screen
 * cannot drift from what the API does.
 *
 * The people list is not a provisioned user directory -- there is no user table,
 * because accounts come from the corporate directory once SSO lands. What it
 * shows instead is who actually appears in the data: owners of rows and actors
 * on audit events. A roster of names, roles and last-active times that nothing
 * behind this screen could enforce would be a fabrication.
 */
export default function AccessView({ onMessage }: { onMessage: (message: string, error?: boolean) => void }) {
  const [matrix, setMatrix] = useState<AccessMatrix | null>(null);
  const [actors, setActors] = useState<ObservedActor[]>([]);
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    getAccessMatrix().then(setMatrix).catch((error) => onMessage(String(error), true));
    listObservedActors().then(setActors).catch(() => setActors([]));
    getMe().then(setMe).catch(() => setMe(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!matrix) return <div className="card empty-cell">Loading access rules…</div>;

  return (
    <div className="workflow-stack">
      <div className="card">
        <div className="card-head compact">
          <div>
            <p className="section-overline">Admin</p>
            <h3>Users &amp; access</h3>
            <p className="card-sub">
              No public sign-up and no local password. The rule that shapes this screen: region scope
              is enforced in the query, not in the interface.
            </p>
          </div>
        </div>
        {me && (
          <p className="identity-line">
            Acting as <strong>{me.user_id}</strong> · {me.role_label} ·{' '}
            {me.sees_all_regions ? 'all regions' : me.regions.join(', ')}.{' '}
            {me.role === 'admin'
              ? 'You can publish rubric versions and set scopes, and you cannot approve a proposal — so no one can grant themselves sign-off.'
              : `Identity source: ${me.identity_source}`}
          </p>
        )}
      </div>

      <div className="card">
        <div className="card-head compact">
          <div>
            <p className="section-overline">Rules</p>
            <h3>Permission matrix</h3>
            <p className="card-sub">Served from app/security/roles.py — the same copy the API enforces</p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="acru-table matrix-table">
            <thead>
              <tr>
                <th>Action</th>
                {matrix.roles.map((role) => (
                  <th key={role}>{matrix.role_labels[role].replace('Regional ', '').replace('Service account', 'Service')}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matrix.rows.map((row) => (
                <tr key={row.action}>
                  <td>{row.label}</td>
                  {matrix.roles.map((role) => {
                    const grant = row.grants[role];
                    return (
                      <td key={role} className="grant-cell">
                        {ALLOWS.has(grant)
                          ? <span className={`inline-chip ${grant === 'own_region' ? 'warn' : ''}`}>{grant.replace('_', ' ')}</span>
                          : <span className="muted">{grant}</span>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">
          Three cells carry the whole separation of duties: an owner cannot approve their own number,
          a manager cannot edit the rubric that judges it, and an admin who can edit the rubric cannot
          ratify what it produces. Nobody, at any level, can edit an audit entry.
        </p>
      </div>

      <div className="card">
        <div className="card-head compact">
          <div>
            <p className="section-overline">Enforcement</p>
            <h3>How it is applied</h3>
            <p className="card-sub">Six points, and what is actually built at each</p>
          </div>
        </div>
        <div className="workflow-list">
          {matrix.enforcement.map((point) => (
            <div className="workflow-row" key={point.n}>
              <div>
                <strong>{point.n}. {point.point}</strong>
                <span className="muted">{point.detail}</span>
                <span className="muted mono">{point.where}</span>
              </div>
              <span className={`inline-chip ${point.status.startsWith('built') ? '' : 'warn'}`}>
                {point.status.startsWith('built') ? 'built' : 'stand-in'}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-head compact">
          <div>
            <p className="section-overline">Directory</p>
            <h3>People in the data</h3>
            <p className="card-sub">{actors.length} identities observed</p>
          </div>
        </div>
        <div className="table-wrap">
          <table className="acru-table">
            <thead>
              <tr><th>Name</th><th>Appears as</th><th>Rows owned</th><th>Events</th><th>Last seen</th></tr>
            </thead>
            <tbody>
              {actors.length === 0 ? (
                <tr><td colSpan={5} className="empty-cell muted">No identities in the data yet.</td></tr>
              ) : actors.map((actor) => (
                <tr key={actor.name}>
                  <td><strong>{actor.name}</strong></td>
                  <td className="muted">{actor.appears_as.join(', ')}</td>
                  <td className="mono">{actor.opportunities_owned}</td>
                  <td className="mono">{actor.events}</td>
                  <td className="muted">{actor.last_seen ? new Date(actor.last_seen).toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">
          This is not a provisioned user list, and there is no Provision user button: accounts are
          provisioned against the corporate directory, which does not exist yet. Rather than show a
          roster nothing behind this screen could enforce, it reports the identities the data actually
          contains. Deleting a person, when that exists, will anonymise the display name and leave
          their decisions in place — removing the actor would break the chain.
        </p>
      </div>
    </div>
  );
}
