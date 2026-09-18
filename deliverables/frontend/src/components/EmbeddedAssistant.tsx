import { useEffect, useState } from 'react';
import { apiGet, apiPost, setActingIdentity } from '../api';

/**
 * Ask OppTrack -- the read-only assistant panel (WBS 14.x), usable inside the
 * app and standalone at /embed/assistant for the Workflow Manager (14.6).
 *
 * Standalone, the host sends `{type: "opptrack.identity", actor, role, regions,
 * token}` over postMessage and receives `{type: "opptrack.answer", ...}` for
 * every answer, plus `{type: "opptrack.ready"}` once. Nothing here writes: the
 * panel says so from the API's own surface report, and an answer with a figure
 * the tools did not return is shown flagged, not trusted.
 */

type Answer = {
  mode: string; answer: string; intent: string; grounded: boolean | null; untraceable: string[];
  citations: string[]; note: string | null; tool_calls: { name: string; summary: string }[];
};
type Surface = { mode: string; model_id: string | null; tools: { name: string }[]; writes: string[] };

export default function EmbeddedAssistant({ embedded = false }: { embedded?: boolean }) {
  const [surface, setSurface] = useState<Surface | null>(null);
  const [question, setQuestion] = useState('');
  const [history, setHistory] = useState<{ q: string; a: Answer }[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet<Surface>('/assistant/surface').then(setSurface).catch(() => setSurface(null));
    if (!embedded) return;
    function onMessage(event: MessageEvent) {
      const data = event.data;
      if (data && data.type === 'opptrack.identity') {
        setActingIdentity({ actor: data.actor, role: data.role, regions: data.regions, token: data.token });
        apiGet<Surface>('/assistant/surface').then(setSurface).catch(() => undefined);
      }
    }
    window.addEventListener('message', onMessage);
    window.parent?.postMessage({ type: 'opptrack.ready' }, '*');
    return () => window.removeEventListener('message', onMessage);
  }, [embedded]);

  async function ask() {
    const q = question.trim();
    if (!q) return;
    setBusy(true);
    try {
      const a = await apiPost<Answer>('/assistant/ask', { question: q });
      setHistory((h) => [{ q, a }, ...h]);
      setQuestion('');
      if (embedded) window.parent?.postMessage({ type: 'opptrack.answer', question: q, answer: a.answer, grounded: a.grounded, citations: a.citations }, '*');
    } catch (e) {
      setHistory((h) => [{ q, a: { mode: 'error', answer: String(e), intent: 'answer', grounded: null, untraceable: [], citations: [], note: null, tool_calls: [] } }, ...h]);
    } finally { setBusy(false); }
  }

  return (
    <div className="card" style={embedded ? { margin: 16 } : undefined}>
      <div className="card-head compact">
        <div>
          <p className="section-overline">Ask OppTrack</p>
          <h3>Read-only assistant</h3>
          <p className="card-sub">
            {surface ? `${surface.mode} mode · ${surface.tools.length} read-only tools · writes: ${surface.writes.length === 0 ? 'none' : surface.writes.join(', ')}` : 'connecting…'}
          </p>
        </div>
      </div>
      <div className="form-grid">
        <label className="span-2">
          Question
          <input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && ask()}
            placeholder="What is the weighted pipeline by region? What if we approve the queue?" />
        </label>
      </div>
      <div className="workflow-actions"><button className="btn-primary btn-sm" disabled={busy} onClick={ask}>{busy ? 'Asking…' : 'Ask'}</button></div>
      <div className="workflow-list">
        {history.map((h, i) => (
          <div className="workflow-row" key={i} style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
            <strong>{h.q}</strong>
            <span style={{ whiteSpace: 'pre-wrap' }}>{h.a.answer}</span>
            <span className="muted">
              {h.a.mode}{h.a.intent !== 'answer' ? ` · ${h.a.intent}` : ''}
              {h.a.grounded === false && <span className="inline-chip warn"> ungrounded: {h.a.untraceable.join(', ')}</span>}
              {h.a.citations.length > 0 && ` · ${h.a.citations.join(' · ')}`}
            </span>
            {h.a.note && <span className="hint">{h.a.note}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
