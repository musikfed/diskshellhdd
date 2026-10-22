# DiskShell HDD 0.3

[Русский](README.ru.md) · English

DiskShell is a **local-first storage workspace and storage brain**, not a PowerShell frontend. It is designed to help a person inspect disks, understand what is stored, keep working free-space reserve, classify information, plan where data should live, browse and preview files, work with archives and private Vault data, and experiment with logical HDD layout policies.

PowerShell exists only inside the Windows storage adapter where Windows has no better high-level Python API for a specific operation. The product model is storage-oriented: **content → policy → placement → safe execution → filesystem adapter**.

## What is included

- Physical disk / partition / volume discovery on Windows 11.
- Quick read-only filesystem indexer with SQLite history.
- File classification: photos, video, audio, documents, archives, ISO/images, code, development dependencies, cache, system data, and other.
- Analytics: categories, largest directories, largest files, extension distribution.
- Storage Classes and Placement Planner.
- Capacity policy with soft/hard fill limits and working reserve.
- File workspace backend: browse, hash, copy, move, Trash (write gate locked by default).
- Preview metadata for images, text/code and optional PDF.
- Read-only ZIP/TAR, optional 7Z and ISO browsing.
- AES-GCM encrypted Vault with Argon2id key derivation, random master key, recovery key and in-memory unlock sessions.
- Partition Magic safety layer with protected-disk checks and typed confirmation (disk write gate locked by default).
- Storage Lab managed-interleave simulator and read-only NTFS extent query.
- Optional local face detector pipeline using OpenCV YuNet model paths; no cloud.
- React/Vite UI with Dashboard, Disks, Examine, Analytics, Storage Brain, Files, Vault and Storage Lab.
- No Rust.

## Safety gates

All risky write domains are independent and **OFF by default**:

```text
DS_ALLOW_FILE_WRITES=0
DS_ALLOW_VAULT_WRITES=0
DS_ALLOW_DISK_WRITES=0
DS_ALLOW_EXTENT_MOVES=0
```

System, boot and the disk containing DiskShell itself are marked protected. Partition formatting requires a separate disk-write gate plus exact typed confirmation.

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

For development UI: run backend, then `cd frontend; npm run dev` and open `http://127.0.0.1:5173/`.

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
