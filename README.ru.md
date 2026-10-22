# DiskShell HDD 0.4

Русский · [English](README.md)

**DiskShell — локальная программа для удобной и правильной эксплуатации накопителя.** Это не оболочка над PowerShell. Пользователь работает с дисками, файлами, классами хранения, резервом свободного места, планами размещения, аналитикой, previews, архивами, Vault и Storage Lab. PowerShell используется только глубоко внутри Windows-adapter там, где Windows не даёт удобного Python API.

## Что умеет 0.4

- безопасно обнаруживать физические диски, разделы и тома Windows 11;
- автоматически блокировать system / boot / application disk;
- обследовать большие деревья файлов через `os.scandir` и хранить индекс в SQLite;
- классифицировать фото, видео, музыку, документы, архивы, ISO/образы, code/development, backup, cache, system и прочее;
- показывать Analytics: категории, тяжёлые папки/файлы, расширения, кандидаты и точные SHA-256 дубликаты;
- работать со **Storage Classes** (`Media`, `Photos`, `Documents`, `Images`, `Archive`, `Backups`, `Development`, `Temporary`, `Vault` и т.д.);
- строить **Placement Plan** с учётом рабочего резерва и различать same-volume move / cross-volume copy;
- применять plan только после отдельного write gate и точной фразы подтверждения;
- same-volume файлы перемещать атомарно с журналом rollback; cross-volume — copy → verify и оставлять оригинал до ручного решения;
- двухпанельный файловый workspace: browse, copy, move, Trash, hash;
- preview изображений, текста/code, PDF и media metadata (ffprobe при наличии);
- просматривать ZIP/TAR/7Z/ISO без полной распаковки; безопасно извлекать ZIP/TAR с защитой от path traversal;
- **Vault**: Argon2id + случайный master key + AES-256-GCM, recovery key, chunked encryption больших файлов, HttpOnly unlock-cookie;
- **Photos / People**: локальный YuNet + SFace pipeline, embeddings в SQLite, автоматическая группировка людей, `alone / with others`; ONNX-модели задаются локально и не отправляются в облако;
- **Partition Magic**: GPT + один NTFS/exFAT том, выбор cluster size, повторная проверка identity диска и typed confirmation; destructive gate по умолчанию выключен;
- **Storage Lab**: Managed Interleave simulator, read-only NTFS extent query и read-only sequential/random benchmark;
- React/Vite UI со страницами Disks, Examine, Analytics, Storage Brain, Files, Preview/Archives, Photos/People, Vault, Storage Lab;
- Python-only backend, **Rust не используется**.

## Safety gates

По умолчанию `.env.example` содержит:

```text
DS_ALLOW_FILE_WRITES=0
DS_ALLOW_VAULT_WRITES=0
DS_ALLOW_DISK_WRITES=0
DS_ALLOW_EXTENT_MOVES=0
```

Это четыре независимые границы. Наличие кода форматирования не означает разрешение форматирования. Защищённый system/boot/application disk нельзя форматировать даже при включённом disk-write gate.

Для текущих системных дисков Windows ничего включать не нужно — оставляй все gate'ы `0`.

## Быстрый запуск Windows 11

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

Для Preview 7Z/ISO/PDF:

```powershell
uv sync --group dev --extra preview
```

Для локального Photos/People engine:

```powershell
uv sync --group dev --extra vision
```

и указать локальные ONNX-модели:

```text
DS_FACE_DETECTOR_MODEL=C:\models\face_detection_yunet.onnx
DS_FACE_RECOGNIZER_MODEL=C:\models\face_recognition_sface.onnx
```

## WD Purple / основной storage

Для постоянного 4 TB HDD на Windows-хосте рекомендуемая базовая схема DiskShell: GPT, один большой NTFS, обычно 4 KiB allocation unit для смешанного набора данных, рабочий резерв свободного места и логические Storage Classes внутри одного тома. 64 KiB имеет смысл выбирать только если реальный анализ покажет почти исключительно крупные последовательные файлы.

База SQLite, thumbnails/cache и временные данные приложения по возможности должны жить на SSD/NVMe. `DS_VAULT_ROOT` можно направить на основной storage HDD отдельно.

## Storage Lab и физика HDD

DiskShell управляет тем, что ОС реально позволяет наблюдать и контролировать: файловыми категориями, путями, VCN/LCN/extents и логическим target layout. Точная геометрия пластин, головок, угловая позиция, remapping и внутренний scheduling скрыты firmware HDD. Поэтому функция называется **Managed Interleave / logical placement**, а не «рисование физических секторов».

Перемещение NTFS extents пока намеренно не включено: сначала на конкретном WD Purple + USB/SATA bridge нужно собрать extent map и benchmark baseline. `DS_ALLOW_EXTENT_MOVES=0` остаётся заблокированным.

Подробнее: [архитектура](docs/ARCHITECTURE.ru.md) · [развёртывание](docs/DEPLOYMENT.ru.md).
