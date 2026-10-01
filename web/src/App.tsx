import { useEffect, useRef, useState } from 'react';
import { api, jsonPost, label } from './api';
import type { Actor, Advice, Fields, Forms, Machine, Role, Submission, Ticket } from './api';
import { ActionFields } from './components/ActionFields';
import { InputCapture } from './components/InputCapture';
import { KanbanBoard } from './components/KanbanBoard';
import { MachineSelector } from './components/MachineSelector';
import { TestPanel } from './components/TestPanel';
import { VehiclePanel } from './components/VehiclePanel';

const statusNames: Record<string, string> = { open: 'Open', in_progress: 'In progress', under_review: 'Under review', closed: 'Closed' };
const actionNames: Record<string, string> = {
  report_fault: 'Report a fault', record_observation: 'Record an observation', record_work: 'Record corrective work',
  submit_for_review: 'Corrective work complete — send to review', submit_verification: 'Submit verification evidence',
  acknowledge_handover: 'Acknowledge handover',
};
const actionLabel = (action: string) => actionNames[action] || label(action);
type Organization = { name?: string; organization?: string; plant_name?: string; stages?: string[]; production_stages?: string[]; [key: string]: unknown };

function initialTheme(): 'light' | 'dark' {
  const saved = localStorage.getItem('shiftover-theme');
  if (saved === 'light' || saved === 'dark') return saved;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export default function App() {
  const [actor, setActor] = useState<Actor>({ person_id: 'op_day', display_name: 'Day operator', role: 'operator' });
  const [shift, setShift] = useState('day');
  const [forms, setForms] = useState<Forms | null>(null);
  const [machines, setMachines] = useState<Machine[]>([]);
  const [machineScope, setMachineScope] = useState('all');
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [organization, setOrganization] = useState<Organization | null>(null);
  const [selected, setSelected] = useState<Ticket | null>(null);
  const [advice, setAdvice] = useState<Advice | null>(null);
  const [action, setAction] = useState('report_fault');
  const [fields, setFields] = useState<Fields>({});
  const [source, setSource] = useState('text');
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [draft, setDraft] = useState<Submission | null>(null);
  const [transcript, setTranscript] = useState('');
  const [tab, setTab] = useState<'board' | 'vehicles' | 'knowledge' | 'tests'>('board');
  const [query, setQuery] = useState('');
  const [knowledge, setKnowledge] = useState<{ source_id: string; text: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [inference, setInference] = useState(false);
  const [clarifying, setClarifying] = useState(false);
  const [pending, setPending] = useState<Submission[]>([]);
  const [theme, setTheme] = useState<'light' | 'dark'>(initialTheme);
  const [showRule, setShowRule] = useState(() => sessionStorage.getItem('shiftover-rule-dismissed') !== 'true');
  const captureAttempt = useRef<{ signature: string; file: File | null; key: string } | null>(null);
  const confirmAttempt = useRef<{ signature: string; key: string } | null>(null);

  const primaryMachines = machines.filter(machine => !machine.legacy_fixture && !machine.legacy && machine.primary_product !== false);
  const effectiveMachineId = selected?.machine_id || (machineScope === 'all' ? '' : machineScope);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('shiftover-theme', theme);
  }, [theme]);

  async function refresh() {
    const ticketPath = machineScope === 'all' ? '/api/tickets?limit=200' : `/api/tickets?machine_id=${encodeURIComponent(machineScope)}&limit=200`;
    const [metadata, assets, records, health, org] = await Promise.all([
      api<Forms>('/api/forms'), api<Machine[]>('/api/machines'), api<Ticket[]>(ticketPath), api<{ inference_enabled: boolean }>('/api/health'),
      api<Organization>('/api/organization').catch(() => null),
    ]);
    setForms(metadata); setMachines(assets); setTickets(records); setInference(health.inference_enabled); setOrganization(org);
    setSelected(current => current ? records.find(record => record._id === current._id) || null : null);
  }

  useEffect(() => { void refresh().catch(failure => setError(String(failure))); }, [machineScope]);
  useEffect(() => {
    if (!selected) { setAdvice(null); return; }
    let active = true;
    let timer: number | undefined;
    const loadAdvice = () => void api<Advice>(`/api/tickets/${selected._id}/advice`).then(result => {
      if (!active) return;
      setAdvice(result);
      if (['queued', 'leased', 'processing'].includes(result.status)) timer = window.setTimeout(loadAdvice, 2000);
    }).catch(() => { if (active) setAdvice(null); });
    loadAdvice();
    return () => { active = false; if (timer) window.clearTimeout(timer); };
  }, [selected?._id]);
  useEffect(() => {
    if (!draft || !draft.processing_status.startsWith('awaiting_')) return;
    const timer = window.setInterval(() => {
      void api<Submission>(`/api/submissions/${draft._id}`).then(record => {
        setDraft(record); if (record.draft) setFields(record.draft.fields);
        setTranscript(record.text_revisions[record.selected_text_revision - 1]?.text || '');
      }).catch(failure => setError(String(failure)));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [draft?._id, draft?.processing_status]);

  async function perform(operation: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await operation(); } catch (failure) { setError(failure instanceof Error ? failure.message : String(failure)); }
    finally { setBusy(false); }
  }
  function preferredAction(ticket: Ticket | null, role = actor.role) {
    if (!ticket) return role === 'operator' ? 'report_fault' : 'record_observation';
    if ((role === 'supervisor' || role === 'maintenance') && ticket.status === 'in_progress') return 'submit_for_review';
    if ((role === 'supervisor' || role === 'maintenance') && ticket.status === 'under_review') return 'submit_verification';
    return 'record_observation';
  }
  function reset(ticket: Ticket | null, nextAction = preferredAction(ticket)) {
    setSelected(ticket); setAction(nextAction); setDraft(null); setFields({}); setText(''); setFile(null);
    setSource('text'); setTranscript(''); setClarifying(false); setError(''); setNotice('');
  }
  function adopt(record: Submission) {
    setDraft(record); setAction(record.action); setFields(record.draft?.fields || {});
    setTranscript(record.text_revisions[record.selected_text_revision - 1]?.text || '');
    setSelected(tickets.find(ticket => ticket._id === record.ticket_id) || null);
  }

  async function capture() {
    if (!effectiveMachineId) throw new Error('Select a machine before creating a production record.');
    if (source !== 'text' && !file) throw new Error('Record or upload a source first.');
    const data = new FormData();
    const metadata = { actor, shift_id: shift, machine_id: effectiveMachineId, ticket_id: selected?._id || null,
      expected_ticket_version: selected?.version || null, action, source_type: source, manual_fields: clarifying ? {} : fields,
      purpose: clarifying ? 'clarification' : 'report', parent_submission_id: clarifying ? draft?._id : null };
    const signature = JSON.stringify({ metadata, text });
    if (!captureAttempt.current || captureAttempt.current.signature !== signature || captureAttempt.current.file !== file) {
      captureAttempt.current = { signature, file, key: crypto.randomUUID() };
    }
    data.append('capture', JSON.stringify({ ...metadata, client_operation_id: captureAttempt.current.key }));
    if (source === 'text') data.append('text', text); else if (file) data.append('file', file);
    const record = await api<Submission>('/api/submissions', { method: 'POST', body: data });
    captureAttempt.current = null;
    if (clarifying && draft) {
      await jsonPost(`/api/submissions/${record._id}/process`, {});
      adopt(await jsonPost<Submission>(`/api/submissions/${draft._id}/process`, {})); setClarifying(false);
    } else adopt(record);
    setNotice('Source saved. Review the transcript and facts before confirming.');
  }

  async function confirm() {
    if (!draft) return;
    const confirmation = { reviewed_by: draft.actor, draft_revision: draft.draft_revision, text_revision: draft.selected_text_revision,
      expected_processing_version: draft.processing_version, expected_ticket_version: draft.draft_context?.ticket?.version ?? null, fields };
    const signature = JSON.stringify({ submission_id: draft._id, confirmation });
    if (!confirmAttempt.current || confirmAttempt.current.signature !== signature) confirmAttempt.current = { signature, key: crypto.randomUUID() };
    let accepted: { status: string };
    try {
      accepted = await jsonPost<{ status: string }>(`/api/submissions/${draft._id}/confirm`, { ...confirmation, operation_id: confirmAttempt.current.key });
    } catch (failure) {
      const latest = await api<Submission>(`/api/submissions/${draft._id}`).catch(() => null);
      if (latest?.confirmation) accepted = latest.confirmation;
      else { if (latest && latest.processing_status !== 'committing') setDraft(latest); throw failure; }
    }
    confirmAttempt.current = null;
    setNotice(accepted.status === 'closed' ? 'Verification passed and the ticket is closed.' : `Recorded. Status: ${label(accepted.status)}.`);
    setDraft(null); setFields({}); setText(''); setFile(null); setAction('record_observation'); await refresh();
  }

  const available = forms?.actions.filter(form => form.roles.includes(actor.role) &&
    (selected ? form.action !== 'report_fault' : ['report_fault', 'record_observation'].includes(form.action))) || [];
  const form = forms?.actions.find(definition => definition.action === action);
  const selectedMachine = machines.find(machine => machine._id === selected?.machine_id);
  const activeCount = tickets.filter(ticket => ticket.status !== 'closed').length;

  return <div className="app-shell">
    <header className="topbar">
      <a href="/" className="wordmark" aria-label="ShiftOver home"><span className="mark" aria-hidden="true">SO</span><span>ShiftOver</span></a>
      <nav className="primary-nav" aria-label="Primary">{(['board', 'vehicles', 'knowledge', 'tests'] as const).map(view => <button key={view}
        className={tab === view ? 'active' : ''} aria-current={tab === view ? 'page' : undefined} onClick={() => setTab(view)}>
        {view === 'tests' ? 'System tests' : label(view)}</button>)}</nav>
      <button className="theme-toggle" aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`} aria-pressed={theme === 'dark'}
        onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}><span aria-hidden="true">{theme === 'light' ? '◐' : '☀'}</span><span>{theme === 'light' ? 'Dark' : 'Light'}</span></button>
    </header>
    <div className="identity-bar"><span className="identity-label">On shift</span>
      <label className="sr-only" htmlFor="person">Person ID</label><input id="person" aria-label="Person ID" value={actor.person_id}
        onChange={event => { setActor({ ...actor, person_id: event.target.value }); setDraft(null); }} />
      <input aria-label="Reporter name" value={actor.display_name} onChange={event => { setActor({ ...actor, display_name: event.target.value }); setDraft(null); }} />
      <select aria-label="Role" value={actor.role} onChange={event => { const role = event.target.value as Role; setActor({ ...actor, role }); reset(selected, preferredAction(selected, role)); }}>
        {['operator', 'supervisor', 'maintenance'].map(role => <option key={role}>{role}</option>)}</select>
      <select aria-label="Shift" value={shift} onChange={event => setShift(event.target.value)}><option>day</option><option>night</option></select>
      <span className="identity-status"><span className="live-dot" />{activeCount} active tickets</span>
    </div>

    <main>
      {showRule && <aside className="handover-bubble" role="note"><div><strong>Closure rule</strong><span>Corrective work moves a ticket to review. Separate verification closes it.</span></div>
        <button className="icon-button" aria-label="Dismiss closure rule" onClick={() => { sessionStorage.setItem('shiftover-rule-dismissed', 'true'); setShowRule(false); }}>×</button></aside>}
      {error && <div role="alert" className="alert error">{error}</div>}{notice && <div role="status" className="alert success">{notice}</div>}

      {tab === 'tests' ? <TestPanel /> : tab === 'vehicles' ? <VehiclePanel machines={machines} onOpenTicket={ticketId => {
        const ticket = tickets.find(record => record._id === ticketId);
        setTab('board'); if (ticket) reset(ticket);
      }} /> : tab === 'knowledge' ? <section className="knowledge-view">
        <div className="view-heading"><div><span className="section-label">Organization knowledge</span><h1>Procedures with traceable sources</h1></div></div>
        <form className="search-row" onSubmit={event => { event.preventDefault(); void perform(async () => {
          const response = await api<{ matches: { source_id: string; text: string }[] }>(`/api/knowledge/search?q=${encodeURIComponent(query)}`); setKnowledge(response.matches);
        }); }}><input aria-label="Search knowledge" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search station procedure, fault, or verification…" /><button>Search</button></form>
        <div className="knowledge-list">{knowledge.map((match, index) => <article className="knowledge-result" key={`${match.source_id}-${index}`}><strong>{match.source_id}</strong><p>{match.text}</p></article>)}</div>
      </section> : <>
        <div className="operations-layout">
          <MachineSelector machines={primaryMachines} value={machineScope} onChange={scope => { reset(null); setMachineScope(scope); }} />
          <section className="board-workspace"><div className="view-heading"><div><span className="section-label">{shift} shift · live production</span>
            <h1>{machineScope === 'all' ? 'Plant handover board' : machines.find(item => item._id === machineScope)?.name || 'Machine board'}</h1></div>
            <div className="heading-actions"><button className="secondary" onClick={() => void perform(refresh)}>Refresh</button>
              <button disabled={machineScope === 'all'} title={machineScope === 'all' ? 'Select a machine first' : undefined}
                onClick={() => reset(null, actor.role === 'operator' ? 'report_fault' : 'record_observation')}>{actor.role === 'operator' ? 'Report fault' : 'Add record'}</button></div></div>
            {!primaryMachines.length ? <div className="empty-state"><h2>No production organization loaded</h2>
              <p>Load the automotive workspace with production stages, machines, parts, vehicles, and starter tickets.</p>
              <button onClick={() => void perform(async () => { await jsonPost('/api/organization/seed', {}); await refresh(); })}>Load production workspace</button></div>
              : <KanbanBoard tickets={tickets} machines={machines} selectedId={selected?._id} onSelect={ticket => reset(ticket)} />}
          </section>
        </div>
        <div className="detail-grid">
          <section className="panel timeline" data-testid="ticket-context-panel">{selected
            ? <TicketHistory ticket={selected} machine={selectedMachine} advice={advice} />
            : <OrganizationContext organization={organization} machines={primaryMachines} activeCount={activeCount} />}</section>
          <section className="panel capture-panel"><div className="panel-title"><div><span className="section-label">{draft ? 'Review & confirm' : 'Production record'}</span>
            <h2>{clarifying ? 'Add a missing detail' : selected ? selected.title : effectiveMachineId ? 'Record at this station' : 'Select a machine or ticket'}</h2></div>
            <span className="mode-badge">{inference ? 'Assisted drafting available' : 'Manual capture'}</span></div>
            {!draft && <label>Action<select aria-label="Action" value={action} onChange={event => { setAction(event.target.value); setFields({}); }}>
              {available.map(definition => <option key={definition.action} value={definition.action}>{actionLabel(definition.action)}</option>)}</select></label>}
            {!draft || clarifying ? <InputCapture source={source} onSource={setSource} text={text} onText={setText} onFile={setFile} /> : <>
              <p className="hint transcript-status">{label(draft.processing_status)} · {draft.actor.display_name}</p>
              <label>Review transcript<textarea rows={4} value={transcript} onChange={event => setTranscript(event.target.value)} /></label>
              <div className="button-row"><button className="secondary" disabled={busy || !transcript.trim()} onClick={() => void perform(async () => {
                adopt(await jsonPost<Submission>(`/api/submissions/${draft._id}/text-revisions`, { text: transcript, actor: draft.actor }));
              })}>Save text correction</button><button className="secondary" onClick={() => { setClarifying(true); setText(''); setSource('text'); setFile(null); }}>Add detail</button></div>
              <button className="text-button" onClick={() => void perform(async () => adopt(await jsonPost<Submission>(`/api/submissions/${draft._id}/manual-form`, draft.actor)))}>Use manual form</button>
              <button className="text-button" onClick={() => void perform(async () => adopt(await jsonPost<Submission>(`/api/submissions/${draft._id}/process`, {})))}>Refresh draft</button>
              {draft.draft?.missing_fields.length ? <p className="missing">Still needed: {draft.draft.missing_fields.map(label).join(', ')}</p> : null}
              {draft.draft && (draft.draft.suggestions.length > 0 || draft.draft.citations.length > 0) && <aside className="suggestions"><strong>{inference ? 'Draft checkpoints' : 'Retrieved knowledge'}</strong>
                {draft.draft.suggestions.map((suggestion, index) => <p key={index}>{suggestion}</p>)}
                {!!draft.draft.citations.length && <p className="citation-line">Sources · {draft.draft.citations.map(citation => String(citation.source_id)).join(', ')}</p>}</aside>}
            </>}
            {!clarifying && form && <ActionFields form={form} fields={fields} onChange={setFields} checks={selected?.verification_plan?.required_checks} />}
            {action === 'submit_for_review' && !fields.policy_id && <button className="text-button" onClick={() => {
              const policy = forms?.policies[0]; if (policy) setFields({ ...fields, policy_id: policy.source_id, policy_version: policy.policy_version });
            }}>Use approved verification policy</button>}
            {action === 'submit_verification' && selected?.verification_plan && <button className="text-button" onClick={() => setFields({ ...fields,
              policy_id: selected.verification_plan!.policy_id, policy_version: selected.verification_plan!.policy_version, repair_cycle: selected.repair_cycle })}>Use this ticket’s verification plan</button>}
            <div className="form-footer"><span className="hint">{draft && !clarifying ? 'Confirm only facts you observed.' : 'The original source stays attached to the record.'}</span>
              <button disabled={busy || !effectiveMachineId || (!!draft && !clarifying && !draft.draft)} onClick={() => void perform(draft && !clarifying ? confirm : capture)}>
                {busy ? 'Saving…' : clarifying ? 'Save detail' : draft ? 'Confirm update' : 'Save & review'}</button></div>
            <button className="text-button" onClick={() => void perform(async () => setPending(await api<Submission[]>('/api/submissions')))}>Resume saved draft</button>
            {pending.filter(record => !['confirmed', 'attached', 'failed'].includes(record.processing_status) && record.actor.person_id === actor.person_id).slice(-8).map(record =>
              <button className="saved-draft" key={record._id} onClick={() => { adopt(record); setPending([]); }}>{actionLabel(record.action)} · {label(record.processing_status)}</button>)}
          </section>
        </div>
      </>}
      <footer><span>ShiftOver · Production continuity</span><span>Evidence closes the loop.</span></footer>
    </main>
  </div>;
}

function TicketHistory({ ticket, machine, advice }: { ticket: Ticket; machine?: Machine; advice: Advice | null }) {
  return <><span className="section-label">Ticket history</span><h2>{ticket.title}</h2>
    <div className="ticket-summary"><span>{ticket._id}</span><span>{statusNames[ticket.status] || label(ticket.status)}</span><span>{machine?.name || ticket.machine_id}</span></div>
    {ticket.next_action && <div className="next-action"><strong>Next · {ticket.next_action.role}</strong><p>{ticket.next_action.description}</p></div>}
    {advice && <aside className="advice-box"><div><strong>{advice.enabled ? 'Suggested checkpoints' : 'Retrieved knowledge'}</strong><span>{label(advice.status)}</span></div>
      {advice.suggestions.map((suggestion, index) => <p key={index}>{suggestion}</p>)}
      {!!advice.citations.length && <p className="citation-line">Sources · {advice.citations.map(citation => citation.chunk_id ? `${citation.source_id} / ${citation.chunk_id}` : citation.source_id).join(', ')}</p>}</aside>}
    <div className="timeline-list">{ticket.activities.map(event => <article className="timeline-event" key={event.event_id}><div className="event-header"><strong>{actionLabel(event.action)}</strong>
      <time>{new Date(event.recorded_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</time></div>
      <p className="hint">{event.actor.display_name} · {event.actor.role} · {statusNames[event.status_after] || event.status_after}</p>
      {Object.entries(event.payload).map(([key, value]) => <p key={key}><span className="field-name">{label(key)}:</span> {typeof value === 'object' ? JSON.stringify(value) : String(value)}</p>)}</article>)}</div>
    <a className="text-button" href={`/api/tickets/${ticket._id}/export`} target="_blank" rel="noreferrer">Export ticket and source history ↗</a></>;
}

function OrganizationContext({ organization, machines, activeCount }: { organization: Organization | null; machines: Machine[]; activeCount: number }) {
  const stages = organization?.production_stages || organization?.stages || [...new Set(machines.map(machine => machine.production_stage).filter(Boolean))] as string[];
  return <><span className="section-label">Organization context</span><h2>{String(organization?.name || organization?.organization || 'Automotive production')}</h2>
    {organization?.plant_name && <p className="hint">{String(organization.plant_name)}</p>}
    <div className="context-stats"><div><strong>{machines.length}</strong><span>machines</span></div><div><strong>{stages.length}</strong><span>stages</span></div><div><strong>{activeCount}</strong><span>active tickets</span></div></div>
    <p className="hint">Choose a ticket to inspect its complete source-linked history, next workflow action, and verification state.</p>
    {!!stages.length && <div className="stage-list">{stages.map(stage => <span key={stage}>{stage}</span>)}</div>}</>;
}
