---
source_id: automotive_demo_verification
document_type: verification_policy
policy_version: 1
approval_status: approved_demo
machine_types:
  - transfer_press
  - laser_blanking
  - body_framer
  - robotic_weld_cell
  - paint_pretreatment
  - paint_booth
  - engine_marriage
  - powertrain_test
  - trim_conveyor
  - wheel_alignment
  - end_of_line_test
required_checks:
  - check_id: synthetic_demo_cycle
    required_result: pass
    minimum_cycles: 3
    required_condition: synthetic_demo_condition
---

# Automotive synthetic demo verification

This policy exists only to exercise the ShiftOver review workflow with fictional data. It is not validated engineering guidance, a maintenance procedure, a quality plan, or authorization to operate real equipment.

## Required demo evidence

After the scheduled verification time, the fictional operator records three synthetic cycles under `synthetic_demo_condition`, explicitly records whether the reported demo fault appeared, and supplies evidence text. Only evidence for the current corrective cycle is accepted.

## Failed or unknown demo evidence

A failed synthetic check or observed recurrence starts another corrective cycle. Missing, unknown, inferred, or model-suggested information cannot close a ticket. A suspected cause remains a suggestion until a human records appropriate evidence.
