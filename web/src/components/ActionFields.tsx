import type { ActionForm, Fields } from '../api';
import { label } from '../api';

type Props = { form: ActionForm; fields: Fields; onChange: (fields: Fields) => void; checks?: Fields[] };

export function ActionFields({ form, fields, onChange, checks = [] }: Props) {
  function update(name: string, value: unknown) {
    const next = { ...fields };
    if (value === '' || value === undefined) delete next[name]; else next[name] = value;
    onChange(next);
  }
  return <div className="action-fields">
    {[...form.required, ...form.optional].map(name => {
      const required = form.required.includes(name);
      if (name === 'checks') {
        const evidence = (fields.checks as Fields[] | undefined) || [];
        const definitions: Fields[] = checks.length ? checks : ((fields.checks as Fields[] | undefined) || []).map((entry, index) => ({
          check_id: entry.check_id || `verification_check_${index + 1}`,
        }));
        if (!definitions.length) return <p className="hint" key={name}>Choose the ticket verification plan before entering evidence.</p>;
        return <fieldset key={name}><legend>Verification evidence</legend>{definitions.map((rule, index) => {
          const value = evidence[index] || { check_id: rule.check_id };
          function changeCheck(key: string, result: unknown) {
            const entries: Fields[] = definitions.map((definition, number) => ({ check_id: definition.check_id, ...evidence[number] }));
            entries[index] = { ...value, [key]: result };
            update('checks', entries);
          }
          return <div className="check-form" key={String(rule.check_id)}>
            <strong>{label(String(rule.check_id))}</strong>
            <p className="hint">Required: {rule.minimum_cycles ? `${rule.minimum_cycles} cycles. ` : ''}{rule.required_condition ? `Condition: ${rule.required_condition}.` : ''}</p>
            <label>Test result<select value={String(value.result || 'unknown')} onChange={event => changeCheck('result', event.target.value)}>
              {['unknown', 'pass', 'fail', 'skipped'].map(result => <option key={result}>{result}</option>)}
            </select></label>
            <label>Did the fault occur?<select value={value.fault_present === true ? 'yes' : value.fault_present === false ? 'no' : 'unknown'}
              onChange={event => changeCheck('fault_present', event.target.value === 'unknown' ? null : event.target.value === 'yes')}>
              <option value="unknown">Unknown</option><option value="yes">Yes</option><option value="no">No</option>
            </select></label>
            <label>Completed cycles<input type="number" min={0} value={String(value.cycles ?? '')}
              onChange={event => changeCheck('cycles', event.target.value === '' ? undefined : Number(event.target.value))} /></label>
            {rule.minimum_duration_seconds !== undefined && rule.minimum_duration_seconds !== null && <label>Test duration (seconds)<input type="number" min={0}
              value={String(value.duration_seconds ?? '')} onChange={event => changeCheck('duration_seconds', Number(event.target.value))} /></label>}
            <label>Test condition<input value={String(value.condition || '')} onChange={event => changeCheck('condition', event.target.value)} /></label>
            <label>What did you observe?<textarea rows={2} value={String(value.evidence_text || '')} onChange={event => changeCheck('evidence_text', event.target.value)} /></label>
          </div>;
        })}</fieldset>;
      }
      if (name === 'reported_condition' || name === 'fault_present') return <label key={name}>
        {label(name)}{required ? ' *' : ' (optional)'}<select value={String(fields[name] ?? '')} onChange={event =>
          update(name, name === 'fault_present' ? (event.target.value === '' ? undefined : event.target.value === 'true') : event.target.value)}>
          <option value="">Select</option>{(name === 'reported_condition' ? ['running', 'stopped', 'restricted', 'unknown'] : ['true', 'false']).map(value =>
            <option key={value} value={value}>{name === 'fault_present' ? (value === 'true' ? 'Yes' : 'No') : label(value)}</option>)}
        </select></label>;
      if (name === 'verification_shift') return <label key={name}>{label(name)}{required ? ' *' : ' (optional)'}
        <select value={String(fields[name] ?? '')} onChange={event => update(name, event.target.value)}>
          <option value="">Select</option><option value="day">Day</option><option value="night">Night</option><option value="next_shift">Next shift</option>
        </select></label>;
      if (name === 'priority') return <label key={name}>{label(name)}{required ? ' *' : ' (optional)'}
        <select value={String(fields[name] ?? '')} onChange={event => update(name, event.target.value)}>
          <option value="">Select</option>{['critical', 'high', 'normal', 'low'].map(value => <option key={value} value={value}>{label(value)}</option>)}
        </select></label>;
      if (['note', 'context', 'impact', 'suspected_cause', 'proposed_action', 'work_summary', 'verification_notes'].includes(name)) {
        return <label className={name === 'note' ? 'field-wide' : ''} key={name}>{label(name)}{required ? ' *' : ' (optional)'}
          <textarea rows={name === 'note' ? 3 : 2} value={String(fields[name] ?? '')} onChange={event => update(name, event.target.value)} />
        </label>;
      }
      const numeric = ['policy_version', 'repair_cycle'].includes(name);
      return <label key={name}>{label(name)}{required ? ' *' : ' (optional)'}
        <input type={numeric ? 'number' : name.endsWith('_at') ? 'datetime-local' : 'text'} min={numeric ? 1 : undefined} value={String(fields[name] ?? '')}
          onChange={event => update(name, numeric && event.target.value ? Number(event.target.value) : event.target.value)} />
      </label>;
    })}
  </div>;
}
