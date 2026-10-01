import { useEffect, useRef } from 'react';
import type { Machine } from '../api';

type Props = {
  machines: Machine[];
  value: string;
  onChange: (machineId: string) => void;
};

export function MachineSelector({ machines, value, onChange }: Props) {
  const rail = useRef<HTMLDivElement>(null);
  const options = [{ _id: 'all', name: 'All machines', machine_type: 'Plant-wide' }, ...machines];
  const selectedIndex = Math.max(0, options.findIndex(machine => machine._id === value));

  function selectIndex(index: number, behavior: ScrollBehavior = 'smooth') {
    const safeIndex = Math.max(0, Math.min(options.length - 1, index));
    onChange(options[safeIndex]._id);
    rail.current?.querySelector<HTMLElement>(`[data-machine-index="${safeIndex}"]`)?.scrollIntoView({
      block: 'center', behavior,
    });
  }

  useEffect(() => {
    const frame = requestAnimationFrame(() => rail.current?.querySelector<HTMLElement>(`[data-machine-index="${selectedIndex}"]`)?.scrollIntoView({
      block: 'center', behavior: 'auto',
    }));
    return () => cancelAnimationFrame(frame);
    // The selected value is the source of truth; option count only matters when machines arrive.
  }, [value, machines.length]);

  return <section className="machine-selector" aria-labelledby="machine-selector-title">
    <div className="machine-selector-heading">
      <div><span className="section-label">Production scope</span><h2 id="machine-selector-title">Machines</h2></div>
      <div className="machine-controls">
        <button className="icon-button" type="button" aria-label="Previous machine" onClick={() => selectIndex(selectedIndex - 1)}>↑</button>
        <button className="icon-button" type="button" aria-label="Next machine" onClick={() => selectIndex(selectedIndex + 1)}>↓</button>
      </div>
    </div>
    <div className="machine-wheel" ref={rail} role="listbox" aria-label="Machine scope"
      onKeyDown={event => {
        if (event.key === 'ArrowUp') { event.preventDefault(); selectIndex(selectedIndex - 1); }
        if (event.key === 'ArrowDown') { event.preventDefault(); selectIndex(selectedIndex + 1); }
        if (event.key === 'Home') { event.preventDefault(); selectIndex(0); }
        if (event.key === 'End') { event.preventDefault(); selectIndex(options.length - 1); }
      }}>
      {options.map((machine, index) => <button type="button" role="option"
        aria-selected={machine._id === value} tabIndex={machine._id === value ? 0 : -1}
        data-machine-index={index} data-machine-id={machine._id} key={machine._id}
        className="machine-option" onClick={() => selectIndex(index)}>
        <span className="machine-name">{machine.name}</span>
        <span className="machine-meta">{machine.production_stage || machine.machine_type}</span>
      </button>)}
    </div>
    <p className="scope-summary" aria-live="polite">
      {value === 'all' ? `${machines.length} machines · all production stages` : options[selectedIndex]?.production_stage || options[selectedIndex]?.machine_type}
    </p>
  </section>;
}
