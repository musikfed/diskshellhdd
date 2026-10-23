# Failure / Recovery Validation

DiskShell must be tested against failure invariants, not only happy paths.

CI covers RAM-cache loss, persistent StreamCopy rediscovery, corrupted `.dspart` rollback to a verified checkpoint, COPY→SHA-256→DELETE SOURCE, journal/lease primitives, workspace persistence, event fabric, current file catalog, and partition-boundary planning.

Real Windows USB validation must use expendable test data with an independent backup:

1. Start a large local StreamCopy.
2. Hot-unplug the destination after progress/checkpoints exist.
3. Confirm the job enters `waiting_endpoint`.
4. Attach a different device that receives the same drive letter: the job must **not** resume because volume identity differs.
5. Reattach the original volume: job should enter `recovering`, validate its checkpoint, truncate unsafe tail if needed, and continue.
6. Kill/restart the backend or reboot Windows mid-transfer. Keep `.dspart-<job>`. After lease expiry the new backend must claim the persisted job and resume from a verified checkpoint.
7. For COPY→SHA-256→DELETE SOURCE, the source must survive until target publish + strong verification complete. A crash after publish must cause re-verification before source cleanup.

Failures include silent overwrite, resuming onto the wrong physical disk, source deletion before verification, trusting arbitrary partial EOF, simultaneous ownership of one job, or losing durable state merely because the browser closed.
