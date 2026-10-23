# Развёртывание DiskShell 0.7.1

DiskShell 0.7.1 развивает первую рабочую admin baseline; GitHub `main` считается источником истины.

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

Для physical disk / Surface Diagnostics / Recovery RAW / Initialize / Partition / Format / NTFS extent функций backend должен быть elevated.

#### Вариант A — одна команда из обычного PowerShell или VS Code terminal

Рекомендуемый способ:

```powershell
Set-Location "F:\diskshellhdd"
.\scripts\start-admin.ps1
```

То же через workspace shortcut:

```powershell
npm run backend:admin:win
```

Скрипт сам проверяет token процесса. Если прав Administrator нет, Windows покажет стандартный UAC prompt и запустит **только backend** в elevated PowerShell. Это безопаснее, чем держать весь редактор с повышенными правами.

Можно также запустить двойным кликом / из cmd.exe:

```cmd
scripts\start-admin.cmd
```

#### Вариант B — VS Code task

В VS Code:

```text
Ctrl+Shift+P
→ Tasks: Run Task
→ DiskShell: Backend as Administrator
```

Task вызывает `scripts/start-admin.ps1`; после UAC backend работает elevated. Исходный VS Code может оставаться обычным пользователем.

Если нужен именно **elevated integrated terminal**, есть второй task. То же можно вызвать командой `npm run vscode:admin:win`:

```text
Ctrl+Shift+P
→ Tasks: Run Task
→ DiskShell: Reopen VS Code as Administrator
```

После подтверждения UAC откроется elevated VS Code workspace. Тогда встроенный terminal уже может запускать:

```powershell
uv run python -m backend.app
```

⚠ В этом режиме **все расширения и workspace tasks VS Code тоже получают Administrator privileges**. Используй только для доверенного workspace.

#### Вариант C — вручную через UAC

```powershell
Start-Process powershell -Verb RunAs
```

В открывшемся Administrator PowerShell:

```powershell
Set-Location "F:\diskshellhdd"
uv run python -m backend.app
```

#### Про `runas`

Можно использовать alternate-credentials запуск:

```cmd
runas /user:Администратор "powershell.exe -NoExit -Command \"Set-Location 'F:\diskshellhdd'; uv run python -m backend.app\""
```

На англоязычной Windows имя встроенной учётки обычно `Administrator`.

Но `runas` **не является надёжной заменой UAC elevation**: встроенный Administrator может быть отключён, имя локализовано, а процесс с другими credentials не всегда получает нужный high-integrity token. Для DiskShell предпочтителен `Start-Process ... -Verb RunAs` или готовый `scripts/start-admin.ps1`.

Открыть UI:

```text
http://127.0.0.1:8765/
```

При `DS_DEBUG=0` backend работает через Waitress.

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

Не запускай `sudo uv sync` или `sudo npm`. Повышай права только у backend-процесса.

Готовый launcher:

```bash
cd /path/to/diskshellhdd
bash scripts/start-admin.sh
```

или workspace shortcut:

```bash
npm run backend:admin:linux
```

Эквивалент вручную:

```bash
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

## Первое создание Vault и место хранения

Обычно `DS_VAULT_ROOT` оставляют пустым. На странице **Vault → Создать Vault** выбери логический том и отдельную папку:

```text
Том: W:\\
Папка: DiskShellVault
Итог: W:\\DiskShellVault
```

DiskShell создаст:

```text
W:\\DiskShellVault\\
├── vault.json
├── catalog.bin
└── objects\\
```

Выбранный путь сохраняется в `data/vault-location.json`. Это locator без ключей и паролей; он нужен только для повторного обнаружения Vault после restart backend.

Корень тома `W:\\` использовать как сам Vault нельзя — backend это блокирует. Если требуется фиксированный путь через конфигурацию, задай `DS_VAULT_ROOT=W:\\DiskShellVault`; тогда это жёсткий override и выбор location в UI будет заблокирован.

После создания обязательно сохрани показанный recovery key **вне диска с Vault**. После закрытия предупреждения DiskShell повторно показать его не сможет.

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


### Commander 0.6.4

После обновления frontend поддерживает групповое выделение `Ctrl+Click`, `Shift+Click`, `Ctrl+A`, Select all / Clear. Copy/Move выполняются одним batch job с общим прогрессом. Rename/View/Extract намеренно остаются single-item операциями.


## Vault WRITE gate

Рекомендуемый дефолт остаётся `DS_ALLOW_VAULT_WRITES=0`. На странице **Vault** включи `VAULT WRITE ENABLED`, когда собираешься создать Vault, импортировать/шифровать или экспортировать файл. Разрешение живёт только в RAM backend и после restart снова становится `LOCKED`.

`DS_ALLOW_VAULT_WRITES=1` нужен только как постоянный environment override; для обычной локальной работы редактировать `.env` больше не требуется.


## SFTP / SSH и крупные файлы

Для Commander SFTP ничего отдельно включать не нужно. В 0.6.7 backend автоматически использует:

```text
SSH keepalive:       30 s
SFTP I/O timeout:   120 s
Reconnect attempts:   4
Backoff:           1/2/4/8 s
Resume:            from target size
```

При кратковременном обрыве Wi‑Fi/LAN/VPN или SSH channel Commander переподключается и продолжает текущий файл с уже подтверждённого offset. Прогресс при этом корректируется по фактическому размеру partial target. После полного копирования выполняется size verification.

После исчерпания быстрых reconnect attempts job переходит в `waiting_endpoint` и оставляет partial. Backend продолжает проверять endpoint и автоматически возобновляет transfer после его возвращения.

Важно: credentials/profile живут только в RAM backend. Поэтому reconnect работает в рамках текущего backend-процесса; restart backend не является persistent resume.


## Commander: обрывы, partial и конфликты имён

Начиная с 0.6.9, обычный workflow крупного Copy/Move:

1. Commander проверяет source и destination.
2. Если destination свободен — запускает job.
3. Если имя занято — запись не начинается до выбора **Continue / Replace / Keep both / Skip / Cancel**.
4. `Keep both` подбирает первый свободный индекс: `file (1).ext`, `file (2).ext`; для каталога — `Folder (1)`.
5. При кратком SSH/SFTP обрыве внутри job действуют keepalive + reconnect.
6. Если reconnect attempts закончились или оператор нажал Stop, partial target сохраняется.
7. Кнопка **Continue partial** запускает новый job с `conflict_policy=resume`, и запись продолжается с фактического размера target.
8. Исчезнувшие source-файлы считаются `missing/skipped` и не останавливают остальные элементы batch.

`Replace` — destructive только для destination и выполняется после повторной проверки существования source. `Move` удаляет source только после успешного копирования и size verification.

После restart backend локальный partial остаётся на диске и может быть продолжен новым Copy/Move. Для remote продолжения после restart нужно заново подключить SFTP/FTP profile, потому что credentials по-прежнему хранятся только в RAM.


## 0.7.0 — hot-unplug и waiting endpoint

Commander теперь ведёт Copy/Move как backend transfer manager. Для локального диска и remote endpoint состояние может быть:

```text
running → waiting_endpoint → running → completed
```

При отключении локального тома backend не считает путь «пропавшим файлом». Он ждёт появления тома и проверяет его identity. На Windows identity берётся из Volume GUID с fallback на volume serial; одной буквы диска недостаточно.

SSH/SFTP сначала использует keepalive и четыре быстрых reconnect, затем остаётся в waiting-state и продолжает проверки. После возврата server/volume фактический partial size заново читается и используется как resume offset.

UI inventory опрашивается периодически. Исчезнувший том помечается OFFLINE; открытая Commander pane восстанавливается после reconnect. Временная ошибка Windows disk inventory больше не должна ронять страницу «Диски».

Перезапуск **самого backend** пока завершает in-memory job. Partial остаётся на target и может быть продолжен через Continue после запуска; автоматическое восстановление job после restart потребует persistent transfer journal. SSH credentials намеренно остаются RAM-only.
