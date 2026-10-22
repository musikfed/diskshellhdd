# Deployment on Windows 11

## Install

```powershell
git clone https://github.com/musikfed/diskshellhdd.git F:\diskshellhdd
cd F:\diskshellhdd
Copy-Item .env.example .env
uv sync --group dev
uv run ruff check backend tests
uv run pytest -v
```

Optional preview support:

```powershell
uv sync --group dev --extra preview
```

Optional local vision runtime:

```powershell
uv sync --group dev --extra vision
```

Face models are not downloaded automatically. Configure local YuNet/SFace model paths in `.env`.

## Build UI

```powershell
cd F:\diskshellhdd\frontend
npm install
npm run build
cd ..
```

## Run

```powershell
uv run python -m backend.app
```

Open `http://127.0.0.1:8765/`.

## Safety

Keep all write gates at `0` during examination. Enable only the one domain you explicitly want. Never enable disk writes before verifying `/api/disks` marks all system/boot/application disks as protected.

## Updating an existing local folder from GitHub

Commit or back up local changes first, then:

```powershell
cd F:\diskshellhdd
git fetch origin
git switch main
git reset --hard origin/main
uv sync --group dev
cd frontend
npm install
npm run build
cd ..
uv run ruff check backend tests
uv run pytest -v
```

`git reset --hard` intentionally replaces tracked local files with GitHub. Runtime data under ignored `data/` paths is not part of the repository, but make a backup before major updates.
