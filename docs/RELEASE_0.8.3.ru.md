# DiskShell 0.8.3 — Remote River / SFTP

## Идея

Remote River не создаёт отдельную систему копирования. Local и SFTP StreamCopy используют один persistent journal:

```text
streamcopy_jobs
streamcopy_items
streamcopy_checkpoints
lease owner / expiry
```

Поддерживаемые маршруты:

- Local → SFTP
- SFTP → Local
- SFTP → SFTP
- Local → Local остаётся на StreamCopy v2 microfile worker.

## Credentials

Пароль, private-key secret и другие credentials не записываются в SQLite.

Persistent endpoint хранит только:

```text
kind = remote
protocol = sftp
path
connection_id (может устареть после restart)
remote_identity = protocol|host|port|username|root
```

После restart пользователь заново создаёт RAM SFTP profile. River Keeper ищет новый profile по `remote_identity` и делает rebind.

Если подходящего profile пока нет, job остаётся в `waiting_endpoint`, а не переходит в `failed`.

## Checkpoints

Remote River использует те же SHA-256 checkpoint blocks, что и local River Keeper.

После обрыва или restart:

1. читается фактический размер remote/local `.dspart-<job>`;
2. проверяются сохранённые checkpoints от нового к старому;
3. одинаковый block SHA-256 должен совпасть у source и partial;
4. сомнительный хвост обрезается через truncate;
5. запись продолжается с последней подтверждённой точки.

SFTP выбран именно потому, что он даёт необходимые операции read/write/stat/rename/truncate с понятной файловой семантикой.

FTP/FTPS в Remote River 0.8.3 **не поддерживаются**: REST/STOR/truncate поведение слишком зависит от сервера для безопасного checkpoint rollback.

## Publish и COPY→DELETE

Файл сначала пишется как `.dspart-<job>`.

После проверки:

```text
partial -> verify -> rename/publish -> journal completed
```

В режиме COPY→SHA-256→DELETE SOURCE source удаляется только после успешной сильной проверки.

## Reconnect race

Если SFTP отвалился между endpoint-check и файловой операцией, worker повторно проверяет endpoint. При реальном disconnect job переходит в waiting и продолжает после reconnect/rebind, а не падает окончательно.

## UI

SOURCE и DESTINATION независимо выбираются как:

- Local volume
- SFTP

StreamCopy использует уже созданные RAM SFTP profiles из Commander. Кнопка `↻ SFTP profiles` обновляет список.

Для remote route transport автоматически считается `Network / SFTP`.

## Ограничения

- Remote microfile batching пока выключен: SFTP 0.8.3 использует последовательные checkpointed items.
- SFTP server-side fsync не стандартизирован. River Keeper полагается на подтверждённую SFTP запись и повторную hash-проверку partial после recovery.
- Physical media type удалённой стороны по-прежнему задаётся вручную.
