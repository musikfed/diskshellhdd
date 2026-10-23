# DiskShell 0.8.x — Engineering Roadmap

Baseline release: **0.7.5 River Keeper**.

DiskShell is evolving toward a persistent workspace runtime:

```text
durable state + durable jobs + replaceable executors + replaceable views
```

## Workstreams

1. River Keeper crash/restart/failure-injection tests plus a manual Windows hot-unplug validation checklist.
2. SSE-first event fabric for workspace, transfers, endpoints, scans and jobs.
3. Backend-owned view state instead of authoritative browser localStorage.
4. StreamCopy v2 microfile batching and HDD locality experiments with separate scan/transfer telemetry.
5. Persistent Commander journal/leases/checkpoints across backend restart.
6. Read-only relocation planner for system/data/cache/archive/junction candidates.
7. Snapshot/atomic updater with rollback on build/health failure.
8. Explicit detached multi-view/multi-monitor windows that do not overwrite the global active page.
9. Persistent remote StreamCopy over SFTP after safe credential/profile rebind.
10. Graphical disk descriptor map: offsets, partitions, gaps, filesystem, health and write state.
11. Safe partition-boundary planner: end grow/shrink; start-boundary movement is treated as relocation/recreate/offline work, not disguised as Resize-Partition.
12. Face/person similarity search and optional local semantic object search.
13. Current SQLite file catalog + FTS/indexes updated during scans for fast search without filesystem traversal per query.

## Safety rules

Destructive partition execution requires identity binding, fresh inventory, explicit confirmation and backup/snapshot warnings. System/boot/application disks remain protected from write execution. Remote secrets are not written into event streams or logs.

## Release slicing

- **0.8.0 Foundation:** docs, events, server view state, multi-view, file catalog/search, descriptor map, resize planner.
- **0.8.1 Data intelligence:** relocation planner, face similarity, local object tagging/search.
- **0.8.2 Transfer convergence:** persistent Commander + StreamCopy microbatch experiments.
- **0.8.3 Remote River:** SFTP persistent StreamCopy.
- **0.8.4 Runtime updates:** snapshot/atomic update hardening and rollback verification.
