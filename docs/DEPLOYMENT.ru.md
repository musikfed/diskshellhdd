# Развёртывание DiskShell 0.6.3

DiskShell 0.6.3 развивает первую рабочую admin baseline; GitHub `main` считается источником истины. GitHub `main` считается источником истины.

## Важно про права администратора

Для обычного просмотра файлов часть функций может работать без повышения прав, но **DiskShell как storage-admin приложение рекомендуется запускать backend из elevated shell**, если используются physical disks, Surface Diagnostics, Recovery raw probes, Initialize/Partition/Format или NTFS extent diagnostics.

Backend по умолчанию слушает только `127.0.0.1:8765`. Не меняй `DS_HOST` на `0.0.0.0` для elevated/root процесса, пока не включена полноценная удалённая аутентификация.

`DS_DEBUG=0` — рекомендуемый режим. При нём `python -m backend.app` использует Waitress. Flask debugger предназначен только для локальной разработки.

## Windows 11 — установка / обновление

Установку зависимостей и frontend build можно выполнять в обычном PowerShell:

```powershell
Set-Location "F:\diskshellhdd"

git fetch origin
git reset --hard origin/main

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
}

uv sync --group dev
uv run ruff check backend tests
uv run pytest -v

npm run ui:install
npm run build
```

### ОБЯЗАТЕЛЬНЫЙ admin CLI запуск backend

Закрой старый backend. Затем открой **Windows PowerShell / Windows Terminal → Запуск от имени администратора**.

Можно открыть elevated PowerShell командой:

```powershell
Start-Process powershell -Verb RunAs
```

В новом окне с правами Administrator:

```powershell
Set-Location "F:\diskshellhdd"

uv run python -m backend.app
```

Открыть UI:

```text
http://127.0.0.1:8765/
```

В нормальном admin runtime при `DS_DEBUG=0` backend работает через Waitress.

## Linux — bash

Linux может запускать Web UI, SQLite index, Analytics, Commander, SFTP/FTP и другие переносимые части. Windows Storage cmdlets, Windows physical-drive paths и NTFS/fsutil-specific функции остаются Windows-specific и на Linux могут быть недоступны.

Зависимости и frontend собирай **обычным пользователем**:

```bash
cd /path/to/diskshellhdd

git fetch origin
git reset --hard origin/main

test -f .env || cp .env.example .env

uv sync --group dev
uv run ruff check backend tests
uv run pytest -v

npm run ui:install
npm run build
```

### Admin/root CLI запуск backend

Не запускай `sudo uv sync` или `sudo npm`. Повышай права только у backend-процесса:

```bash
cd /path/to/diskshellhdd
sudo -E "$(pwd)/.venv/bin/python" -m backend.app
```

UI:

```text
http://127.0.0.1:8765/
```

Если root создал файлы в `data/`, учитывай их ownership при последующих запусках обычным пользователем.

## Safety gates 0.6.0

Рекомендуемый `.env`:

```text
DS_HOST=127.0.0.1
DS_DEBUG=0

DS_ALLOW_FILE_WRITES=0
DS_ALLOW_VAULT_WRITES=0
DS_ALLOW_DISK_WRITES=0
DS_ALLOW_EXTENT_MOVES=0
```

- `DS_ALLOW_FILE_WRITES=0`: global override выключен. В Files/Storage Brain есть RAM-тумблер `FILE WRITE LOCKED ⇄ ENABLED`; он действует до ручного выключения или restart backend.
- `DS_ALLOW_DISK_WRITES=0`: global disk override выключен. Для конкретного non-protected physical disk WRITE включается отдельным identity-bound тумблером.
- System / Boot / Application disks остаются backend-protected.
- `DS_ALLOW_EXTENT_MOVES=0`: реальное принудительное перемещение NTFS extents отключено.

## Первый рабочий цикл

1. **Диски** — проверь identity диска, topology, filesystem и Health.
2. **Diagnostics** — Quick surface scan выбранного physical disk.
3. **Обследование** — выбери локальный том и создай Quick Index.
4. **Analytics** — проверь размеры/категории.
5. **Storage Brain** — выбери HDD volume/root, Source scope и построй plan.
6. Plan создаётся **без выбранных items**. Поставь галочки только на нужные файлы или используй фильтр + «Выбрать все в фильтре».
7. Включи `FILE WRITE ENABLED`.
8. Выбери integrity mode: Size или SHA-256.
9. Примени выбранный batch.
10. После publish DiskShell проверяет фактические **NTFS logical extents** и показывает `layout OK / drift / unavailable`.

## Что означает проверка “нарезки”

Текущая 0.6.0 **не принуждает NTFS писать файл шахматными macro-bands**. Она:

- рассчитывает lane + target band policy;
- переносит выбранные данные;
- проверяет целостность;
- читает фактические NTFS extents через Windows;
- сравнивает actual extent count с ожидаемым macro-band профилем.

Это проверка логического NTFS layout. HDD firmware не открывает DiskShell точное физическое расположение по platter/head/angular position.

Принудительный Managed Interleave writer / rebalancer остаётся следующим experimental этапом и не включается, пока `DS_ALLOW_EXTENT_MOVES=0`.

## Данные и миграции

SQLite находится в `data/diskshell.db` по умолчанию. Миграции выполняются автоматически при запуске.

Если база и история важны, перед жёстким reset репозитория сделай копию `data/`.

См. также [SAFETY.ru.md](SAFETY.ru.md) и [ARCHITECTURE.ru.md](ARCHITECTURE.ru.md).


### Commander 0.6.3

После обновления frontend поддерживает групповое выделение `Ctrl+Click`, `Shift+Click`, `Ctrl+A`, Select all / Clear. Copy/Move выполняются одним batch job с общим прогрессом. Rename/View/Extract намеренно остаются single-item операциями.
