# DiskShell HDD 0.4

[Русская версия](README.ru.md) · English

**DiskShell is a local-first storage workspace for operating a drive correctly and comfortably.** It is not a PowerShell wrapper. Users work with disks, files, storage classes, working-space reserve, placement plans, analytics, previews, archives, an encrypted Vault and Storage Lab. PowerShell is hidden inside the Windows adapter only where Windows does not expose a suitable high-level Python API.

## 0.4 capabilities

- Windows 11 physical disk / partition / volume inventory with system, boot and application-disk protection.
- Fast `os.scandir` filesystem index persisted in SQLite.
- Content classification: photos, video, audio, documents, archives, disk images, code/development, backups, cache, system and more.
- Analytics: categories, top folders/files, extension distribution, size-based duplicate candidates and opt-in SHA-256 exact duplicates.
- Storage Classes and a capacity-aware Placement Planner.
- Same-volume atomic moves with rollback journal; cross-volume copy → verify while keeping the original.
- Two-pane file workspace with browse/copy/move/Trash/hash behind an independent file-write gate.
- Local previews for images, text/code and PDF, plus ffprobe media metadata when installed.
- Read-only ZIP/TAR/7Z/ISO browsing and traversal-safe ZIP/TAR extraction.
- Vault using Argon2id, a random master key, AES-256-GCM, independent recovery key, chunked large-file encryption and HttpOnly unlock cookie.
- Optional local Photos/People pipeline using OpenCV YuNet + SFace ONNX models; embeddings and clusters remain local.
- Partition Magic safety layer for GPT + one NTFS/exFAT partition, allocation-unit choice, disk identity re-check and typed confirmation.
- Storage Lab with Managed Interleave simulation, read-only NTFS extent queries and read-only sequential/random file benchmarks.
- React/Vite UI.
- Python backend only; **no Rust**.

## Independent safety gates

```text
DS_ALLOW_FILE_WRITES=0
DS_ALLOW_VAULT_WRITES=0
DS_ALLOW_DISK_WRITES=0
DS_ALLOW_EXTENT_MOVES=0
```

All are OFF by default. Protected system/boot/application disks remain blocked even when the disk-write gate is enabled.

## Windows quick start

```powershell
git clone https://github.com/musikfed/diskshellhdd.git F:\diskshellhdd
cd F:\diskshellhdd
Copy-Item .env.example .env
uv sync --group dev
uv run ruff check backend tests
uv run pytest -v
cd frontend
npm install
npm run build
cd ..
uv run python -m backend.app
```

Open `http://127.0.0.1:8765/`.

Optional preview providers:

```powershell
uv sync --group dev --extra preview
```

Optional local Photos/People engine:

```powershell
uv sync --group dev --extra vision
```

Then configure local YuNet/SFace model paths in `.env`.

## HDD layout research

DiskShell only claims control over logical filesystem-visible placement (paths and NTFS extents/LCNs). HDD firmware hides platter geometry, angular position, remapping and internal scheduling. Managed Interleave is therefore a logical target-layout policy. Actual extent relocation remains deliberately locked until it is benchmarked on the target HDD/bridge.

See [architecture](docs/ARCHITECTURE.md) and [deployment](docs/DEPLOYMENT.md).
