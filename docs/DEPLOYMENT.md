# Deploying DiskShell 0.5.1.1 on Windows 11

## Clean installation / recovery

GitHub `main` is the source of truth.

```powershell
Set-Location F:\
Remove-Item F:\diskshellhdd -Recurse -Force -ErrorAction SilentlyContinue
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

Back up and restore `data` before the first backend start if previous scan/Vault runtime state must be retained. SQLite migrations are automatic.

## Disk writes in 0.5

Recommended default:

```text
DS_ALLOW_DISK_WRITES=0
```

This disables the global override but still allows the administrator to unlock one selected non-protected physical disk from the Disks page after identity review and exact typed confirmation. Runtime unlock expires after 15 minutes and can be manually locked earlier.

System / Boot / Application disks cannot be unlocked.

`DS_ALLOW_DISK_WRITES=1` is a global override intended for controlled lab/automation scenarios.

## Partition / Volume Manager

0.5 supports RAW disk initialization, partition creation in unallocated space, NTFS/exFAT formatting, allocation-unit selection, drive-letter assignment, and the explicitly destructive whole-disk single-volume workflow.

## Stop buttons

Quick Index, Placement Executor, two-pane Files Copy/Move, and Security Scan support cooperative cancellation.

## Recovery

Recovery is currently read-only: SQLite topology snapshots plus raw MBR/GPT/filesystem-signature probing. It is groundwork for future recovery workflows, not an automatic data-recovery promise.

## Security

DiskShell uses local Microsoft Defender or ClamAV and runs scans without remediation.

Keep `DS_HOST=127.0.0.1` until remote authentication is implemented.

See [SAFETY.md](SAFETY.md).
