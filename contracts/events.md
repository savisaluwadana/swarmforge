# Event payload contract v1

Every event has schema_version, run_id, seq, tick, type, payload (see OpenAPI Event). seq starts at 1, contiguous per run; tick nondecreasing. IDs use scenario IDs, not database UUIDs, except run_id. Optional reason codes should be stable enums documented in implementation. The following table specifies required payload keys; additional diagnostic keys are allowed. Payload validators must enforce these fields; do not treat arbitrary JSON as valid. No personal data or secrets.

| Type | Required payload |
|---|---|
| run.started | manifest_hash, engine_version |
| run.progress | completed, released, duration_ticks |
| run.finished | status, trace_hash (trace hash calculated excluding this field itself) |
| run.invariant_failed | invariant_id, reason, entity_ids |
| robot.moved | robot_id, from:{x,y}, to:{x,y} |
| robot.failed | robot_id, reason |
| robot.waiting | robot_id, reason |
| task.released | task_id |
| task.assigned | task_id, robot_id, epoch, expires_tick, issuer_id |
| task.deferred | task_id, reason |
| task.picked | task_id, robot_id, epoch |
| task.completed | task_id, robot_id, epoch |
| task.stranded | task_id, robot_id, reason |
| task.released_assignment | task_id, robot_id, epoch, reason |
| authority.granted | scope_id or task_id, holder, epoch, expires_tick, issuer_id |
| authority.expired | scope_id or task_id, holder, epoch |
| authority.rejected | task_id, robot_id, epoch, reason |
| network.message_sent | message_id, sender, receiver, kind, deliver_tick, bytes |
| network.message_delivered | message_id, sender, receiver |
| network.message_dropped | message_id, sender, receiver, reason |
| network.fault_started | fault_id, fault_type, targets, end_tick |
| network.fault_ended | fault_id, fault_type, targets |
| command.applied | command_seq, fault_id, applied_tick |
| command.rejected | command_seq, reason |
| motion.conflict | robot_id, target:{x,y}, reason |
| motion.deadlock_suspected | robot_id, waiting_ticks |
| recovery.reconciled | task_id, epoch, outcome |
| recovery.unresolved | task_id, reason |

The renderer uses authoritative state from snapshots and applies committed events. If event type is not understood, request fresh snapshot and show compatibility error rather than guessing. Transport stream.closed is not part of engine history. 
Digest: normalize event run_id away; include schema_version, seq, tick, type, payload; remove trace_hash field from run.finished before hashing. Hash canonical JSON lines with newline after each normalized event. Version canonicalization rules and add golden vectors. For progress events emitted at deterministic logical ticks, include them; any wall-clock-dependent transport progress must not be persisted as semantic event. 
