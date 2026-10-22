# DiskShell HDD

[Русская версия](README.ru.md) · English

DiskShell is a local-first storage inspection and indexing project for Windows. The current baseline focuses on safe, read-only discovery of physical disks and volumes, fast filesystem indexing, SQLite-backed scan history, and a small Flask API.

## Current baseline: 0.2

Implemented:

- Windows 11 physical disk / partition / volume inventory.
- Read-only PowerShell Storage queries.
- Automatic protection labels for system, boot, and application disks.
- SQLite index stored locally by DiskShell.
- Quick filesystem indexer based on os.scandir.
- Bottom-up directory size aggregation.
- Background scan jobs with live counters.
- Flask API bound to localhost by default.
- Ruff and pytest development checks.

Planned later:

- Analytics dashboard and file classification.
- React frontend.
- Preview providers for images, documents, archives, ISO and media.
- Local photo/person recognition.
- File manager with quarantine-first write operations.
- Vault.
- Partition Magic with a separate privileged safety layer.
- Experimental Storage Lab / managed layout research.

## Safety model

Baseline 0.2 is intentionally non-destructive.

DiskShell does not initialize, format, clear, repartition, delete, or relocate disk extents in this milestone. Every physical disk returned by the disk inventory API has write_policy = blocked.

Filesystem scanning reads metadata from the selected directory and writes index data only to DiskShell's own local SQLite database.

## Requirements

- Windows 11
- Python 3.12
- uv
- PowerShell with the Windows Storage module

## Quick start

    git clone https://github.com/musikfed/diskshellhdd.git
    cd diskshellhdd
    Copy-Item .env.example .env
    uv sync
    uv run ruff check backend tests
    uv run pytest -v
    uv run python -m backend.app

Open:

- http://127.0.0.1:8765/
- http://127.0.0.1:8765/api/health
- http://127.0.0.1:8765/api/disks

Read the full English deployment guide: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

Полная инструкция на русском: [docs/DEPLOYMENT.ru.md](docs/DEPLOYMENT.ru.md)

## Development status

The working baseline has been validated with a local scan job completing successfully with zero scanner errors. The project is now ready for the next milestone: file classification and Analytics API.

## License

No license has been selected yet.
