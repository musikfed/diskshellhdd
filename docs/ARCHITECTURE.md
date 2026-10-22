# DiskShell 0.5.6 architecture

DiskShell is layered as React/Vite Admin Workbench → Flask API → Storage Brain/content services → cancellable safe executors → filesystem/Windows storage adapters.

PowerShell is a Windows storage adapter only.

## Per-disk authorization

`DS_ALLOW_DISK_WRITES=0` disables the global override but does not prevent an administrator from temporarily unlocking one selected non-protected physical disk. Runtime authorization is bound to physical identity and expires after 15 minutes. System / Boot / Application disks remain protected.

## Partition / Volume layer

The volume manager supports disk initialization, partition creation in unallocated space, NTFS/exFAT volume formatting, allocation-unit selection, and drive-letter assignment. Whole-disk clear/format is a separate explicitly destructive workflow.

## Cancellable jobs

Quick Index and Placement Executor are cooperative-cancellable. Cross-volume copies use chunks and removable partial targets. Security scans run as cancellable local scanner processes.

## Persistence

SQLite stores scan facts, placement plans, operation journal, Recovery snapshots, and Security results. The UI keeps only active IDs/preferences in localStorage and restores persistent plans after refresh.

## Recovery / Security

Recovery is read-only topology/signature inspection. Security adapters integrate Microsoft Defender and ClamAV without remediation.

Storage Lab still models logical Managed Interleave and NTFS-visible extents only; HDD firmware geometry and actual extent relocation remain separate.

## Storage wizard 0.5.6

Partition-table initialization, partition/volume creation, and whole-disk destructive formatting are separate workflows. The Windows Storage adapter uses `Format-Volume` profiles for NTFS, exFAT, ReFS, FAT32, and FAT.

Volume size and allocation-unit compatibility are validated before destructive execution. The whole-disk wizard can create a smaller first volume and leave the remaining address space unallocated.

Job progress is explicitly determinate or indeterminate instead of displaying invented percentages.

## Adaptive Macro Interleave 0.5.6

The target layout is bounded macro-interleave rather than random fragmentation. Each workload lane has minimum, target, and maximum band sizes plus an extent budget.

A seek-derived lower bound is calculated from measured sequential throughput and seek latency. Large files are segmented into approximately equal extents to avoid tiny tails, while small files remain whole and can be grouped into a lane band.

Real extent relocation remains a separate experimental step and must be benchmarked against normal NTFS and contiguous layouts first.

## Commander / remote transport 0.5.6

The File Manager now uses local/remote endpoint descriptors and one cancellable Commander transfer job. SFTP/FTP credentials are RAM-only. Cross-endpoint moves are copy → size verification → source removal after success.

Remote preview uses a bounded backend cache. Direct transfer preserves the exact destination path; opt-in Smart placement selects a local Storage Class and records a lane/target-band hint. This is placement policy, not a claim of physical platter geometry.
