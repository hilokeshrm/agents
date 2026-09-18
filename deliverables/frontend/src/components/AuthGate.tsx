/**
 * Decides what the browser shows before the app renders:
 *
 *   headers / oidc mode  -> the app, as before (identity from headers or SSO)
 *   local mode, no token -> landing / sign-in / sign-up screens
 *   local mode, token    -> /auth/session: provisioned -> the app;
 *                                           not yet    -> the "waiting for a role" screen
 *
 * The mode comes from GET /auth/config so the same build works against any
 * backend; nothing about sign-in is compiled into the bundle.
 */

import { useCallback, useEffect, useState } from 'react';
import App from '../App';
import { apiGet, setActingIdentity } from '../api';
import type { AuthConfig, SessionInfo } from '../session';
import { SIGNED_OUT_EVENT, getToken } from '../session';
import { AuthScreens, Pending, currentAuthPath, go } from './AuthScreens';

type State =
  | { kind: 'loading' }
  | { kind: 'open'; config: AuthConfig }               // headers / oidc: no gate
  | { kind: 'anonymous'; config: AuthConfig }
  | { kind: 'pending'; config: AuthConfig; session: SessionInfo }
  | { kind: 'signed_in'; config: AuthConfig; session: SessionInfo }
  | { kind: 'unreachable'; error: string };

export default function AuthGate() {
  const [state, setState] = useState<State>({ kind: 'loading' });

  const evaluate = useCallback(async () => {
    let config: AuthConfig;
    try {
      config = await apiGet<AuthConfig>('/auth/config');
    } catch (ex) {
      setState({ kind: 'unreachable', error: String((ex as Error).message || ex) });
      return;
    }
    if (config.mode !== 'local') {
      setState({ kind: 'open', config });
      return;
    }
    if (!getToken()) {
      if (!currentAuthPath()) go('/welcome');
      setState({ kind: 'anonymous', config });
      return;
    }
    try {
      const session = await apiGet<SessionInfo>('/auth/session');
      if (!session.provisioned) {
        if (currentAuthPath() !== '/pending') go('/pending');
        setState({ kind: 'pending', config, session });
        return;
      }
      // The display identity the app uses for its landing card and forms.
      setActingIdentity({ actor: session.user_id ?? session.email, role: session.role ?? 'owner', regions: session.region_scope ?? '*' });
      if (currentAuthPath()) go('/');
      setState({ kind: 'signed_in', config, session });
    } catch {
      // 401 already cleared the token (api.ts); show the sign-in screens.
      if (!currentAuthPath()) go('/welcome');
      setState({ kind: 'anonymous', config });
    }
  }, []);

  useEffect(() => {
    void evaluate();
    const onSignedOut = () => void evaluate();
    window.addEventListener(SIGNED_OUT_EVENT, onSignedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, onSignedOut);
  }, [evaluate]);

  switch (state.kind) {
    case 'loading':
      return <div className="auth-page"><p className="muted">Connecting…</p></div>;
    case 'unreachable':
      return (
        <div className="auth-page">
          <div className="auth-card">
            <h1>The API is not reachable</h1>
            <p className="muted">{state.error}</p>
            <button type="button" className="btn-primary" onClick={() => void evaluate()}>Try again</button>
          </div>
        </div>
      );
    case 'open':
    case 'signed_in':
      return <App />;
    case 'pending':
      return <Pending session={state.session} onRefresh={() => void evaluate()} />;
    case 'anonymous':
      return <AuthScreens config={state.config} onSignedIn={() => void evaluate()} />;
  }
}
