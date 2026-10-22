# DiskShell HDD 0.3

Русский · [English](README.md)

DiskShell — это **локальное рабочее пространство для хранения и Storage Brain**, а не оболочка над PowerShell. Цель программы — удобно и правильно эксплуатировать диск: обследовать накопители, понимать состав данных, держать рабочий резерв, классифицировать информацию, предлагать правильное место хранения, работать с файлами и архивами, защищать приватные данные и экспериментировать с логическим размещением на HDD.

PowerShell остаётся только глубоко внутри Windows-adapter там, где конкретная операция Windows требует системного API. Пользовательская модель DiskShell другая: **содержимое → политика → план размещения → безопасное выполнение → файловая система**.

## Что уже входит

- обнаружение физических дисков, разделов и томов Windows 11;
- Quick Indexer с read-only обходом и историей в SQLite;
- классификация: фото, видео, аудио, документы, архивы, ISO/образы, код, development dependencies, cache, system, other;
- Analytics: категории, самые тяжёлые папки/файлы, распределение расширений;
- Storage Classes и Placement Planner;
- контроль заполнения, soft/hard limits и рабочий резерв;
- файловый workspace: просмотр, hash, copy/move/Trash через отдельный write gate;
- preview изображений, текста/кода и опционально PDF;
- просмотр ZIP/TAR и опционально 7Z/ISO без распаковки всего контейнера;
- зашифрованный Vault: Argon2id + AES-GCM, случайный master key, recovery key, unlock только в RAM;
- Partition Magic safety layer с защитой system/boot/application disk и текстовым подтверждением;
- Storage Lab: симулятор Managed Interleave и read-only запрос NTFS extents;
- опциональный локальный face detector через OpenCV YuNet; облако не используется;
- React/Vite UI: Dashboard, Disks, Examine, Analytics, Storage Brain, Files, Vault, Storage Lab;
- Rust не используется.

## Safety gates

Все потенциально опасные области **выключены по умолчанию независимо друг от друга**:

```text
DS_ALLOW_FILE_WRITES=0
DS_ALLOW_VAULT_WRITES=0
DS_ALLOW_DISK_WRITES=0
DS_ALLOW_EXTENT_MOVES=0
```

System/boot диск и физический диск, на котором находится DiskShell, помечаются protected. Форматирование требует отдельного включения disk-write gate и точной фразы подтверждения.

## Быстрый запуск Windows

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

Открыть: `http://127.0.0.1:8765/`.

Для UI-разработки: backend оставить запущенным, затем `cd frontend; npm run dev` и открыть `http://127.0.0.1:5173/`.

Подробно: [docs/DEPLOYMENT.ru.md](docs/DEPLOYMENT.ru.md) и [docs/ARCHITECTURE.ru.md](docs/ARCHITECTURE.ru.md).
