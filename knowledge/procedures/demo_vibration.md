---
source_id: demo_vibration_verification
document_type: verification_policy
policy_version: 1
approval_status: approved_demo
machine_types:
  - demo_press
required_checks:
  - check_id: demo_cycle_test
    required_result: pass
    minimum_cycles: 5
    required_condition: demo_test_condition
---

# Demo vibration verification

This is a synthetic test policy for a demo asset. It is not a real maintenance or machine-safety procedure.

## Required evidence

An operator reports five completed cycles under `demo_test_condition`, explicitly reports that vibration did not recur, and records when the test occurred. The test must occur after the corrective work in the current repair cycle.

## Unknown or failed result

“Running now” does not establish these checks. “Still vibrating” is a failed result and requires a new corrective cycle. An inspection alone does not establish resolution.
