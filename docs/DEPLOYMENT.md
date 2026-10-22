# Deploying DiskShell 0.4.1 on Windows 11

## Recommended recovery path: clean redeploy from GitHub

The GitHub `main` branch is the source of truth. If the local tree becomes mixed with old files, it is safe to remove the local project directory completely and clone it again.

Stop Flask/Node and leave the directory:

```powershell
Set-Location F:\
```

Optionally back up runtime state:

```powershell
if (Test-Path F:\diskshellhdd\data) {
    Copy-Item F:\diskshellhdd\data F:\diskshellhdd_data_backup -Recurse -Force
}
```

Back up `.env` separately if it contains local model paths or other settings.

Remove the old project tree:

```powershell
Remove-Item F:\diskshellhdd -Recurse -Force
```

Clone a clean copy:

```powershell
git clone https://github.com/musikfed/diskshellhdd.git F:\diskshellhdd
Set-Location F:\diskshellhdd
Copy-Item .env.example .env
```

If required, restore runtime state before the first backend start:

```powershell
if (Test-Path F:\diskshellhdd_data_backup) {
    Copy-Item F:\diskshellhdd_data_backup\* F:\diskshellhdd\data\ -Recurse -Force
}
```

SQLite migrations run automatically. Version 0.4.1 includes a regression test for upgrading the legacy 0.2 file schema before category indexes are created.

## Python

```powershell
uv sync --group dev
uv run ruff check backend tests
uv run pytest -v
```

Optional preview providers:

```powershell
uv sync --group dev --extra preview
```

Optional local Photos/People:

```powershell
uv sync --group dev --extra vision
```

## Frontend

From the repository root:

```powershell
npm run ui:install
npm run build
```

The root `package.json` proxies these commands into `frontend`.

## Run

```powershell
uv run python -m backend.app
```

Open `http://127.0.0.1:8765/`.

## Safety gates

Keep all write domains disabled for normal inspection:

```text
DS_ALLOW_FILE_WRITES=0
DS_ALLOW_VAULT_WRITES=0
DS_ALLOW_DISK_WRITES=0
DS_ALLOW_EXTENT_MOVES=0
```

Protected system/boot/application disks remain blocked independently of the UI.

Keep `DS_HOST=127.0.0.1` until remote authentication is implemented.
