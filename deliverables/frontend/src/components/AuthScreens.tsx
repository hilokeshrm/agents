/**
 * Landing, sign-up, code verification, sign-in, password reset and the
 * "waiting for a role" screen -- shown only when the API runs AUTH_MODE=local.
 *
 * Paths: /welcome, /signup, /verify, /login, /reset, /pending. The app itself
 * stays at /. Navigation is pushState so a refresh lands on the same screen;
 * AuthGate in main.tsx owns the decision of which of these to show.
 */

import { useEffect, useState, type FormEvent } from 'react';
import { apiPost, request } from '../api';
import { IconBrand } from './Icons';
import type { AuthConfig, SessionInfo } from '../session';
import { clearToken, setToken } from '../session';

export type AuthPath = '/welcome' | '/signup' | '/verify' | '/login' | '/reset' | '/pending';

export function currentAuthPath(): AuthPath | null {
  const p = window.location.pathname.replace(/\/+$/, '') || '/';
  return (['/welcome', '/signup', '/verify', '/login', '/reset', '/pending'] as AuthPath[]).includes(p as AuthPath)
    ? (p as AuthPath)
    : null;
}

export function go(path: AuthPath | '/', search = ''): void {
  window.history.pushState({}, '', path + search);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

function emailFromQuery(): string {
  return new URLSearchParams(window.location.search).get('email') ?? '';
}

type OtpOut = { delivery: 'console' | 'smtp'; dev_code: string | null; message: string };
type TokenOut = { token: string; expires_hours: number };

function Frame({ title, lede, children, wide }: { title: string; lede?: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="auth-page">
      <div className={`auth-card ${wide ? 'wide' : ''}`}>
        <button type="button" className="auth-brand" onClick={() => go('/welcome')} aria-label="Home">
          <span className="brand-mark"><IconBrand /></span>
          <span>
            <span className="brand-name">AXCELAI</span>
            <span className="brand-tagline">Opportunity Tracking</span>
          </span>
        </button>
        <h1>{title}</h1>
        {lede && <p className="auth-lede">{lede}</p>}
        {children}
      </div>
    </div>
  );
}

function Notice({ kind, children }: { kind: 'error' | 'success'; children: React.ReactNode }) {
  return <div className={`toast ${kind}`} role={kind === 'error' ? 'alert' : 'status'}>{children}</div>;
}

/** Console delivery only: the code came back in the response, so show it. */
function DevCode({ sent }: { sent: OtpOut | null }) {
  if (!sent || sent.delivery !== 'console' || !sent.dev_code) return null;
  return (
    <div className="auth-devcode">
      <strong>Development mail delivery</strong>
      <span>OTP_DELIVERY is <code>console</code>, so no email was sent. Your code is</span>
      <code className="auth-devcode-value" data-testid="dev-code">{sent.dev_code}</code>
      <span className="muted">Set OTP_DELIVERY=smtp with Gmail settings to send it by email instead.</span>
    </div>
  );
}

// ---------------------------------------------------------------------------

export function Landing({ config }: { config: AuthConfig }) {
  return (
    <div className="auth-page landing">
      <header className="landing-top">
        <span className="auth-brand static">
          <span className="brand-mark"><IconBrand /></span>
          <span>
            <span className="brand-name">AXCELAI</span>
            <span className="brand-tagline">Opportunity Tracking</span>
          </span>
        </span>
        <nav>
          <button type="button" className="btn-ghost" onClick={() => go('/login')}>Sign in</button>
          <button type="button" className="btn-primary" onClick={() => go('/signup')}>Create account</button>
        </nav>
      </header>

      <section className="landing-hero">
        <p className="landing-kicker">Design-win pipeline, with the arithmetic kept honest</p>
        <h1>The forecast is computed. The judgment is proposed. A person decides.</h1>
        <p className="landing-lede">
          Opportunity Tracking replaces the pipeline workbook: every revenue number is deterministic, every
          confidence change is a proposal a reviewer approves, rejects or overrides, and every decision is on
          an append-only audit stream.
        </p>
        <div className="landing-cta">
          <button type="button" className="btn-primary" onClick={() => go('/signup')}>Create an account</button>
          <button type="button" className="btn-ghost" onClick={() => go('/login')}>I already have one</button>
        </div>
      </section>

      <section className="landing-grid">
        <article>
          <h3>Deterministic revenue</h3>
          <p>Sales, adjusted and NRE revenue from EAU, ASP and confidence — Python, tested against the workbook's own examples.</p>
        </article>
        <article>
          <h3>Rubric-bounded judgment</h3>
          <p>Thirteen rules propose a confidence move with a verbatim quote and a cap. Nothing changes until a reviewer says so.</p>
        </article>
        <article>
          <h3>Roles the admin assigns</h3>
          <p>Sign up with your work email. What you can see and do comes from the role an admin gives that email — never from the sign-up form.</p>
        </article>
        <article>
          <h3>One audit stream</h3>
          <p>Confidence events, lifecycle moves, owner changes and review decisions — written once, never edited.</p>
        </article>
      </section>

      <footer className="landing-foot muted">
        Sign-in mode: {config.mode} · code delivery: {config.otp_delivery}
      </footer>
    </div>
  );
}

// ---------------------------------------------------------------------------

export function Signup({ config }: { config: AuthConfig }) {
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    if (password !== confirm) { setErr('The two passwords do not match.'); return; }
    if (password.length < config.min_password_length) { setErr(`Use at least ${config.min_password_length} characters.`); return; }
    setBusy(true);
    try {
      const sent = await apiPost<OtpOut>('/auth/signup', { email, display_name: displayName, password });
      sessionStorage.setItem('ot-last-otp', JSON.stringify(sent));
      go('/verify', `?email=${encodeURIComponent(email)}`);
    } catch (ex) {
      setErr(String((ex as Error).message || ex));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Frame title="Create your account" lede="Use your work email. An admin assigns your role after you verify it.">
      {err && <Notice kind="error">{err}</Notice>}
      <form className="form-grid auth-form" onSubmit={submit}>
        <label>
          Display name
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} required autoComplete="name" />
        </label>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={config.min_password_length} autoComplete="new-password" />
          <span className="muted">At least {config.min_password_length} characters.</span>
        </label>
        <label>
          Confirm password
          <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required autoComplete="new-password" />
        </label>
        <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Sending code…' : 'Create account'}</button>
      </form>
      <p className="auth-alt">Already have one? <button type="button" className="link" onClick={() => go('/login')}>Sign in</button></p>
    </Frame>
  );
}

// ---------------------------------------------------------------------------

export function Verify({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState(emailFromQuery());
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sent, setSent] = useState<OtpOut | null>(() => {
    try { return JSON.parse(sessionStorage.getItem('ot-last-otp') ?? 'null'); } catch { return null; }
  });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const out = await apiPost<TokenOut>('/auth/verify', { email, code });
      setToken(out.token);
      sessionStorage.removeItem('ot-last-otp');
      onSignedIn();
    } catch (ex) {
      setErr(String((ex as Error).message || ex));
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setErr(null);
    try {
      const out = await apiPost<OtpOut>('/auth/resend', { email });
      setSent(out);
      sessionStorage.setItem('ot-last-otp', JSON.stringify(out));
    } catch (ex) {
      setErr(String((ex as Error).message || ex));
    }
  }

  return (
    <Frame title="Check your email" lede="Enter the 6-digit code we sent to verify the address.">
      {err && <Notice kind="error">{err}</Notice>}
      {sent && sent.delivery === 'smtp' && <Notice kind="success">{sent.message}</Notice>}
      <DevCode sent={sent} />
      <form className="form-grid auth-form" onSubmit={submit}>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>
        <label>
          Code
          <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" pattern="[0-9]{6}" required autoComplete="one-time-code" className="auth-code" />
        </label>
        <button type="submit" className="btn-primary" disabled={busy || code.length !== 6}>{busy ? 'Checking…' : 'Verify and sign in'}</button>
      </form>
      <p className="auth-alt">
        Didn't get it? <button type="button" className="link" onClick={resend}>Send a new code</button>
      </p>
    </Frame>
  );
}

// ---------------------------------------------------------------------------

export function Login({ onSignedIn }: { onSignedIn: () => void }) {
  const [email, setEmail] = useState(emailFromQuery());
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const out = await apiPost<TokenOut>('/auth/login', { email, password });
      setToken(out.token);
      onSignedIn();
    } catch (ex) {
      const message = String((ex as Error).message || ex);
      if (message.includes('verify your email')) {
        // The API sent a fresh code; take the person to the code screen.
        go('/verify', `?email=${encodeURIComponent(email)}`);
        return;
      }
      setErr(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Frame title="Sign in">
      {err && <Notice kind="error">{err}</Notice>}
      <form className="form-grid auth-form" onSubmit={submit}>
        <label>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" autoFocus />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" />
        </label>
        <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <p className="auth-alt">
        <button type="button" className="link" onClick={() => go('/reset', email ? `?email=${encodeURIComponent(email)}` : '')}>Forgot your password?</button>
        {' · '}
        New here? <button type="button" className="link" onClick={() => go('/signup')}>Create an account</button>
      </p>
    </Frame>
  );
}

// ---------------------------------------------------------------------------

export function Reset() {
  const [email, setEmail] = useState(emailFromQuery());
  const [sent, setSent] = useState<OtpOut | null>(null);
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function start(e: FormEvent) {
    e.preventDefault();
    setErr(null); setBusy(true);
    try { setSent(await apiPost<OtpOut>('/auth/reset/start', { email })); } catch (ex) { setErr(String((ex as Error).message || ex)); } finally { setBusy(false); }
  }

  async function finish(e: FormEvent) {
    e.preventDefault();
    setErr(null); setBusy(true);
    try {
      await apiPost<void>('/auth/reset/finish', { email, code, new_password: password });
      setDone(true);
    } catch (ex) { setErr(String((ex as Error).message || ex)); } finally { setBusy(false); }
  }

  if (done) {
    return (
      <Frame title="Password changed">
        <Notice kind="success">Your password is updated and every other session was signed out.</Notice>
        <button type="button" className="btn-primary" onClick={() => go('/login', `?email=${encodeURIComponent(email)}`)}>Sign in</button>
      </Frame>
    );
  }

  return (
    <Frame title="Reset your password" lede="We send a code to your email; enter it with a new password.">
      {err && <Notice kind="error">{err}</Notice>}
      {!sent ? (
        <form className="form-grid auth-form" onSubmit={start}>
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
          </label>
          <button type="submit" className="btn-primary" disabled={busy}>{busy ? 'Sending…' : 'Send reset code'}</button>
        </form>
      ) : (
        <>
          {sent.delivery === 'smtp' && <Notice kind="success">{sent.message}</Notice>}
          <DevCode sent={sent} />
          <form className="form-grid auth-form" onSubmit={finish}>
            <label>
              Code
              <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" required className="auth-code" />
            </label>
            <label>
              New password
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={10} autoComplete="new-password" />
            </label>
            <button type="submit" className="btn-primary" disabled={busy || code.length !== 6}>{busy ? 'Saving…' : 'Set new password'}</button>
          </form>
        </>
      )}
      <p className="auth-alt"><button type="button" className="link" onClick={() => go('/login')}>Back to sign in</button></p>
    </Frame>
  );
}

// ---------------------------------------------------------------------------

export function Pending({ session, onRefresh }: { session: SessionInfo; onRefresh: () => void }) {
  return (
    <Frame title="You're verified — waiting for a role" lede={`Signed in as ${session.display_name} (${session.email}).`}>
      <Notice kind="success">
        Your email is verified. Roles are not self-assigned on this platform: an admin has to provision
        <strong> {session.email} </strong> on the Users screen with the role and regions you should have.
      </Notice>
      <p className="muted">Once that is done, this page turns into your dashboard — press refresh or sign in again.</p>
      <div className="auth-actions">
        <button type="button" className="btn-primary" onClick={onRefresh}>Check again</button>
        <button type="button" className="btn-ghost" onClick={() => signOut()}>Sign out</button>
      </div>
    </Frame>
  );
}

export async function signOut(): Promise<void> {
  try {
    await request<void>('/auth/logout', { method: 'POST' });
  } catch {
    // Already invalid: clearing locally is enough.
  }
  clearToken();
  go('/welcome');
}

/** Shows the screen for the current path, and re-renders on navigation. */
export function AuthScreens({ config, onSignedIn }: { config: AuthConfig; onSignedIn: () => void }) {
  const [path, setPath] = useState<AuthPath | null>(currentAuthPath());
  useEffect(() => {
    const onPop = () => setPath(currentAuthPath());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);
  switch (path) {
    case '/signup': return <Signup config={config} />;
    case '/verify': return <Verify onSignedIn={onSignedIn} />;
    case '/login': return <Login onSignedIn={onSignedIn} />;
    case '/reset': return <Reset />;
    default: return <Landing config={config} />;
  }
}
