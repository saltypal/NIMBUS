import { useEffect, useState } from 'react';
import { api, label } from '../api';
import type { Diagnostics, InferenceTest } from '../api';
import { InputCapture } from './InputCapture';

export function TestPanel() {
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [source, setSource] = useState('text');
  const [text, setText] = useState('Conveyor drive has an intermittent high-pitch vibration at station 4.');
  const [file, setFile] = useState<File | null>(null);
  const [test, setTest] = useState<InferenceTest | null>(null);
  const [testLlm, setTestLlm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function refreshDiagnostics() {
    setError('');
    try { setDiagnostics(await api<Diagnostics>('/api/diagnostics')); }
    catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
  }

  useEffect(() => { void refreshDiagnostics(); }, []);
  useEffect(() => {
    if (!test || ['succeeded', 'failed', 'complete', 'completed'].includes(test.status)) return;
    const timer = window.setInterval(() => {
      void api<InferenceTest>(`/api/inference-tests/${test._id}`).then(setTest).catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [test?._id, test?.status]);

  async function runTest() {
    if (source !== 'text' && !file) { setError('Record, draw, or upload a source before running the test.'); return; }
    setBusy(true); setError(''); setTest(null);
    try {
      const body = new FormData();
      body.append('source_type', source);
      if (source === 'text' && testLlm) body.append('capability', 'llm');
      if (source === 'text') body.append('text', text); else if (file) body.append('file', file);
      setTest(await api<InferenceTest>('/api/inference-tests', { method: 'POST', body }));
      await refreshDiagnostics();
    } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  }

  return <section className="test-lab" data-testid="diagnostics-panel">
    <div className="test-heading">
      <div><span className="section-label">System test bench</span><h1>Backend & worker diagnostics</h1>
        <p>Run isolated capture checks without creating production tickets.</p></div>
      <button className="secondary" onClick={() => void refreshDiagnostics()}>Refresh diagnostics</button>
    </div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {diagnostics && <div className="diagnostic-grid">
      <article className="diagnostic-card"><span>Database</span><strong className={diagnostics.database.connected ? 'healthy' : 'unhealthy'}>
        {diagnostics.database.connected ? 'Connected' : 'Disconnected'}</strong>
        <p>{diagnostics.database.backend} · {diagnostics.database.name}</p></article>
      <article className="diagnostic-card"><span>Retrieval</span><strong>{diagnostics.retrieval.backend}</strong>
        <p>{diagnostics.retrieval.vector_index_enabled ? 'Vector index enabled' : 'Keyword retrieval'}</p></article>
      <article className="diagnostic-card"><span>Workers</span><strong>{diagnostics.workers.length} registered</strong>
        <p>{Object.entries(diagnostics.capabilities).map(([name, state]) => `${label(name)} ${state.ready_workers}/${state.configured ? 'ready' : 'off'}`).join(' · ')}</p></article>
      <article className="diagnostic-card"><span>Jobs</span><strong>{diagnostics.jobs.queued} queued · {diagnostics.jobs.leased} leased</strong>
        <p>{diagnostics.jobs.succeeded} succeeded · {diagnostics.jobs.failed} failed</p></article>
    </div>}
    <div className="test-workspace">
      <section className="panel"><h2>Capture test</h2><p className="hint">Choose a source. The result reports the actual worker and model when one handles it.</p>
        <InputCapture source={source} onSource={setSource} text={text} onText={setText} onFile={setFile} />
        {source === 'text' && <label className="checkbox-row"><input type="checkbox" checked={testLlm} onChange={event => setTestLlm(event.target.checked)} />
          <span>Test LLM drafting <small>Queues a real worker job when configured.</small></span></label>}
        <button disabled={busy} data-testid="run-inference-test" onClick={() => void runTest()}>{busy ? 'Submitting…' : 'Run isolated test'}</button>
      </section>
      <section className="panel test-result" aria-live="polite"><h2>Latest result</h2>
        {!test ? <p className="empty-copy">No test run in this session.</p> : <>
          <div className="result-status"><span className={`status-dot ${test.status}`} /><strong>{label(test.status)}</strong><code>{test._id}</code></div>
          <dl><div><dt>Capability</dt><dd>{label(test.capability)}</dd></div><div><dt>Source</dt><dd>{label(test.source_type)}</dd></div>
            <div><dt>Worker</dt><dd>{test.worker_id || 'Not assigned'}</dd></div><div><dt>Model</dt><dd>{test.model_id || 'Not reported'}{test.model_revision ? ` · ${test.model_revision}` : ''}</dd></div></dl>
          {test.transcript && <div className="transcript"><span>{test.output_kind === 'draft' ? 'Draft summary' : test.capability ? 'Transcript' : 'Text passthrough'}</span><p>{test.transcript}</p></div>}
          {test.output_kind === 'draft' && test.draft && <details className="draft-output"><summary>Structured draft</summary><pre>{JSON.stringify(test.draft, null, 2)}</pre></details>}
          {test.error && <p className="error" role="alert">{test.error}</p>}
        </>}
      </section>
    </div>
  </section>;
}
