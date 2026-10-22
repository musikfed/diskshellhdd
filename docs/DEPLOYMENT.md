# Deploying DiskShell 0.6.0

DiskShell 0.6.0 is the first frozen working admin baseline. GitHub `main` is the source of truth.

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

Stop the previous backend. Open **Windows PowerShell / Windows Terminal → Run as Administrator**.

You can open an elevated PowerShell with:

```powershell
Start-Process powershell -Verb RunAs
```

Inside the elevated shell:

```powershell
Set-Location "F:\diskshellhdd"

uv run python -m backend.app
```

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

Do not run `sudo uv sync` or `sudo npm`. Elevate only the backend process:

```bash
cd /path/to/diskshellhdd
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
