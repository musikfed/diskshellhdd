# DiskShell HDD 0.7.5

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


## Vault WRITE RAM toggle 0.6.6

`DS_ALLOW_VAULT_WRITES=0` remains the safe default, but normal Vault use no longer requires editing `.env`. The Vault page exposes a RAM-only `VAULT WRITE LOCKED ⇄ ENABLED` toggle controlling Create, Import/Encrypt, and Export. It resets after backend restart. `DS_ALLOW_VAULT_WRITES=1` remains a persistent environment override.


## SFTP / SSH large-file reliability 0.6.8

Commander now protects long SFTP transfers with a 30-second SSH keepalive, OS TCP keepalive where available, and a 120-second SFTP I/O timeout. Transient SSH/network failures trigger up to four reconnect attempts with 1/2/4/8-second backoff. After reconnect, DiskShell re-reads the partial target size and resumes upload/download from that offset instead of restarting the whole file. Size verification still runs before a Move source is removed. The UI reports reconnect count, retry attempt, and resume offset.

Resume applies while the backend job is alive; backend-restart recovery is not yet persistent.


## Zero-byte file transfer fix 0.6.8

Commander now creates zero-byte files correctly during Copy/Move, including cross-volume and remote workflows. Previously a missing empty target could be mistaken for a completed transfer because both its offset and expected size were zero, causing the following size verification to raise FileNotFoundError. The job current path is also updated before every file, including empty files.


## Commander conflicts / resume / missing sources 0.6.9

Copy/Move now requires an explicit policy when a destination already exists: **Continue partial**, **Replace all**, **Keep both** using `name (1)`, `name (2)`, and so on, **Skip conflicts**, or Cancel. There is no implicit overwrite.

Stop and exhausted reconnect attempts retain the incomplete target instead of deleting it. The transfer job exposes `partial_retained` and the UI offers **Continue partial**. A retry can resume from the actual destination size; directory resume merges file-by-file using the same size-based continuation rule.

If a selected source disappears between browsing and transfer start, or an individual source file disappears while walking a directory, the batch records it as missing/skipped, reports a warning, and continues the remaining items. Replace rechecks that the source still exists before deleting any existing destination.


## Resilient endpoints / backend transfer manager 0.7.0

Copy/Move is now treated as a backend-owned transfer, not a browser-owned operation. UI refreshes or render failures do not stop a live backend job.

A disconnected local volume or a prolonged SSH/SFTP outage moves the job into `waiting_endpoint`. The backend periodically probes the endpoint, verifies local volume identity before resuming, recalculates the actual partial target size, and continues automatically. A different device that happens to reuse the same Windows drive letter is not accepted as the original target.

The same wait/retry policy surrounds directory creation, final size verification, native rename, and Move source cleanup. Drive inventory is refreshed continuously and offline roots are represented as OFFLINE instead of being treated as fatal UI errors.

Scope: the backend process must remain alive. Persistent job recovery across a backend restart is a separate transfer-journal milestone; remote credentials/profiles remain RAM-only.


## StreamCopy EXP 0.7.5 · River Keeper

**StreamCopy · EXP** now persists the transfer river in SQLite rather than relying on RAM-only job state. Manifest items, stable local-volume identities and 128 MiB checkpoints survive backend restart. A job-specific `.dspart` is verified against persisted SHA-256 checkpoint data; the unverified tail is truncated and rewritten from the last safe checkpoint.

Hot-unplug enters `waiting_endpoint` and resumes only when the same volume identity returns. Backend restart creates a new worker for the same persistent job after lease claim.

There is no destructive Move primitive: use **COPY**, or optional **COPY → SHA-256 → DELETE SOURCE** after verified publication. See [docs/STREAMCOPY.md](docs/STREAMCOPY.md).


### Workspace 0.7.3 · current page is backend-owned

The current workbench page, active volume, and scan id are now persisted in backend SQLite rather than browser storage alone. Clearing browser site data or switching browsers does not force a landing page; DiskShell restores the current workspace. An active StreamCopy job on another page is exposed through a `↩ StreamCopy · status` header chip. See [docs/WORKSPACE_STATE.md](docs/WORKSPACE_STATE.md).


## Logging 0.7.5 · operator events instead of polling noise

The browser/UI is treated as a control surface. Successful HTTP polling traffic (`/api/files/roots`, `/api/ui-state`, StreamCopy status, frontend `304`) is no longer printed to the backend console. The console is reserved for warnings and errors.

Meaningful events are written to the rotating `data/logs/diskshell.log` journal: backend start, Commander/StreamCopy lifecycle, endpoint waiting/resume, completed-with-warnings, transfer failures, and HTTP 5xx/unhandled exceptions. Request bodies, cookies, passwords, and remote credentials are not logged. Rotation is 5 MiB with up to five backups. See [docs/LOGGING.md](docs/LOGGING.md).
