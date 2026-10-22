# DiskShell 0.5.1 — operator safety and responsibility

DiskShell is intended for system administrators, storage engineers, and other operators who understand the consequences of storage operations.

Destructive operations can permanently destroy data. Before using them, the operator must understand the difference between a physical disk, GPT/MBR partition table, partition, volume, filesystem, drive letter/mount point, and unallocated space.

The project is provided **as-is**. The operator is responsible for selecting the correct physical disk, maintaining backups, reviewing the operation plan, and accepting the consequences of execution. To the extent permitted by applicable law, the project authors do not accept liability for data loss, downtime, or other damage caused by destructive use.

This notice does not replace backups, change-management, or organizational procedures.

## Disk write model in 0.5

With `DS_ALLOW_DISK_WRITES=0`:

- the global disk-write override is disabled;
- one specific non-protected physical disk can still be unlocked from the UI;
- unlock is bound to Number + UniqueId/Serial + Size;
- exact typed confirmation is required;
- runtime unlock expires after 15 minutes;
- the operator can lock it again immediately;
- System / Boot / Application disks cannot be unlocked.

`DS_ALLOW_DISK_WRITES=1` remains a global override for controlled lab/automation environments and is not recommended for normal administration.

## Before destructive execution

1. Verify model, serial, UniqueId, and size.
2. Confirm the disk is not System / Boot / Application.
3. Confirm backups exist.
4. Read the generated plan.
5. Enter the exact confirmation phrase.
6. Re-check partitioning and filesystem after completion.

## Stop / Cancel

Quick Index, Placement Executor, Files Copy/Move, and Security Scan are cancellable.

Cancellation is cooperative: scanners stop between filesystem operations, cross-volume placement copies check cancellation between chunks, and Defender/ClamAV processes are terminated. Already completed atomic operations are not silently reversed.
