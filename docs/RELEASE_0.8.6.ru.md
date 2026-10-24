# DiskShell 0.8.6 — Multi-view workspace + SQLite concurrency hotfix

## Исправлено: `database is locked`

Workspace API больше не превращает обычный GET в SQLite write.

До 0.8.6:

- каждый `GET/PATCH /api/ui-state` вызывал schema initialization;
- каждый SQLite connect повторно выполнял `PRAGMA journal_mode=WAL`;
- GET делал `INSERT OR IGNORE`;
- PATCH с `view_state` использовал несколько соединений.

При параллельном Quick Index / Commander journal / workspace patches это могло приводить к:

```text
sqlite3.OperationalError: database is locked
```

0.8.6:

- WAL переключается один раз при startup/schema init;
- schema init защищён process lock и кэшируется для текущей DB;
- workspace GET — pure read;
- workspace PATCH — одна SQLite connection / одна transaction;
- `busy_timeout` остаётся на соединениях.

## Несколько вкладок / мониторов

Каждая browser tab получает собственный `view_id`.

Backend хранит:

```text
workspace_state      -> default workspace для новой вкладки/браузера
workspace_views      -> состояние конкретной вкладки
commander_jobs       -> persistent operations, не принадлежат вкладке
streamcopy_jobs      -> persistent River jobs, не принадлежат вкладке
```

Поэтому можно одновременно держать:

```text
Tab A -> Files / SFTP
Tab B -> Disks
Tab C -> StreamCopy
```

Переход Tab B на другую страницу больше не переводит A или C.

Detached view (`↗ Open view`) получает новый `view_id` и не меняет global/default workspace.

## Что запоминается по view

- active page;
- active volume;
- scan context;
- scroll position;
- Commander left/right paths;
- active Commander pane;
- Commander job id;
- Smart folders / archive preference;
- остальные существующие workbench view-state поля.

Browser `sessionStorage` используется только как per-view fallback. Авторитетное состояние — backend SQLite.

## Jobs и закрытие вкладки

Commander Copy/Move и StreamCopy принадлежат backend.

Закрытие/refresh/navigation вкладки:

- не отменяет job;
- не снимает lease;
- не удаляет partial;
- при новом view можно снова подключиться к persistent job.

## SFTP F5

Remote directory перед стартом Copy должен один раз построить recursive SFTP manifest. Раньше в этот момент UI выглядел как будто F5 ничего не сделал.

0.8.6 показывает отдельное состояние:

```text
Preparing transfer…
SFTP: строю manifest удалённого дерева и проверяю destination…
```

После создания Commander job transfer полностью backend-owned.

## Storage watcher

Background watcher больше не запускает тяжёлый полный PowerShell inventory каждые 3 секунды.

Он отслеживает дешёвую root topology и при изменении посылает refresh event. Полный disk inventory выполняется страницей Disks по событию или медленному fallback.

Также hidden/unformatted partitions больше не вызывают ненужный `Get-PartitionSupportedSize`.
