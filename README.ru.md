# DiskShell HDD 0.6.0

Русский · [English](README.md)

**DiskShell — локальный Admin Storage Workbench для Windows 11.** Это не оболочка над PowerShell: пользователь работает с физическими дисками, разделами, томами, файлами, Storage Classes, placement plans, аналитикой, Recovery, Security, Vault и Storage Lab. PowerShell спрятан только внутри Windows storage adapter.

## Первая рабочая baseline 0.6.0

- React/Vite интерфейс переработан под системного администратора / storage engineer.
- System / Boot / Application disk всегда backend-protected.
- `DS_ALLOW_DISK_WRITES=0` оставляет глобальный override выключенным, но позволяет вручную включить запись **только для выбранного непротектед physical disk** из UI.
- Per-disk write toggle привязан к Number + UniqueId/Serial + Size, не требует typed-confirmation и остаётся включённым до ручного выключения или перезапуска backend.
- Partition/Volume Manager: initialize GPT/MBR, создать partition в unallocated space, форматировать NTFS/exFAT, выбрать cluster size, назначить drive letter.
- Whole-disk workflow по-прежнему умеет Clear → GPT → one partition → format, но только после unlock и destructive confirmation.
- Quick Index имеет настоящий Stop/Cancel.
- Двухпанельные Files Copy/Move выполняются background-job с Stop; незавершённый target очищается, исходник сохраняется.
- Placement Plan сохраняется в SQLite и автоматически восстанавливается после refresh.
- Placement Executor запускается background-job, имеет Stop; cross-volume copy идёт chunks и удаляет partial-файл при отмене.
- Recovery / Forensics: persistent topology snapshots и read-only raw signature probe MBR/GPT/NTFS/exFAT/FAT32/BitLocker.
- Security: локальный scan через Microsoft Defender или ClamAV, без remediation, с Stop и историей результатов.
- Analytics, Commander Files, Photos/People, Vault и Storage Lab остаются частью приложения.
- Python backend only; Rust не используется.

## Для кого

Программа предназначена для системных администраторов и инженеров, которые понимают, что такое physical disk, GPT/MBR, partition, volume, filesystem и drive letter. Destructive operations могут необратимо уничтожить данные.

Подробно: [Безопасность и ответственность оператора](docs/SAFETY.ru.md).

## Safety model

```text
DS_ALLOW_FILE_WRITES=0
DS_ALLOW_VAULT_WRITES=0
DS_ALLOW_DISK_WRITES=0   # global override OFF; per-disk WRITE toggle работает
DS_ALLOW_EXTENT_MOVES=0
```

Для обычной админской работы `DS_ALLOW_DISK_WRITES` можно оставить `0` и включать WRITE только тумблером выбранного диска.

## Быстрый запуск Windows 11

Синхронизацию/сборку можно выполнить обычным пользователем:

```powershell
Set-Location "F:\diskshellhdd"
git fetch origin
git reset --hard origin/main
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
uv sync --group dev
uv run ruff check backend tests
uv run pytest -v
npm run ui:install
npm run build
```

**Backend для storage-admin функций запускай из PowerShell / Windows Terminal «От имени администратора»:**

```powershell
Set-Location "F:\diskshellhdd"
uv run python -m backend.app
```

При `DS_DEBUG=0` используется Waitress. Открыть: `http://127.0.0.1:8765/`.

Linux/root запуск и подробная инструкция: [docs/DEPLOYMENT.ru.md](docs/DEPLOYMENT.ru.md).

Локальный Photos/People engine: `uv sync --group dev --extra vision` и задать пути YuNet/SFace ONNX в `.env`.

## WD Purple / основной storage

Для 4 TB storage HDD разумная базовая схема: GPT + один большой NTFS том. 4 KiB — универсальный вариант; 16 KiB — хороший вариант для смешанного хранилища с преобладанием крупных фото/video/archive/ISO; 64 KiB — специализированный вариант для почти исключительно крупных sequential-файлов. DiskShell не притворяется, что cluster size можно поменять без переформатирования.

Подробнее: [архитектура](docs/ARCHITECTURE.ru.md) · [развёртывание](docs/DEPLOYMENT.ru.md) · [безопасность](docs/SAFETY.ru.md).

## Storage wizard 0.6.0

DiskShell различает три операции:

1. **Initialize GPT** — создаёт только таблицу разделов. Том и файловая система ещё не создаются.
2. **+ Раздел / том** — создаёт partition в уже существующем unallocated space. Можно задать размер GiB или оставить поле пустым для максимального extent.
3. **Очистить + первый том** — destructive workflow для выбранного physical disk. После очистки создаёт GPT и первый том заданного размера; если размер меньше диска, остаток остаётся **Unallocated** для следующих томов.

Windows Storage `Format-Volume` adapter предлагает: **NTFS, exFAT, ReFS, FAT32, FAT**. UDF сюда не включён, потому что PowerShell `Format-Volume` его не принимает; это отдельный backend через `format.exe`, если он когда-нибудь понадобится.

Cluster sizes показываются по выбранной FS. Backend дополнительно проверяет cluster-count limits до destructive execution. Для основного WD Purple остаётся рекомендуемый профиль **NTFS 16 KiB**.

### Progress

- Files Copy/Move: реальный процент по байтам после этапа измерения source.
- Placement Executor: реальный процент по объёму плана.
- Quick Index: indeterminate, потому что заранее неизвестно число файлов.
- Defender/ClamAV: indeterminate, потому что движок не отдаёт надёжный общий объём.
- Initialize/partition/format: activity indicator без фиктивного процента; принудительный Stop во время изменения partition table намеренно не предлагается.

## Adaptive Macro Interleave 0.6.0

Storage Lab больше не моделирует одинаковые фиксированные куски. Вместо этого используется bounded macro-interleave:

- Video/Audio получают длинные sequential bands;
- Photo/RAW — средние bands;
- Documents/Code/Design — более короткие interactive bands;
- Archive/Backup/ISO — самые длинные cold bands;
- Cache/Temporary ограничены, чтобы churn не захватывал layout.

Размер bands адаптируется к измеренным sequential MiB/s и seek latency. Цель — чтобы стоимость seek составляла не более заданной доли времени обработки полосы.

Большой файл делится на примерно равные extents без маленького хвоста. Маленький файл не режется. Несколько маленьких файлов одного класса могут заполнять одну macro-band.

Симулятор показывает tiny/oversized split extents, max extents per file и итоговый quality. Реальное NTFS extent relocation всё ещё выключено и остаётся отдельным experimental этапом.

## RAW disk workflow 0.6.0

Для RAW-диска DiskShell больше не предлагает основной shortcut «GPT + первый том». Безопасный путь разделён на стадии:

1. включить WRITE тумблер только для выбранного physical disk;
2. Initialize GPT;
3. перечитать topology;
4. создать раздел/том из unallocated space;
5. отформатировать выбранной FS/cluster policy.

UI показывает stepper и фиксированный activity-status поверх окна. Внутри Initialize-Disk / New-Partition / Format-Volume честного процента Windows не предоставляет, поэтому DiskShell показывает этап, а не выдуманный процент.

Destructive Windows Storage operations требуют запуска backend от имени Administrator. Страница Disks теперь показывает это явно и блокирует write-кнопки, если процесс не elevated.

## Commander 0.6.0

`Files` теперь является единым двухпанельным Commander. Отдельная вкладка Preview / Archives удалена.

- каждая панель: Local, SFTP/SSH, FTP или FTPS;
- локальные панели имеют выбор диска/root и текущего пути;
- remote credentials живут только в RAM backend и не записываются в SQLite/localStorage;
- F2 Rename, F3 View, F5 Copy, F6 Move, F7 MkDir, F8 Trash/Delete, F9 Archive, Esc Stop;
- локальный delete использует Recycle Bin; remote delete является явным необратимым удалением;
- Preview и Archive/ISO browser встроены в Commander;
- ZIP/TAR/TAR.GZ/7Z создаются из Commander; ZIP/TAR/7Z безопасно распаковываются; RAR/CAB/WIM используют 7-Zip CLI, если он установлен;
- SFTP работает через Paramiko; FTP/FTPS — через Python ftplib;
- transfer jobs поддерживают Local↔Local, Local↔Remote и Remote↔Remote с size verification и cooperative Stop.

### Direct и Smart transfer

`Smart folders` выключен по умолчанию. Direct-режим переносит ровно в открытую папку второй панели. Smart folders меняет только папку назначения по Storage Class; он **не** обещает принудительную NTFS-нарезку.

Storage Brain 0.6.0 после managed transfer уже выполняет read-only проверку фактических NTFS extents и показывает `layout OK / drift / unavailable` относительно lane/band policy. Реальное принудительное перемещение extents остаётся выключенным при `DS_ALLOW_EXTENT_MOVES=0`.


## Per-disk WRITE toggle 0.6.0

Разблокировка диска больше не использует фразу вида `UNLOCK DISK ...` и не имеет 15-минутного TTL.

Для непротектед physical disk на странице «Диски» используется обычный тумблер:

```text
WRITE LOCKED  ⇄  WRITE ENABLED
```

Состояние хранится только в памяти backend и действует до ручного выключения или restart backend. Разрешение жёстко связано с Number + UniqueId + Serial + Size: если identity на этом номере изменилась, write enable автоматически сбрасывается.

System / Boot / Application disk остаются backend-protected и тумблером не открываются. Typed confirmation у конкретных destructive действий (Initialize / Format / Create partition) остаётся отдельным уровнем подтверждения операции.


## Что зафиксировано в 0.6.0

- выбор локального тома добавлен в Examine, Security, Storage Brain, Storage Lab и обе панели Commander;
- Commander показывает размер папки из активного SQLite scan вместо пустого `<DIR>`, если папка индексирована;
- направления Copy/Move видны явно: LEFT → RIGHT и RIGHT → LEFT;
- FILE WRITE — отдельный RAM-тумблер, не требующий редактировать `.env`;
- Placement Plan отдаётся страницами и не пытается отправить браузеру сотни тысяч строк одним JSON;
- новый plan создаётся **без выбранных items**: оператор отмечает галочками только нужный batch;
- Select all/none работает по текущему фильтру;
- cross-volume managed copy проверяется по Size или SHA-256;
- после publish выполняется read-only проверка реальных NTFS logical extents относительно target macro-band;
- принудительный Managed Interleave writer/rebalancer в 0.6.0 ещё не включён.

**Admin CLI:** для Windows physical disk / Surface Diagnostics / Recovery raw / NTFS extent функций backend запускается из elevated PowerShell. На Linux — из root shell, но Windows Storage/NTFS-specific функции там недоступны. Полные команды: [DEPLOYMENT.ru.md](docs/DEPLOYMENT.ru.md).
