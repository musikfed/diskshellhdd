# Развёртывание DiskShell 0.4.1 на Windows 11

## Рекомендуемый способ: чистое восстановление из GitHub

GitHub `main` является источником истины. Если локальная папка запуталась или содержит старые файлы, её можно полностью очистить и развернуть заново.

Сначала останови Flask/Node и выйди из каталога:

```powershell
Set-Location F:\
```

### Если нужно сохранить историю сканов / runtime state

Скопируй `data` отдельно:

```powershell
if (Test-Path F:\diskshellhdd\data) {
    Copy-Item F:\diskshellhdd\data F:\diskshellhdd_data_backup -Recurse -Force
}
```

Также отдельно сохрани `.env`, если в нём есть нужные локальные пути/настройки.

### Полностью очистить локальный проект

Удалить старую папку целиком:

```powershell
Remove-Item F:\diskshellhdd -Recurse -Force
```

Затем клонировать чистый `main`:

```powershell
git clone https://github.com/musikfed/diskshellhdd.git F:\diskshellhdd
Set-Location F:\diskshellhdd
Copy-Item .env.example .env
```

Если нужен старый runtime state, вернуть его **до первого запуска backend**:

```powershell
if (Test-Path F:\diskshellhdd_data_backup) {
    Copy-Item F:\diskshellhdd_data_backup\* F:\diskshellhdd\data\ -Recurse -Force
}
```

SQLite migration выполняется автоматически. Версия 0.4.1 специально проверяет миграцию старой 0.2-схемы до создания новых индексов.

## Установка Python

```powershell
uv sync --group dev
uv run ruff check backend tests
uv run pytest -v
```

Для Preview PDF/7Z/ISO:

```powershell
uv sync --group dev --extra preview
```

Для локального Photos/People:

```powershell
uv sync --group dev --extra vision
```

## Сборка интерфейса

Из корня проекта:

```powershell
npm run ui:install
npm run build
```

Корневой `package.json` проксирует команды в `frontend`, поэтому `cd frontend` больше не нужен.

## Запуск

```powershell
uv run python -m backend.app
```

Открыть:

`http://127.0.0.1:8765/`

## Обычное обновление без полной очистки

Если локальная папка уже является нормальным clone:

```powershell
Set-Location F:\diskshellhdd
git fetch origin
git reset --hard origin/main
uv sync --group dev
uv run ruff check backend tests
uv run pytest -v
npm run build
```

## Safety gates

Для обследования все gates оставлять выключенными:

```text
DS_ALLOW_FILE_WRITES=0
DS_ALLOW_VAULT_WRITES=0
DS_ALLOW_DISK_WRITES=0
DS_ALLOW_EXTENT_MOVES=0
```

`DS_ALLOW_FILE_WRITES=1` нужен только для намеренных file operations / placement execution.

`DS_ALLOW_VAULT_WRITES=1` — только для create/import/export Vault.

`DS_ALLOW_DISK_WRITES=1` — только перед намеренной разметкой конкретного **не protected** диска.

`DS_ALLOW_EXTENT_MOVES=0` пока оставлять выключенным.

System / boot / application disk защищаются backend независимо от UI.

До появления полноценной remote-auth схемы оставлять:

```text
DS_HOST=127.0.0.1
```
