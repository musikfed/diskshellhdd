# DiskShell 0.7.5 — Release Guide

## What this release establishes

0.7.5 is the first DiskShell release where the browser is treated as a **replaceable workspace view**, not as the owner of processes or durable state.

Core rule:

```text
UI/view       — replaceable
backend       — replaceable executor
workspace     — persistent
transfer job  — persistent
data          — persistent
```

### StreamCopy River Keeper

StreamCopy persists in SQLite:

- job and media/profile parameters;
- manifest;
- source/destination volume identity;
- per-file state;
- confirmed offsets;
- SHA-256 checkpoints;
- warnings/progress;
- lease owner + expiry.

Incomplete files are written as `.dspart-<job>`. After hot-unplug or backend restart, an arbitrary partial tail is not trusted. River Keeper walks back to the last verified checkpoint, revalidates the source/partial range hash, truncates the unverified tail, and resumes from the safe point.

### Split-brain protection

Persistent state does not itself create split-brain. The risk is two backends concurrently believing they own one job.

Each persistent job therefore carries:

```text
lease_owner
lease_expires_at
```

A live backend renews its lease. If it dies, the lease expires and another backend may claim the job.

### COPY instead of destructive Move

StreamCopy exposes two completion modes:

1. **COPY** — keep the source.
2. **COPY → SHA-256 → DELETE SOURCE** — delete the source only after target write, publish, and strong verification succeed.

On uncertainty, conflict, missing target, or verification failure, the source is retained.

## Workspace

The active page, active volume, and scan id are persisted in backend SQLite.

Therefore refresh, browser close, site-data cleanup, or switching browsers do not define authoritative workspace state.

## Logging

Routine HTTP polling is suppressed from the operator console.

Event journal:

```text
data/logs/diskshell.log
```

It rotates and records meaningful lifecycle events, warnings, and failures rather than every successful GET.

## Install / update

```powershell
git fetch origin
git reset --hard origin/main
npm run build
.\scripts\start-admin.ps1
```

Physical-disk/raw/partition features on Windows require an elevated Administrator backend.

## Post-start checks

1. Open `/api/health` and confirm version `0.7.5`.
2. Confirm the UI restored the previous workspace page.
3. Check `data/logs/diskshell.log`.
4. Test StreamCopy in COPY mode before enabling source deletion.
5. Test hot-unplug/restart recovery only with independently backed-up data.

## Known 0.7.5 boundaries

- River Keeper is local-only.
- Commander still uses its separate transfer manager and is not yet restart-persistent through the same journal.
- Several UI areas still poll instead of using an event fabric.
- Some view preferences still live in localStorage.
- Physical partition-boundary relocation is not implemented.
- Photo object search is not yet a full semantic vision search.
- File indexing is snapshot-oriented rather than a continuously refreshed mini database.

## Operational principle

Do not preserve the “program window”; preserve the **world state of the program**.

After a crash/reboot, a new executor should recover durable state safely, while the browser simply reconnects to that state.
