# DiskShell 0.6.0 — operator safety and responsibility

DiskShell is intended for system administrators, storage engineers, and other operators who understand the consequences of storage operations.

Destructive operations can permanently destroy data. Before using them, the operator must understand the difference between a physical disk, GPT/MBR partition table, partition, volume, filesystem, drive letter/mount point, and unallocated space.

The project is provided **as-is**. The operator is responsible for selecting the correct physical disk, maintaining backups, reviewing the operation plan, and accepting the consequences of execution. To the extent permitted by applicable law, the project authors do not accept liability for data loss, downtime, or other damage caused by destructive use.

This notice does not replace backups, change-management, or organizational procedures.

## Write model in 0.6

With `DS_ALLOW_DISK_WRITES=0`:

- the global disk-write override is disabled;
- write access can be enabled for one specific non-protected physical disk from the UI;
- permission is bound to Number + UniqueId/Serial + Size;
- no typed phrase is required to enable WRITE;
- there is no automatic timeout;
- WRITE stays enabled until manually disabled or the backend restarts;
- changing the disk identity automatically invalidates the permission;
- System / Boot / Application disks cannot be write-enabled.

`DS_ALLOW_DISK_WRITES=1` remains a global override for controlled lab/automation environments and is not recommended for normal administration.

File WRITE is a separate gate. With `DS_ALLOW_FILE_WRITES=0`, Commander/Storage Brain can temporarily enable it in backend RAM; it resets on backend restart.

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

## Why destructive storage operations do not expose Stop

Interrupting a workflow between Clear-Disk, Initialize-Disk, New-Partition, and Format-Volume can leave storage in an intermediate state. DiskShell therefore shows activity, serializes write actions, and does not invent a percentage or offer an unsafe forced Stop.

## Remote Commander

SFTP/FTP credentials are not persisted. Remote mutations obey `DS_ALLOW_FILE_WRITES`. Local F8 uses the Recycle Bin; remote Delete has no platform trash and requires explicit confirmation. Cross-endpoint moves remove the source only after a completed size-verified copy.

Remote preview is bounded by a temporary-cache size limit to prevent accidental multi-gigabyte downloads from an F3 preview action.


## Placement / layout safety 0.6.0

New Placement Plans start with no selected items. The operator explicitly checks the intended batch, and capacity/reserve is revalidated before executing that batch.

Integrity verification and layout verification are separate:

- Size/SHA-256 verifies copied bytes;
- NTFS extent verification only checks actual logical extents against target macro-band policy;
- layout `drift` does not mean file corruption;
- with `DS_ALLOW_EXTENT_MOVES=0`, DiskShell does not automatically relocate extents.

DiskShell does not claim visibility into hidden HDD physical geometry.

## Elevated backend

Run physical/raw/NTFS storage features from an **Administrator** PowerShell/Terminal on Windows or a root shell on Linux. Keep `DS_HOST=127.0.0.1` and `DS_DEBUG=0` for elevated/root operation. See [DEPLOYMENT.md](DEPLOYMENT.md).


## 0.8 partition boundary safety

A partition boundary plan is always based on a fresh Windows Storage inventory including offsets and `Get-PartitionSupportedSize` bounds.

Protected system/boot/application physical disks remain read-only for boundary execution. A start-boundary change is plan-only because Windows `Resize-Partition` does not move partition starts. End-boundary execution on a non-protected disk requires:
- the exact identity-bound per-disk WRITE gate;
- Administrator elevation;
- a typed confirmation tied to disk/partition/target size;
- a fresh inventory and identity comparison immediately before execution.

The UI is not a security boundary; the backend rechecks all write authorization.
