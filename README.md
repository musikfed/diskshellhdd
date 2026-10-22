# DiskShell HDD 0.5.3

[Русская версия](README.ru.md) · English

**DiskShell is a local Windows 11 Admin Storage Workbench.** It is not a PowerShell wrapper. Operators work with physical disks, partitions, volumes, files, Storage Classes, placement plans, analytics, Recovery, Security, Vault, and Storage Lab. PowerShell is hidden inside the Windows storage adapter only.

## 0.5 highlights

- React/Vite UI redesigned for system administrators and storage engineers.
- System / Boot / Application disks remain backend-protected.
- With `DS_ALLOW_DISK_WRITES=0`, the global override is off, while one selected non-protected physical disk can still be temporarily unlocked from the UI.
- Per-disk unlock is bound to Number + UniqueId/Serial + Size, requires typed confirmation, and expires after 15 minutes.
- Partition/Volume Manager: initialize GPT/MBR, create a partition in unallocated space, format NTFS/exFAT, select allocation unit, and assign a drive letter.
- Whole-disk Clear → GPT → single partition → format remains available only after explicit disk unlock and destructive confirmation.
- Quick Index supports real cooperative Stop/Cancel.
- Two-pane Files Copy/Move run as background jobs with Stop; cancelled partial targets are cleaned while the source is retained.
- Placement Plans persist in SQLite and restore after browser refresh.
- Placement execution runs as a cancellable background job; cross-volume copies are chunked and partial files are removed on cancel.
- Recovery / Forensics stores topology snapshots and performs read-only raw MBR/GPT/filesystem signature probes.
- Security runs local Microsoft Defender or ClamAV scans without remediation, with Stop and persistent result history.
- Analytics, Files, Preview/Archives, Photos/People, Vault, and Storage Lab remain included.
- Python backend only; no Rust.

DiskShell is intended for qualified administrators/engineers who understand physical disks, partition tables, partitions, volumes, filesystems, and drive letters. Destructive actions can permanently destroy data. See [operator safety](docs/SAFETY.md).

## Default safety configuration

```text
DS_ALLOW_FILE_WRITES=0
DS_ALLOW_VAULT_WRITES=0
DS_ALLOW_DISK_WRITES=0   # global override OFF; per-disk UI unlock still available
DS_ALLOW_EXTENT_MOVES=0
```

## Windows quick start

```powershell
git clone "https://github.com/musikfed/diskshellhdd.git" "F:\diskshellhdd"
Set-Location "F:\diskshellhdd"
Copy-Item .env.example .env
uv sync --group dev
uv run ruff check backend tests
uv run pytest -v
npm run ui:install
npm run build
uv run python -m backend.app
```

Open `http://127.0.0.1:8765/`.

See [architecture](docs/ARCHITECTURE.md), [deployment](docs/DEPLOYMENT.md), and [operator safety](docs/SAFETY.md).

## Storage wizard 0.5.3

DiskShell now separates disk initialization, partition/volume creation, and the destructive whole-disk workflow.

- **Initialize GPT** writes the partition table only.
- **Create partition / volume** uses existing unallocated space and accepts an explicit GiB size or the maximum free extent.
- **Clear + first volume** can create a first volume smaller than the physical disk and leave the remainder unallocated for additional volumes.

The Windows Storage `Format-Volume` adapter exposes **NTFS, exFAT, ReFS, FAT32, and FAT** with filesystem-specific allocation-unit choices and size/cluster-count validation.

Progress is truthful: Files and Placement have real percentages; filesystem discovery, Defender/ClamAV, and destructive Windows Storage operations use indeterminate activity when no reliable total is available.

## Adaptive Macro Interleave 0.5.3

Storage Lab no longer models one fixed stripe size. It now uses bounded adaptive macro-bands per workload class.

Band size is derived from the lane policy plus measured sequential throughput and seek latency so seek cost can be amortized without turning files into either tiny fragments or giant monoliths.

Large files are split into approximately equal extents with no tiny tail; small files stay whole; multiple small files of the same class can fill one macro-band.

The simulator reports tiny/oversized split extents, max extents per file, and an overall layout quality score. Real NTFS extent relocation remains disabled and experimental.

## RAW disk workflow 0.5.4

RAW-disk setup is now explicitly staged instead of using the combined shortcut as the primary path: unlock the selected disk, initialize GPT, refresh topology, then create/format a volume from unallocated space.

The UI shows a persistent stepper and a fixed operation-status panel. Windows does not expose a trustworthy percentage for Initialize-Disk/New-Partition/Format-Volume, so DiskShell reports the active stage instead of inventing progress.

Destructive Windows Storage operations require an elevated backend process. DiskShell exposes the elevation state and disables write controls when the backend is not running as Administrator.
