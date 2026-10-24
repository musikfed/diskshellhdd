# DiskShell 0.8.1 — Commander River

## Что изменилось

Commander copy/move jobs теперь имеют persistent journal в SQLite и lease-защиту.

Состояние top-level transfer:

```text
pending -> copying -> verified -> completed
                   \-> skipped / missing
```

Для MOVE на разных томах/endpoint:

```text
COPY
  -> verify destination
  -> persist VERIFIED
  -> delete source
  -> persist COMPLETED
```

Если backend умер после VERIFIED, новый worker сначала повторно проверяет target и только затем удаляет source.

## Restart recovery

После restart backend:

- незавершённые Commander jobs находятся в SQLite;
- lease предыдущего процесса должен истечь;
- partial target используется как resume offset;
- уже completed top-level transfers не выполняются повторно;
- same-volume rename crash может быть распознан по отсутствующему source + корректному target;
- новый браузер может найти active job через backend, даже если localStorage пуст.

## SFTP rebind

Секреты не пишутся в journal.

В SQLite сохраняется только стабильная remote identity:

```text
protocol|host|port|username|root
```

После restart пользователь снова создаёт RAM connection profile с credentials. Если identity совпала, persistent Commander job автоматически заменяет старый connection_id на новый и продолжает.

## Split-brain

У job есть lease owner + expiry. Второй backend не может claim'ить живую job до истечения lease.

## Ограничения

- FTP/FTPS используют старый reconnect path, но restart recovery целевым профилем 0.8.1 считается прежде всего SFTP.
- Commander resume использует фактический размер partial target; это ещё не SHA-256 checkpoint journal как у StreamCopy River Keeper.
- Stop переводит job в terminal cancelled и не запускает её автоматически после restart.
