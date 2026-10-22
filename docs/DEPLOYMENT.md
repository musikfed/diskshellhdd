# Deployment Guide

This guide describes deployment of DiskShell baseline 0.2 on Windows 11.

## 1. Prerequisites

Install Windows 11, Git, uv, and Python 3.12.

Verify:

    git --version
    uv --version

## 2. Clone

    git clone https://github.com/musikfed/diskshellhdd.git
    cd diskshellhdd

## 3. Python environment

DiskShell baseline 0.2 targets Python 3.12.

    uv sync
    uv run python --version

Expected: Python 3.12.x

## 4. Environment configuration

    Copy-Item .env.example .env

Recommended development values:

    DS_HOST=127.0.0.1
    DS_PORT=8765
    DS_DEBUG=1
    DS_DATA_DIR=./data
    DS_ALLOW_DESTRUCTIVE=0

Do not enable destructive operations in baseline 0.2.

## 5. Static checks

    uv run ruff check backend tests

For safe automatic lint fixes during development:

    uv run ruff check backend tests --fix

Then run the check again.

## 6. Tests

    uv run pytest -v

## 7. Run the backend

    uv run python -m backend.app

Local address: http://127.0.0.1:8765

Useful endpoints:

- GET /
- GET /api/health
- GET /api/disks
- POST /api/scans
- GET /api/scans/<job_id>
- GET /api/index/scans/<scan_id>/top
- GET /api/index/scans/<scan_id>/directory

## 8. Test the CLI scanner

Use a small directory first:

    uv run python -m backend.scanner.quick_scan F:\\diskshellhdd\\backend

The scanned directory is read-only from DiskShell's point of view. Index data is written only to DiskShell's own SQLite database.

## 9. Test background scanning

Keep Flask running in one PowerShell window. In another window:

    $body = @{ path = "F:\\diskshellhdd\\backend" } | ConvertTo-Json
    $result = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/api/scans" -ContentType "application/json" -Body $body
    $job = $result.id
    Invoke-RestMethod "http://127.0.0.1:8765/api/scans/$job" | Format-List

A successful job should report status = completed, non-zero file/directory counters, and a scan_id.

## 10. Disk safety

Baseline 0.2 must not call Clear-Disk, Initialize-Disk, Format-Volume, destructive diskpart commands, raw disk writes, or extent relocation.

All physical disks must remain write_policy = blocked.

## 11. Development server note

Flask's built-in server is for local development only. Future LAN/WireGuard deployment should use a production WSGI server such as Waitress, authentication, and firewall restrictions. Until then, keep the service on 127.0.0.1.

## 12. Data location

Default SQLite database:

    data\\diskshell.db

For future NAS/HDD deployment, keep application DB, cache, thumbnails, and temporary files on SSD/NVMe when possible.

## 13. Upgrade workflow

Before major changes:

    git status
    git add .
    git commit -m "checkpoint: working baseline"

Implement one milestone at a time and keep read-side and write-side features separate.
