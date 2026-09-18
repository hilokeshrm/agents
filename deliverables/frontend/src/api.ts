import { clearToken, getToken } from './session';

const API_BASE = import.meta.env.VITE_API_BASE ?? import.meta.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000/api/v1';

/**
 * Who this client is acting as. A development stand-in for the SSO assertion
 * (WBS 9.4): the API reads these headers to decide role and region scope, so
 * they are the identity, not a display preference. Exported because a write
 * that records an actor -- a transition, a review decision -- must record the
 * same identity the request was authorised under.
 */
export const actingIdentity = {
  actor: import.meta.env.VITE_OPPTRACK_ACTOR ?? 'sales@axcelai.com',
  role: import.meta.env.VITE_OPPTRACK_ROLE ?? 'owner',
  regions: import.meta.env.VITE_OPPTRACK_REGIONS ?? '*',
};

const headers: Record<string, string> = {
  'Content-Type': 'application/json',
  'X-OppTrack-Actor': actingIdentity.actor,
  'X-OppTrack-Role': actingIdentity.role,
  'X-OppTrack-Regions': actingIdentity.regions,
};

/**
 * WBS 14.6: an embedding host (the Workflow Manager) hands the panel its
 * identity over postMessage -- a bearer token when SSO is on, the dev headers
 * otherwise. Applied to every request from then on.
 */
export function setActingIdentity(next: { actor?: string; role?: string; regions?: string; token?: string }) {
  if (next.actor) { actingIdentity.actor = next.actor; headers['X-OppTrack-Actor'] = next.actor; }
  if (next.role) { actingIdentity.role = next.role; headers['X-OppTrack-Role'] = next.role; }
  if (next.regions) { actingIdentity.regions = next.regions; headers['X-OppTrack-Regions'] = next.regions; }
  if (next.token) headers['Authorization'] = `Bearer ${next.token}`;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const merged: Record<string, string> = { ...headers, ...(init?.headers as Record<string, string>) };
  // AUTH_MODE=local: a session token replaces the header stand-in entirely.
  const token = getToken();
  if (token) {
    merged['Authorization'] = `Bearer ${token}`;
    delete merged['X-OppTrack-Actor'];
    delete merged['X-OppTrack-Role'];
    delete merged['X-OppTrack-Regions'];
  }
  // An empty value means "let the browser decide" -- see apiUpload.
  Object.keys(merged).forEach((key) => merged[key] === '' && delete merged[key]);

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers: merged });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      // Keep the HTTP status when the server does not return JSON.
    }
    if (response.status === 401 && token && !path.startsWith('/auth/')) {
      // Revoked or expired session: back to the sign-in screen.
      clearToken();
    }
    throw new Error(`${response.status}: ${detail}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function apiPost<T>(path: string, body: unknown = {}): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) });
}

/**
 * Multipart upload. `Content-Type` is deleted deliberately: the browser has to
 * set it itself so the multipart boundary matches the body it generates.
 */
export function apiUpload<T>(path: string, form: FormData): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: form,
    headers: { 'Content-Type': '' },
  });
}