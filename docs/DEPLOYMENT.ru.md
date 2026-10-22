# Развёртывание DiskShell 0.4 на Windows 11

## Чистая установка

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

Открыть `http://127.0.0.1:8765/`.

## Обновление существующей папки с GitHub

Останови Flask. Сначала сохрани runtime state:

```powershell
Copy-Item F:\diskshellhdd\data F:\diskshellhdd_data_backup -Recurse
```

Если локальная папка уже является clone этого repo:

```powershell
cd F:\diskshellhdd
git fetch origin
git reset --hard origin/main
uv sync --group dev
cd frontend
npm install
npm run build
cd ..
uv run pytest -v
```

Если Git ещё не был нормально привязан, безопаснее переименовать старую папку и сделать чистый clone, затем вернуть `data\diskshell.db` при необходимости. SQLite migration выполняется автоматически.

## Extras

Preview: `uv sync --group dev --extra preview`.

People: `uv sync --group dev --extra vision`, затем укажи `DS_FACE_DETECTOR_MODEL` и `DS_FACE_RECOGNIZER_MODEL`.

## Gate policy

Для обычного обследования все `DS_ALLOW_*` оставлять `0`. `DS_ALLOW_FILE_WRITES=1` нужен только для применения placement plan/copy/move/Trash/extract. `DS_ALLOW_VAULT_WRITES=1` — для create/import/export Vault. `DS_ALLOW_DISK_WRITES=1` — только перед намеренной разметкой конкретного НЕ protected disk. `DS_ALLOW_EXTENT_MOVES` пока оставлять `0`.

При remote/LAN/WireGuard доступе до добавления полноценной auth-схемы не менять `DS_HOST=127.0.0.1`.
