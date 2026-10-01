import type { Machine, Ticket } from '../api';

const columns = [
  ['open', 'Open'],
  ['in_progress', 'In progress'],
  ['under_review', 'Under review'],
  ['closed', 'Closed'],
] as const;

type Props = {
  tickets: Ticket[];
  machines: Machine[];
  selectedId?: string;
  onSelect: (ticket: Ticket) => void;
};

function priorityLabel(priority: Ticket['priority']) {
  if (priority === undefined || priority === null || priority === '') return 'Normal';
  if (typeof priority === 'number') return priority <= 1 ? 'Critical' : priority === 2 ? 'High' : `P${priority}`;
  return String(priority).replaceAll('_', ' ');
}

export function KanbanBoard({ tickets, machines, selectedId, onSelect }: Props) {
  const machineNames = new Map(machines.map(machine => [machine._id, machine.name]));
  return <div className="board" aria-label="Ticket board" data-testid="ticket-board">
    {columns.map(([status, title]) => {
      const records = tickets.filter(ticket => ticket.status === status);
      return <section className="column" data-status={status} key={status}>
        <header className="column-heading">
          <span className={`status-dot ${status}`} aria-hidden="true" />
          <h2>{title}</h2><span className="count" aria-label={`${records.length} tickets`}>{records.length}</span>
        </header>
        <div className="ticket-list">
          {records.map(ticket => <button className={`ticket-card ${selectedId === ticket._id ? 'selected' : ''}`}
            data-ticket-id={ticket._id} aria-pressed={selectedId === ticket._id} key={ticket._id} onClick={() => onSelect(ticket)}>
            <span className="ticket-card-topline">
              <span className="ticket-id">{ticket._id}</span>
              <span className={`priority priority-${String(ticket.priority ?? 'normal').toLowerCase()}`}>{priorityLabel(ticket.priority)}</span>
            </span>
            <h3>{ticket.title}</h3>
            <p className="ticket-symptom">{ticket.symptom}</p>
            <dl className="ticket-context">
              <div><dt>Machine</dt><dd>{machineNames.get(ticket.machine_id) || ticket.machine_id}</dd></div>
              <div><dt>Stage</dt><dd>{ticket.production_stage || 'Not assigned'}</dd></div>
              <div><dt>Vehicle</dt><dd>{ticket.vehicle_id || '—'}</dd></div>
              <div><dt>Part</dt><dd>{ticket.part_name || '—'}</dd></div>
            </dl>
            <div className="card-footer">
              <span>{ticket.next_action?.role ? `Next · ${ticket.next_action.role}` : 'Workflow complete'}</span>
              <span>Cycle {ticket.repair_cycle}</span>
            </div>
            {ticket.next_action && <span className="next-action-line">{ticket.next_action.description}</span>}
          </button>)}
          {!records.length && <p className="column-empty">No {title.toLowerCase()} tickets</p>}
        </div>
      </section>;
    })}
  </div>;
}
