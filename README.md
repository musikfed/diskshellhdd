# DiskShell HDD 0.6.5

[Русская версия](README.ru.md) · English

**DiskShell is a local Windows 11 Admin Storage Workbench.** It is not a PowerShell wrapper. Operators work with physical disks, partitions, volumes, files, Storage Classes, placement plans, analytics, Recovery, Security, Vault, and Storage Lab. PowerShell is hidden inside the Windows storage adapter only.

## First working baseline 0.6.0

- React/Vite UI redesigned for system administrators and storage engineers.
- System / Boot / Application disks remain backend-protected.
- With `DS_ALLOW_DISK_WRITES=0`, the global override stays off while write access can be manually enabled for one selected non-protected physical disk from the UI.
- The per-disk write toggle is bound to Number + UniqueId/Serial + Size, requires no typed unlock phrase, and remains enabled until manually disabled or the backend restarts.
- Partition/Volume Manager: initialize GPT/MBR, create a partition in unallocated space, format NTFS/exFAT, select allocation unit, and assign a drive letter.
- Whole-disk Clear → GPT → single partition → format remains available only after explicit disk unlock and destructive confirmation.
- Quick Index supports real cooperative Stop/Cancel.
- Two-pane Files Copy/Move run as background jobs with Stop; cancelled partial targets are cleaned while the source is retained.
- Placement Plans persist in SQLite and restore after browser refresh.
- Placement execution runs as a cancellable background job; cross-volume copies are chunked and partial files are removed on cancel.
- Recovery / Forensics stores topology snapshots and performs read-only raw MBR/GPT/filesystem signature probes.
- Security runs local Microsoft Defender or ClamAV scans without remediation, with Stop and persistent result history.
- Analytics, Commander Files, Photos/People, Vault, and Storage Lab remain included.
- Python backend only; no Rust.

DiskShell is intended for qualified administrators/engineers who understand physical disks, partition tables, partitions, volumes, filesystems, and drive letters. Destructive actions can permanently destroy data. See [operator safety](docs/SAFETY.md).

## Default safety configuration

```text
DS_ALLOW_FILE_WRITES=0
DS_ALLOW_VAULT_WRITES=0
DS_ALLOW_DISK_WRITES=0   # global override OFF; per-disk WRITE toggle still available
DS_ALLOW_EXTENT_MOVES=0
```

## Windows quick start

Sync/build can run unprivileged:

```powershell
Set-Location "F:\diskshellhdd"
git fetch origin
git reset --hard origin/main
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv sync --group dev
uv run ruff check backend tests
uv run pytest -v
npm run ui:install
npm run build
```

**Run the storage-admin backend elevated. The easiest path from normal PowerShell or the VS Code terminal is:**

```powershell
Set-Location "F:\diskshellhdd"
.\scripts\start-admin.ps1
```

The script requests UAC only for the backend. VS Code also exposes `DiskShell: Backend as Administrator`; `DiskShell: Reopen VS Code as Administrator` elevates the whole editor and its extensions, so use that only for a trusted workspace.

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for the `runas` fallback and Linux/root launch.

With `DS_DEBUG=0`, Waitress is used. Open `http://127.0.0.1:8765/`.

See [deployment](docs/DEPLOYMENT.md) for Linux/root launch instructions.

See [architecture](docs/ARCHITECTURE.md), [deployment](docs/DEPLOYMENT.md), and [operator safety](docs/SAFETY.md).

## Storage wizard 0.6.0

DiskShell now separates disk initialization, partition/volume creation, and the destructive whole-disk workflow.

- **Initialize GPT** writes the partition table only.
- **Create partition / volume** uses existing unallocated space and accepts an explicit GiB size or the maximum free extent.
- **Clear + first volume** can create a first volume smaller than the physical disk and leave the remainder unallocated for additional volumes.

The Windows Storage `Format-Volume` adapter exposes **NTFS, exFAT, ReFS, FAT32, and FAT** with filesystem-specific allocation-unit choices and size/cluster-count validation.

Progress is truthful: Files and Placement have real percentages; filesystem discovery, Defender/ClamAV, and destructive Windows Storage operations use indeterminate activity when no reliable total is available.

## Adaptive Macro Interleave 0.6.0

Storage Lab no longer models one fixed stripe size. It now uses bounded adaptive macro-bands per workload class.

Band size is derived from the lane policy plus measured sequential throughput and seek latency so seek cost can be amortized without turning files into either tiny fragments or giant monoliths.

Large files are split into approximately equal extents with no tiny tail; small files stay whole; multiple small files of the same class can fill one macro-band.

The simulator reports tiny/oversized split extents, max extents per file, and an overall layout quality score. Real NTFS extent relocation remains disabled and experimental.

## RAW disk workflow 0.6.0

RAW-disk setup is explicitly staged: enable WRITE for the selected disk, initialize GPT, refresh topology, then create/format a volume from unallocated space.

The UI shows a persistent stepper and a fixed operation-status panel. Windows does not expose a trustworthy percentage for Initialize-Disk/New-Partition/Format-Volume, so DiskShell reports the active stage instead of inventing progress.

Destructive Windows Storage operations require an elevated backend process. DiskShell exposes the elevation state and disables write controls when the backend is not running as Administrator.

## Commander 0.6.0

`Files` is now the single two-pane Commander; the separate Preview / Archives navigation item has been removed.

- each pane can be Local, SFTP/SSH, FTP, or FTPS;
- local panes expose drive/root selection;
- remote credentials stay in backend RAM only;
- F2 Rename, F3 View, F5 Copy, F6 Move, F7 MkDir, F8 Trash/Delete, F9 Archive, Esc Stop;
- Preview and archive/ISO browsing are integrated in the Commander;
- ZIP/TAR/TAR.GZ/7Z creation, safe ZIP/TAR/7Z extraction, optional 7-Zip CLI support for RAR/CAB/WIM;
- Local↔Local, Local↔Remote, and Remote↔Remote transfer jobs with size verification and cooperative Stop.

`Smart folders` is opt-in. Direct mode copies/moves to the exact open destination; Smart folders only changes the target Storage Class path. It does **not** claim to force NTFS macro-interleave.


## Per-disk WRITE toggle 0.6.0

Disk write enablement no longer uses an `UNLOCK DISK ...` typed phrase and no longer expires after 15 minutes.

A non-protected physical disk now has a direct `WRITE LOCKED ⇄ WRITE ENABLED` toggle. The state exists only in backend memory and lasts until manually disabled or the backend restarts. It is bound to Number + UniqueId + Serial + Size, so replacing the disk on the same number automatically invalidates the permission.

System / Boot / Application disks remain backend-protected. Typed confirmation for the actual destructive operation (Initialize / Format / Create partition) remains a separate execution safeguard.


## Frozen 0.6.0 baseline

- local volume selectors across Examine, Security, Storage Brain, Storage Lab, and both Commander panes;
- indexed directory total sizes in Commander;
- explicit LEFT → RIGHT / RIGHT → LEFT Copy and Move;
- RAM-only FILE WRITE toggle;
- paginated Placement Plans for very large indexes;
- new plans start with **no items selected**; the operator checks the intended batch;
- filter-aware Select all / none;
- Size or SHA-256 cross-volume integrity verification;
- post-publish read-only NTFS logical extent verification against the target macro-band policy;
- forced Managed Interleave writing/rebalancing remains disabled.

**Administrator CLI:** launch the Windows backend from an elevated PowerShell for physical-disk/raw/NTFS features. On Linux use a root shell when elevated access is required, while Windows Storage/NTFS-specific operations remain unavailable. See [DEPLOYMENT.md](docs/DEPLOYMENT.md).

## UI/workspace fixes 0.6.1

- fixed the Commander blank-screen runtime reference;
- active navigation page survives refresh;
- per-page vertical scroll position is restored;
- a persistent global **Active volume** selector is visible across the workspace;
- Vault now has explicit Import-source and Export-destination volume selectors;
- Commander remembers LEFT/RIGHT paths, active pane, Smart folders, and archive format;
- a page-level React error boundary shows runtime errors instead of a blank dark page;
- CI runs ESLint `no-undef` before the Vite build.

## Vault logical volume / folder workflow 0.6.2

- Vault operates on mounted logical volumes (`C:\\`, `F:\\`, `W:\\`), not directly on physical disks;
- an integrated browser navigates folders and files inside the selected volume;
- the operator can select one file or the current folder tree;
- folder import is recursive and preserves relative paths;
- export selects a logical volume and destination directory, restoring nested paths;
- physical disk selectors remain reserved for partitioning, raw access and surface diagnostics.


## Vault location / first creation

First-time Vault creation now selects the storage location explicitly in the UI: **logical volume + folder**, for example `W:\\DiskShellVault`.

- The global `Active volume` selector is not an implicit Vault-location setting; the final path is shown before creation.
- DiskShell refuses to place Vault service files directly in a volume root such as `W:\\`; use a dedicated folder.
- After Create, DiskShell writes `vault.json`, `catalog.bin`, and `objects\\` inside the selected folder.
- The selected path is persisted in `data/vault-location.json` so the backend rediscovers the same Vault after restart.
- The locator stores only the path, never identity, secret, master key, or recovery key.
- `DS_VAULT_ROOT` remains a hard administrator override and disables UI relocation when set.
- Existing Vaults are not moved automatically; location selection applies to first creation.
- The recovery key remains visible until the operator explicitly confirms it was saved.

## Commander multi-selection 0.6.5

- normal click selects one item;
- `Ctrl+Click` toggles individual files/folders;
- `Shift+Click` selects a range;
- `Ctrl+A` selects all items in the active pane;
- each pane has explicit Select all / Clear controls;
- pane status shows selection count and known selected size;
- F5 Copy and F6 Move submit one background batch job for the selected set;
- batch transfer supports Local↔Local, Local↔SFTP/FTP and Remote↔Remote;
- Smart folders use one batch destination-classification request;
- F8 Trash/Delete and F9 Archive accept the selected group;
- F2 Rename, F3 View and Extract require exactly one selected item;
- Stop removes only the current incomplete target while already verified batch items remain completed.


## Vault create diagnostics 0.6.5

When **Create Vault** is disabled, the UI now lists the exact blockers: Vault WRITE gate, selected storage path, non-empty identity, and a secret phrase of at least 8 characters.
