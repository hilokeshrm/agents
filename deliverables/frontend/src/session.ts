/**
 * The browser side of AUTH_MODE=local: where the session token lives and how
 * the app learns which sign-in mode the API runs.
 *
 * The token is an opaque session id the API can revoke (/auth/logout); it is
 * not a JWT and carries no role. Stored in localStorage so a reload stays
 * signed in; cleared on 401 so a revoked or expired session falls back to the
 * sign-in screen rather than a page of errors.
 */

const TOKEN_KEY = 'ot-session';
export const SIGNED_OUT_EVENT = 'ot-signed-out';

export type AuthConfig = { mode: 'headers' | 'local' | 'oidc'; otp_delivery: 'console' | 'smtp'; min_password_length: number };

export type SessionInfo = {
  email: string;
  display_name: string;
  email_verified: boolean;
  provisioned: boolean;
  user_id: string | null;
  role: string | null;
  role_label: string | null;
  region_scope: string | null;
};

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Private mode: the session lasts for this page only.
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // nothing to clear
  }
  window.dispatchEvent(new Event(SIGNED_OUT_EVENT));
}
