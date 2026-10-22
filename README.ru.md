# DiskShell HDD 0.5

Русский · [English](README.md)

**DiskShell — локальный Admin Storage Workbench для Windows 11.** Это не оболочка над PowerShell: пользователь работает с физическими дисками, разделами, томами, файлами, Storage Classes, placement plans, аналитикой, Recovery, Security, Vault и Storage Lab. PowerShell спрятан только внутри Windows storage adapter.

## Главное в 0.5

- React/Vite интерфейс переработан под системного администратора / storage engineer.
- System / Boot / Application disk всегда backend-protected.
- `DS_ALLOW_DISK_WRITES=0` оставляет глобальный override выключенным, но позволяет временно разблокировать **один выбранный непротектед physical disk** из UI.
- Per-disk unlock привязан к Number + UniqueId/Serial + Size, требует typed-confirmation и истекает через 15 минут.
- Partition/Volume Manager: initialize GPT/MBR, создать partition в unallocated space, форматировать NTFS/exFAT, выбрать cluster size, назначить drive letter.
- Whole-disk workflow по-прежнему умеет Clear → GPT → one partition → format, но только после unlock и destructive confirmation.
- Quick Index имеет настоящий Stop/Cancel.
- Placement Plan сохраняется в SQLite и автоматически восстанавливается после refresh.
- Placement Executor запускается background-job, имеет Stop; cross-volume copy идёт chunks и удаляет partial-файл при отмене.
- Recovery / Forensics: persistent topology snapshots и read-only raw signature probe MBR/GPT/NTFS/exFAT/FAT32/BitLocker.
- Security: локальный scan через Microsoft Defender или ClamAV, без remediation, с Stop и историей результатов.
- Analytics, Files, Preview/Archives, Photos/People, Vault и Storage Lab остаются частью приложения.
- Python backend only; Rust не используется.

## Для кого

Программа предназначена для системных администраторов и инженеров, которые понимают, что такое physical disk, GPT/MBR, partition, volume, filesystem и drive letter. Destructive operations могут необратимо уничтожить данные.

Подробно: [Безопасность и ответственность оператора](docs/SAFETY.ru.md).

## Safety model

```text
DS_ALLOW_FILE_WRITES=0
DS_ALLOW_VAULT_WRITES=0
DS_ALLOW_DISK_WRITES=0   # global override OFF; per-disk UI unlock работает
DS_ALLOW_EXTENT_MOVES=0
```

Для обычной админской работы с storage-диском `DS_ALLOW_DISK_WRITES` можно оставить `0` и разблокировать только выбранный диск из UI.

## Быстрый запуск Windows 11

```powershell
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

Открыть: `http://127.0.0.1:8765/`.

Дополнительные preview providers: `uv sync --group dev --extra preview`.

Локальный Photos/People engine: `uv sync --group dev --extra vision` и задать пути YuNet/SFace ONNX в `.env`.

## WD Purple / основной storage

Для 4 TB storage HDD разумная базовая схема: GPT + один большой NTFS том. 4 KiB — универсальный вариант; 16 KiB — хороший вариант для смешанного хранилища с преобладанием крупных фото/video/archive/ISO; 64 KiB — специализированный вариант для почти исключительно крупных sequential-файлов. DiskShell не притворяется, что cluster size можно поменять без переформатирования.

Подробнее: [архитектура](docs/ARCHITECTURE.ru.md) · [развёртывание](docs/DEPLOYMENT.ru.md) · [безопасность](docs/SAFETY.ru.md).
