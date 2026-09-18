import React from 'react';
import ReactDOM from 'react-dom/client';
import AuthGate from './components/AuthGate';
import EmbeddedAssistant from './components/EmbeddedAssistant';
import { applyPalette, getInitialPalette } from './designThemes';
import { applyTheme, getInitialTheme } from './theme';
import './styles.css';
import './palettes.css';

applyTheme(getInitialTheme());
applyPalette(getInitialPalette());

// WBS 14.6: /embed/assistant serves the read-only panel standalone for the
// Workflow Manager; everything else is the app.
const embedded = window.location.pathname.replace(/\/+$/, '') === '/embed/assistant';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {embedded ? <EmbeddedAssistant embedded /> : <AuthGate />}
  </React.StrictMode>,
);
