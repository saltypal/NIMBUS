import { useEffect, useState } from 'react';
import { api, label } from '../api';
import type { Machine, PartCheck, Vehicle } from '../api';

type Props = { machines: Machine[]; onOpenTicket: (ticketId: string) => void };

export function VehiclePanel({ machines, onOpenTicket }: Props) {
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [checks, setChecks] = useState<PartCheck[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [error, setError] = useState('');
  const selected = vehicles.find(vehicle => (vehicle.vehicle_id || vehicle._id) === selectedId);
  const visibleChecks = checks.filter(check => check.vehicle_id === selectedId);
  const stages = [...new Set([...machines.map(machine => machine.production_stage), ...visibleChecks.map(check => check.production_stage)].filter(Boolean))] as string[];
  const machineNames = new Map(machines.map(machine => [machine._id, machine.name]));

  useEffect(() => {
    void Promise.all([api<Vehicle[]>('/api/vehicles'), api<PartCheck[]>('/api/part-checks?limit=200')]).then(([units, records]) => {
      setVehicles(units); setChecks(records);
      if (units.length) setSelectedId(current => current || units[0].vehicle_id || units[0]._id);
    }).catch(failure => setError(failure instanceof Error ? failure.message : String(failure)));
  }, []);

  return <section className="vehicles-view" data-testid="vehicle-stage-matrix">
    <div className="view-heading"><div><span className="section-label">Unit trace</span><h1>Vehicles across production</h1></div>
      <label className="vehicle-picker">Vehicle<select aria-label="Vehicle" value={selectedId} onChange={event => setSelectedId(event.target.value)}>
        {vehicles.map(vehicle => <option key={vehicle._id} value={vehicle.vehicle_id || vehicle._id}>{vehicle.vehicle_id || vehicle._id} · {vehicle.model || 'Vehicle'}</option>)}</select></label></div>
    {error && <div role="alert" className="alert error">{error}</div>}
    {!selected ? <div className="empty-state"><h2>No vehicles recorded</h2><p>Load the production workspace to see vehicle and part checks.</p></div> : <>
      <div className="vehicle-summary"><div><span>Unit</span><strong>{selected.vehicle_id || selected._id}</strong></div><div><span>Model</span><strong>{selected.model || '—'}</strong></div>
        <div><span>Current stage</span><strong>{selected.current_stage || selected.production_stage || '—'}</strong></div><div><span>Disposition</span><strong>{selected.disposition ? label(selected.disposition) : 'In production'}</strong></div></div>
      <div className="stage-matrix">{stages.map(stage => {
        const stageChecks = visibleChecks.filter(check => check.production_stage === stage);
        const state = stageChecks.some(check => check.result === 'issue') ? 'issue' : stageChecks.length && stageChecks.every(check => check.result === 'pass') ? 'pass' : 'pending';
        return <article className={`stage-cell stage-${state}`} key={stage}><span>{stage}</span><strong>{stageChecks.length ? label(state) : 'No checks'}</strong><small>{stageChecks.length} records</small></article>;
      })}</div>
      <section className="panel part-checks"><h2>Part checks</h2>{visibleChecks.map(check => <article className="part-check-row" key={check._id}>
        <span className={`check-result result-${check.result}`}>{label(check.result)}</span><div><strong>{check.part_name}</strong><p>{check.production_stage} · {machineNames.get(check.machine_id) || check.machine_id}</p>{check.note && <p>{check.note}</p>}</div>
        {check.linked_ticket_id && <button className="text-button" onClick={() => onOpenTicket(check.linked_ticket_id!)}>Open ticket →</button>}</article>)}</section>
    </>}
  </section>;
}
