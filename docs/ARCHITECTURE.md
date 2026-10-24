# DiskShell 0.6.0 architecture

DiskShell is layered as React/Vite Admin Workbench → Flask API → Storage Brain/content services → cancellable safe executors → filesystem/Windows storage adapters.

PowerShell is a Windows storage adapter only.

## Write authorization

Physical-disk WRITE and file WRITE are independent runtime gates.

- `DS_ALLOW_DISK_WRITES=0` disables the global disk override; a non-protected disk can be manually write-enabled until manual disable/backend restart, bound to Number + UniqueId + Serial + Size.
- `DS_ALLOW_FILE_WRITES=0` disables the global file override; Commander/Storage Brain can enable a RAM-only FILE WRITE gate.
- System / Boot / Application disks remain backend-protected.

## Partition / Volume layer

The volume manager supports disk initialization, partition creation in unallocated space, NTFS/exFAT volume formatting, allocation-unit selection, and drive-letter assignment. Whole-disk clear/format is a separate explicitly destructive workflow.

## Cancellable jobs

Quick Index and Placement Executor are cooperative-cancellable. Cross-volume copies use chunks and removable partial targets. Security scans run as cancellable local scanner processes.

## Persistence

SQLite stores scan facts, placement plans, operation journal, Recovery snapshots, and Security results. The UI keeps only active IDs/preferences in localStorage and restores persistent plans after refresh.

## Recovery / Security

Recovery is read-only topology/signature inspection. Security adapters integrate Microsoft Defender and ClamAV without remediation.

Storage Lab still models logical Managed Interleave and NTFS-visible extents only; HDD firmware geometry and actual extent relocation remain separate.

## Storage wizard 0.6.0

Partition-table initialization, partition/volume creation, and whole-disk destructive formatting are separate workflows. The Windows Storage adapter uses `Format-Volume` profiles for NTFS, exFAT, ReFS, FAT32, and FAT.

Volume size and allocation-unit compatibility are validated before destructive execution. The whole-disk wizard can create a smaller first volume and leave the remaining address space unallocated.

Job progress is explicitly determinate or indeterminate instead of displaying invented percentages.

## Adaptive Macro Interleave 0.6.0

The target layout is bounded macro-interleave rather than random fragmentation. Each workload lane has minimum, target, and maximum band sizes plus an extent budget.

A seek-derived lower bound is calculated from measured sequential throughput and seek latency. Large files are segmented into approximately equal extents to avoid tiny tails, while small files remain whole and can be grouped into a lane band.

Real extent relocation remains a separate experimental step and must be benchmarked against normal NTFS and contiguous layouts first.

## Commander / remote transport 0.6.0

The File Manager now uses local/remote endpoint descriptors and one cancellable Commander transfer job. SFTP/FTP credentials are RAM-only. Cross-endpoint moves are copy → size verification → source removal after success.

Remote preview uses a bounded backend cache. Direct transfer preserves the exact destination path; opt-in Smart placement selects a local Storage Class and records a lane/target-band hint. This is placement policy, not a claim of physical platter geometry.


## Placement execution 0.6.0

Large Placement Plans remain in SQLite and are paged to the UI. New plans start with `selected=0`, and the executor loads only explicitly checked rows.

Cross-volume execution is chunked copy → fsync → Size/SHA-256 verification → atomic publish. The source is retained for operator review. After publish, DiskShell performs a read-only NTFS extent query.

`layout_lane` and `target_band_bytes` are policy, not physical geometry. Layout verification compares actual NTFS-visible extent count with the approximate macro-band target and reports `conforming / drift / unavailable`. Forced extent relocation remains a later experimental writer/rebalancer milestone.

## Runtime server

With `DS_DEBUG=0`, `python -m backend.app` uses Waitress. An elevated Administrator/root backend should remain loopback-only until remote authentication is complete.


## 0.8 persistent workspace/event layer

The browser is a replaceable view. Authoritative navigation/view state is backend-owned in SQLite. The SSE event fabric at `/api/events` distributes typed workspace, transfer, scan and storage-inventory changes. HTTP polling remains a fallback rather than the primary synchronization channel.

Quick Index serves two purposes: immutable historical scan snapshots and a continuously refreshed current file catalog. The current catalog is optimized for interactive search and may use SQLite FTS5 when available.

Detached views are explicit client views of the same backend workspace. A detached view does not claim ownership of the global active page.

Partition boundary work is split by semantics:
- end-boundary resize may use Windows `Resize-Partition` when the OS reports a supported range and the physical disk is not protected;
- start-boundary changes are relocation/recreate/offline plans and are never disguised as an in-place resize.
