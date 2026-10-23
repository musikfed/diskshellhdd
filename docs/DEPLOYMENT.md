# Deploying DiskShell 0.7.5

DiskShell 0.7.5 builds on the first frozen admin baseline; GitHub `main` is the source of truth.

## Administrator/root privileges

Read-only filesystem features can run unprivileged, but **run the DiskShell backend from an elevated shell** when using physical disks, Surface Diagnostics, raw Recovery probes, Initialize/Partition/Format, or NTFS extent diagnostics.

The default bind is `127.0.0.1:8765`. Do not expose an elevated/root backend on `0.0.0.0` until proper remote authentication is enabled.

`DS_DEBUG=0` is the recommended runtime. In this mode `python -m backend.app` uses Waitress. Flask debug mode is for local development only.

## Windows 11 — install/update

Dependency installation and frontend build can run from a normal PowerShell:

```powershell
Set-Location "F:\diskshellhdd"

git fetch origin
git reset --hard origin/main

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}

uv sync --group dev
uv run ruff check backend tests
uv run pytest -v

npm run ui:install
npm run build
```

### REQUIRED administrator CLI launch

Physical disk, Surface Diagnostics, raw Recovery, Initialize/Partition/Format and NTFS extent features require an elevated backend.

#### Option A — one command from normal PowerShell or the VS Code terminal

Recommended:

```powershell
Set-Location "F:\diskshellhdd"
.\scripts\start-admin.ps1
```

Equivalent workspace shortcut:

```powershell
npm run backend:admin:win
```

The script checks the current process token. If it is not elevated, Windows shows the standard UAC prompt and starts **only the backend** in an elevated PowerShell. This is safer than keeping the whole editor elevated.

A cmd.exe / double-click wrapper is also available:

```cmd
scripts\start-admin.cmd
```

#### Option B — VS Code task

In VS Code:

```text
Ctrl+Shift+P
→ Tasks: Run Task
→ DiskShell: Backend as Administrator
```

The task calls `scripts/start-admin.ps1`; after the UAC prompt the backend is elevated while the original VS Code process can stay unprivileged.

If you specifically want an **elevated integrated terminal**, use the second task, or run `npm run vscode:admin:win`:

```text
Ctrl+Shift+P
→ Tasks: Run Task
→ DiskShell: Reopen VS Code as Administrator
```

After UAC, the reopened workspace can run:

```powershell
uv run python -m backend.app
```

⚠ In this mode **all VS Code extensions and workspace tasks also run with Administrator privileges**. Use it only for a trusted workspace.

#### Option C — manual UAC launch

```powershell
Start-Process powershell -Verb RunAs
```

Then:

```powershell
Set-Location "F:\diskshellhdd"
uv run python -m backend.app
```

#### About `runas`

Alternate credentials are possible:

```cmd
runas /user:Administrator "powershell.exe -NoExit -Command \"Set-Location 'F:\diskshellhdd'; uv run python -m backend.app\""
```

On localized Windows the built-in account name may differ, for example `Администратор`.

However, `runas` is **not a reliable substitute for UAC elevation**. The built-in Administrator account may be disabled, account names are locale-dependent, and alternate credentials do not always provide the required high-integrity token. Prefer `Start-Process ... -Verb RunAs` or `scripts/start-admin.ps1`.

Open:

```text
http://127.0.0.1:8765/
```

With `DS_DEBUG=0`, the admin runtime is served by Waitress.

## Linux — bash

Linux can run the Web UI, SQLite index, Analytics, Commander, SFTP/FTP, and other portable components. Windows Storage cmdlets, Windows physical-drive paths, and NTFS/fsutil-specific functions are Windows-specific and may be unavailable on Linux.

Install/build as a **normal user**:

```bash
cd /path/to/diskshellhdd

git fetch origin
git reset --hard origin/main

test -f .env || cp .env.example .env

uv sync --group dev
uv run ruff check backend tests
uv run pytest -v

npm run ui:install
npm run build
```

### Administrator/root CLI launch

Do not run `sudo uv sync` or `sudo npm`. Elevate only the backend process.

Ready-made launcher:

```bash
cd /path/to/diskshellhdd
bash scripts/start-admin.sh
```

or the workspace shortcut:

```bash
npm run backend:admin:linux
```

Equivalent manual command:

```bash
sudo -E "$(pwd)/.venv/bin/python" -m backend.app
```

Open:

```text
http://127.0.0.1:8765/
```

If root creates files under `data/`, account for their ownership on later unprivileged runs.

## Safety gates

Recommended defaults:

```text
DS_HOST=127.0.0.1
DS_DEBUG=0

DS_ALLOW_FILE_WRITES=0
DS_ALLOW_VAULT_WRITES=0
DS_ALLOW_DISK_WRITES=0
DS_ALLOW_EXTENT_MOVES=0
```

- File writes have a RAM-only UI toggle until manual disable/backend restart.
- Physical disk writes have a separate identity-bound per-disk toggle.
- System / Boot / Application disks remain backend-protected.
- Actual NTFS extent relocation remains disabled.

## First Vault creation and storage location

Normally leave `DS_VAULT_ROOT` empty. On **Vault → Create Vault**, choose a logical volume and a dedicated folder:

```text
Volume: W:\\
Folder: DiskShellVault
Result: W:\\DiskShellVault
```

DiskShell creates `vault.json`, `catalog.bin`, and `objects\\` inside that directory. The selected path is persisted in `data/vault-location.json`; this locator contains no passwords or keys.

Using the volume root `W:\\` itself is rejected. If policy requires a configuration-fixed location, set `DS_VAULT_ROOT=W:\\DiskShellVault`; that becomes a hard override and disables the UI location selector.

Save the displayed recovery key somewhere separate from the Vault disk. DiskShell cannot display it again after the warning is dismissed.

## First working workflow

1. Verify disk identity/topology in **Disks**.
2. Run a **Quick** read-only Surface Diagnostic.
3. Select a local volume in **Examine** and build a Quick Index.
4. Review Analytics.
5. In **Storage Brain**, select the target HDD volume/root and source scope.
6. New plans start with **no items selected**. Check only the files to move, or filter and select the filtered set.
7. Enable `FILE WRITE`.
8. Choose Size or SHA-256 integrity verification.
9. Apply the checked batch.
10. After publish, DiskShell queries actual **NTFS logical extents** and reports layout `conforming / drift / unavailable`.

## “Smart fragmentation” status

0.6.0 does **not** force NTFS into a checkerboard macro-interleave layout. It calculates lane/band policy, transfers selected data, verifies integrity, reads actual NTFS extents, and compares those extents against the planned macro-band profile.

This is logical NTFS layout verification. DiskShell cannot see exact hidden platter/head/angular geometry controlled by HDD firmware.

The forced Managed Interleave writer/rebalancer remains a later experimental milestone and stays disabled while `DS_ALLOW_EXTENT_MOVES=0`.

See [SAFETY.md](SAFETY.md) and [ARCHITECTURE.md](ARCHITECTURE.md).


### Commander 0.6.4

The frontend supports multi-selection with `Ctrl+Click`, `Shift+Click`, `Ctrl+A`, and explicit Select all / Clear controls. Copy/Move run as one batch job with aggregate progress. Rename/View/Extract intentionally remain single-item operations.


## Vault WRITE gate

Keep `DS_ALLOW_VAULT_WRITES=0` as the normal default. Enable `VAULT WRITE` from the Vault page when creating a Vault, importing/encrypting data, or exporting data. The permission lives only in backend RAM and resets to locked after restart. Use `DS_ALLOW_VAULT_WRITES=1` only when a persistent environment override is intentionally desired.


## SFTP / SSH large files

Commander requires no extra switch for SFTP resilience. Version 0.6.7 uses a 30-second SSH keepalive, OS TCP keepalive when available, a 120-second SFTP I/O timeout, and up to four reconnect attempts with 1/2/4/8-second backoff. After reconnect, the current transfer resumes from the partial target size and is size-verified before completion.

This retry/resume state lives in the running backend job; restarting the backend does not yet persist or restore unfinished transfers.


## Commander: disconnects, partial targets, and name conflicts

From 0.6.9, an existing destination never triggers an implicit overwrite. The UI requires an explicit **Continue partial / Replace / Keep both / Skip / Cancel** decision. Keep both allocates the next free indexed name such as `file (1).ext` or `Folder (1)`.

After reconnect attempts are exhausted, or after Stop, the incomplete target is retained. **Continue partial** starts a new job using the actual target size as the resume offset. Missing sources are recorded as missing/skipped and do not terminate the rest of the batch. Replace rechecks source existence before deleting the existing destination, and Move removes a source only after verified completion.

Local partial files remain available across backend restarts. Remote continuation after restart requires reconnecting the remote profile because credentials remain RAM-only.


## 0.7.0 — endpoint hot-unplug and waiting transfers

Commander now treats Copy/Move as a backend-owned transfer manager workflow. A local volume disconnect or prolonged SSH/SFTP outage transitions the job from `running` to `waiting_endpoint` rather than immediately failing.

Local Windows volumes are identity-bound using the Volume GUID with a serial fallback, so a different device that reuses the same drive letter is not silently accepted. Once the original endpoint returns, DiskShell re-reads the partial target size and resumes automatically. The same resilience wraps mkdir, size verification, rename, and Move source cleanup.

Drive inventory is periodically refreshed; an offline root is shown as OFFLINE and temporary Windows storage-enumeration failures no longer need to crash the Disks page.

This state remains in the running backend process. Backend-restart auto-recovery is intentionally deferred to a persistent transfer journal; SSH credentials remain RAM-only.


## Quiet console and event journal 0.7.5

Routine HTTP access logging is disabled. UI polling and successful 200/304 traffic no longer floods the elevated shell. The console is reserved for WARNING/ERROR output. The rotating event journal is `data/logs/diskshell.log`, capped at 5 MiB with up to five backups. Admin launchers print the journal path at startup.

See [LOGGING.md](LOGGING.md).


## StreamCopy River Keeper 0.7.5

Unfinished local StreamCopy jobs are persisted in SQLite `data/diskshell.db`. After backend restart the recovery manager claims the job after the previous lease expires. Remaining `.dspart-<job>` partial files are part of recovery state and should not be manually deleted while a job is unfinished.
