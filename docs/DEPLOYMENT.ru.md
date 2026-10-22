# Развёртывание на Windows 11

## Установка

```powershell
git clone https://github.com/musikfed/diskshellhdd.git F:\diskshellhdd
cd F:\diskshellhdd
Copy-Item .env.example .env
uv sync --group dev
uv run ruff check backend tests
uv run pytest -v
```

Опциональные previews PDF/7Z/ISO:

```powershell
uv sync --group dev --extra preview
```

Опциональный локальный vision runtime:

```powershell
uv sync --group dev --extra vision
```

Face-модели автоматически не скачиваются. Пути к локальным YuNet/SFace моделям задаются в `.env`.

## Сборка интерфейса

```powershell
cd F:\diskshellhdd\frontend
npm install
npm run build
cd ..
```

## Запуск

```powershell
uv run python -m backend.app
```

Открыть `http://127.0.0.1:8765/`.

## Безопасность

Во время обследования все write gates оставлять `0`. Включать только конкретную область, которой собираешься пользоваться. Disk writes не включать, пока `/api/disks` не показывает system/boot/application disks как protected.

## Обновление существующей папки F:\\diskshellhdd из GitHub

Сначала сохранить нужные локальные изменения или сделать backup. Затем:

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

`git reset --hard` специально заменяет tracked-файлы локальной папки версией из GitHub. Runtime-данные из ignored `data/` не входят в репозиторий, но перед крупным обновлением backup всё равно рекомендуется.
