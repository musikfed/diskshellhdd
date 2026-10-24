# DiskShell HDD 0.8.4

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
- Двухпанельные Files Copy/Move выполняются background-job с Stop; незавершённый target сохраняется как partial для явного Continue, исходник сохраняется.
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

**Backend для storage-admin функций запускай elevated. Самый удобный способ из обычного PowerShell или VS Code terminal:**

```powershell
Set-Location "F:\diskshellhdd"
.\scripts\start-admin.ps1
```

Скрипт сам вызывает UAC только для backend. В VS Code также доступен task `DiskShell: Backend as Administrator`; отдельный task `DiskShell: Reopen VS Code as Administrator` повышает весь редактор и его extensions, поэтому используй его только для доверенного workspace.

Подробно, включая `runas`, см. [docs/DEPLOYMENT.ru.md](docs/DEPLOYMENT.ru.md).

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

## UI/workspace fixes 0.6.1

- исправлен blank-screen Commander: отсутствующий runtime handler теперь ловится frontend lint до merge;
- активная вкладка сохраняется после F5/refresh;
- для каждой вкладки сохраняется вертикальная scroll position;
- в общей шапке появился persistent **Active volume** selector;
- Vault получил отдельный выбор тома для Import source и Export destination;
- Commander сохраняет LEFT/RIGHT path, активную панель, Smart folders и archive format;
- page-level React error boundary показывает текст ошибки вместо пустого тёмного экрана;
- CI теперь запускает ESLint `no-undef` перед Vite build.

## Vault logical volume / folder workflow 0.6.2

- Vault выбирает не physical disk, а смонтированный логический том (`C:\\`, `F:\\`, `W:\\`);
- внутри выбранного тома доступен встроенный browser каталогов и файлов;
- можно выбрать один файл или текущую папку целиком;
- импорт папки выполняется рекурсивно с сохранением относительных путей;
- при экспорте выбирается логический том и каталог назначения; вложенная структура восстанавливается;
- physical disk selector по-прежнему используется только там, где речь о разметке, RAW access или диагностике поверхности.


## Vault location / first creation

При первом создании Vault место хранения теперь выбирается прямо в UI: **логический том + папка**, например `W:\\DiskShellVault`.

- Общий `Active volume` больше не является скрытой настройкой Vault: итоговый путь явно показан до создания.
- В корень тома (`W:\\`) Vault создать нельзя — нужна отдельная папка.
- После Create DiskShell создаёт внутри выбранной папки `vault.json`, `catalog.bin` и `objects\\`.
- Выбранный путь сохраняется в `data/vault-location.json`, поэтому после перезапуска backend открывается тот же Vault.
- Locator хранит только путь, без identity, secret, master key и recovery key.
- `DS_VAULT_ROOT` остаётся жёстким admin override: если он задан, UI не даёт выбрать другое место.
- Существующий Vault автоматически не переносится; выбор location относится к первому созданию.
- Recovery key после Create остаётся виден до явного подтверждения «Я сохранил recovery key».

## Commander multi-selection 0.6.5

- обычный клик — выбрать один объект;
- `Ctrl+Click` — добавить/убрать отдельный файл или папку;
- `Shift+Click` — выделить диапазон;
- `Ctrl+A` — выделить все объекты текущей панели;
- в каждой панели есть `Select all` и `Clear`;
- статус панели показывает число выбранных объектов и известный суммарный размер;
- F5 Copy и F6 Move создают один batch background job для всей выбранной группы;
- один batch может работать Local↔Local, Local↔SFTP/FTP и Remote↔Remote;
- Smart folders рассчитываются одним batch-запросом, а не отдельным HTTP-вызовом на каждый файл;
- F8 Trash/Delete и F9 Archive работают с группой;
- F2 Rename, F3 View и Extract требуют ровно один выбранный объект;
- Stop отменяет текущий незавершённый transfer item и очищает его partial target; уже завершённые и проверенные items остаются завершёнными.


## Vault create diagnostics 0.6.5

Если кнопка **Создать Vault** недоступна, UI теперь показывает точные блокирующие условия: Vault WRITE gate, выбранный путь, непустой идентификатор и секретная фраза минимум 8 символов. Серую кнопку без объяснения больше не нужно диагностировать вручную.


## Vault WRITE RAM toggle 0.6.6

`DS_ALLOW_VAULT_WRITES=0` теперь остаётся безопасным дефолтом, но больше не требует редактировать `.env` для обычной работы. На странице **Vault** есть отдельный переключатель:

```text
VAULT WRITE LOCKED ⇄ VAULT WRITE ENABLED
```

Включение хранится только в RAM backend и автоматически сбрасывается после restart backend. Этот gate управляет **Create Vault**, Import/Encrypt и Export. Если `DS_ALLOW_VAULT_WRITES=1`, это постоянный environment override и UI-toggle отключён как избыточный.


## SFTP / SSH large-file reliability 0.6.8

Для длинных SFTP-передач Commander теперь не рассчитывает на одну идеально стабильную SSH-сессию:

- SSH keepalive отправляется каждые **30 секунд**;
- дополнительно включается TCP keepalive, где это поддерживает ОС;
- зависший SFTP channel имеет I/O timeout **120 секунд**, после чего transfer переходит к reconnect вместо вечного зависания;
- при transient network/SSH error Commander делает до **4 reconnect attempts** с backoff 1/2/4/8 секунд;
- после reconnect размер уже записанного target перечитывается и upload/download продолжается **с этого offset**, а не с нуля;
- после завершения по-прежнему выполняется size verification; только после успешной проверки Move удаляет source;
- UI показывает число reconnects, retry attempt и приблизительный resume offset.

Resume работает пока жив backend job. Полный restart backend не восстанавливает незавершённый job: это отдельный будущий persistent-transfer слой.


## Zero-byte file transfer fix 0.6.8

Commander теперь корректно создаёт файлы размером 0 байт при Copy/Move между томами и в remote-transfer workflow. Раньше такой файл ошибочно считался уже полностью переданным при `offset == expected_size == 0`, хотя target ещё не существовал; последующий size verification завершался `FileNotFoundError`. Также `current_path` обновляется до начала каждого файла, включая пустые файлы.


## Commander conflicts / resume / missing sources 0.6.9

Copy/Move больше не использует правило «destination уже существует → весь job падает». Перед записью Commander возвращает структурированный конфликт и UI требует явное решение:

```text
Continue partial  — продолжить существующий неполный target по фактическому размеру
Replace all       — удалить конфликтующий target и записать заново
Keep both         — сохранить рядом как name (1), name (2), ...
Skip conflicts    — не трогать конфликтующие элементы и продолжить batch
Cancel            — ничего не писать
```

Автоматической перезаписи нет. Если source и destination — один и тот же объект, Replace/Continue блокируются; безопасным вариантом остаётся Keep both или Cancel.

При Stop или после исчерпания reconnect attempts незавершённый target **не удаляется**. Job помечает `partial_retained`, а UI показывает кнопку **Continue partial**. При следующем запуске того же Copy/Move существующий target определяется как resumable, если его размер не больше source. Для каталога Continue работает как merge/resume по файлам и размерам.

Если выбранный source исчез между отображением списка и фактическим стартом, batch больше не падает целиком: элемент получает counters `missing/skipped`, warning и обработка остальных элементов продолжается. То же применяется к отдельному файлу, который исчез уже во время обхода каталога.

Для Move source удаляется только после завершения и size verification соответствующего transfer. Replace повторно проверяет наличие source **до удаления destination**, чтобы stale selection не уничтожил существующий target.


## Resilient endpoints / backend transfer manager 0.7.0

Copy/Move окончательно перенесён в модель backend transfer manager. React/UI не владеет потоком данных: закрытие вкладки, refresh или render-error не останавливают живой backend job.

При hot-unplug локального диска или длительном обрыве SSH/SFTP:

```text
running
  ↓ endpoint lost
waiting_endpoint
  ↓ endpoint + identity снова доступны
running
  ↓
completed
```

- локальный volume проверяется по стабильной identity (Windows Volume GUID/serial fallback), а не только по букве `W:`;
- другой носитель, случайно получивший ту же букву, не используется для автоматического resume;
- backend сохраняет partial target и пересчитывает фактический размер перед продолжением;
- SSH использует keepalive + быстрые reconnect attempts, затем переходит в длительное `waiting_endpoint` вместо немедленного failed;
- Stop остаётся доступным в waiting-state и сохраняет partial;
- короткие операции вокруг transfer — mkdir, verify, rename и удаление source после Move — тоже ждут возврата endpoint;
- root/drive inventory опрашивается заново, offline volume показывается как OFFLINE, а hot-unplug не должен ронять страницу «Диски»;
- local Commander pane автоматически перечитывается после возврата тома.

Граница 0.7.0: сам backend-процесс должен оставаться живым. Persistent transfer journal для автоматического восстановления job после restart backend — отдельный следующий слой. Для remote после restart всё равно потребуется безопасно восстановить/rebind SSH profile, потому что пароль и private-key path не пишутся в SQLite/localStorage.


## StreamCopy EXP 0.7.5 · River Keeper

**StreamCopy · EXP** теперь хранит не только UI/job в RAM, а persistent river journal в SQLite. Manifest, file state, stable volume identity и 128 MiB checkpoints переживают restart backend. Незавершённый файл пишется в job-specific `.dspart`; после обрыва StreamCopy проверяет SHA-256 последнего checkpoint, отрезает неподтверждённый хвост и повторяет участок от безопасной точки.

Hot-unplug переводит job в `waiting_endpoint`; после возврата того же Volume GUID/identity job восстанавливается. Backend restart создаёт новый worker той же persistent job после lease claim.

Разрушительного Move primitive нет: либо **COPY**, либо опционально **COPY → SHA-256 → DELETE SOURCE** после успешной публикации и сравнения. Подробности: [docs/STREAMCOPY.ru.md](docs/STREAMCOPY.ru.md).


### Workspace 0.7.3 · актуальная вкладка живёт в backend

Последняя рабочая вкладка, активный том и scan id теперь сохраняются в SQLite backend, а не только в браузере. Очистка cookies/site data или переход в другой браузер не возвращают DiskShell на «главную»: при открытии восстанавливается актуальная вкладка. Если StreamCopy работает на фоне другой страницы, в шапке появляется `↩ StreamCopy · status`. Подробнее: [docs/WORKSPACE_STATE.ru.md](docs/WORKSPACE_STATE.ru.md).


## Logging 0.7.5 · консоль только для событий, а не polling

Browser/UI считается control surface. Успешные HTTP polling-запросы (`/api/files/roots`, `/api/ui-state`, StreamCopy status, frontend `304`) больше не печатаются в backend-консоль. В консоли остаются предупреждения и ошибки.

Значимые события пишутся в ротируемый журнал `data/logs/diskshell.log`: backend start, Commander/StreamCopy start/complete/cancel, endpoint waiting/resume, completed-with-warnings, transfer failure и HTTP 5xx/unhandled exceptions. Request bodies, cookies, пароли и remote credentials не журналируются. Ротация: 5 MiB × до 5 backup-файлов. Подробнее: [docs/LOGGING.ru.md](docs/LOGGING.ru.md).


## 0.8.0 · Persistent Workspace Foundation

- SSE-first event fabric: workspace, StreamCopy, Quick Index и storage inventory публикуют события; HTTP polling остаётся только медленным fallback.
- Backend-owned view state хранит scroll, Commander paths/active pane, Scan path, Storage Brain scopes, Diagnostics/Security preferences.
- `↗ Open view` открывает detached view для второго монитора; detached window не перезаписывает глобальную active page.
- Quick Index параллельно обновляет current SQLite file catalog; **Быстрый поиск** использует FTS5 или indexed fallback без нового обхода файловой системы на каждый запрос.
- **Relocation Planner** read-only классифицирует крупные каталоги и рекомендует leave/native relocate/junction/archive; destructive executor в 0.8.0 не включён.
- Disk descriptor map показывает реальные offsets, partitions и unallocated gaps.
- Partition Boundary Planner различает end grow/shrink и start relocation. Protected system/boot/application disks — plan-only; end resize на непротектированном диске требует per-disk WRITE + Administrator + typed confirmation + повторную identity check.
- Photos/People получил локальный similarity search по существующим SFace embeddings.
- `npm run update:safe:win` делает SQLite-consistent snapshot, update/build/tests и runtime rollback при ошибке.

Release guides 0.7.5: [RU](docs/RELEASE_0.7.5.ru.md) · [EN](docs/RELEASE_0.7.5.md) · [FR](docs/RELEASE_0.7.5.fr.md) · [DE](docs/RELEASE_0.7.5.de.md) · [ET](docs/RELEASE_0.7.5.et.md).

Roadmap: [RU](docs/ROADMAP_0.8.ru.md) · [EN](docs/ROADMAP_0.8.md). Failure validation: [RU](docs/FAILURE_TESTING.ru.md) · [EN](docs/FAILURE_TESTING.md). Safe update: [RU](docs/UPDATE_SAFE.ru.md) · [EN](docs/UPDATE_SAFE.md).


## 0.8.4 · Local Subject / Object Search

Photos / People теперь индексирует не только лица, но и локальные whole-image subject/object tags через optional ONNX classifier. После анализа теги и confidence сохраняются в SQLite, а поиск по `car / dog / keyboard / beach` выполняется без повторного inference на каждый запрос.

Настройка: `DS_IMAGE_CLASSIFIER_MODEL`, `DS_IMAGE_CLASSIFIER_LABELS`, `DS_IMAGE_CLASSIFIER_INPUT_SIZE`. Облако не используется. Это классификация всего изображения, не bounding-box detector.

Подробнее: [docs/RELEASE_0.8.4.ru.md](docs/RELEASE_0.8.4.ru.md).
