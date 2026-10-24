# DiskShell 0.8.2 — StreamCopy v2 Microfile Frames

## Что изменилось

StreamCopy v2 делает следующий шаг от “одна job на папку” к настоящему логическому потоку для множества маленьких файлов.

Файлы до **1 MiB** могут собираться producer'ом в RAM frames размером текущего stream chunk:

```text
manifest
  -> microfile candidates
  -> producer packs many files into one RAM frame
  -> bounded frame queue
  -> consumer
  -> ordinary destination files
```

Например при HDD→HDD chunk 8 MiB несколько файлов по 50–500 KiB проходят через очередь как один frame, но на destination остаются отдельными обычными файлами с исходными именами.

## Safety / recovery

Microbatch используется только когда:

- item ещё `pending`;
- размер не больше 1 MiB;
- нет существующего target;
- нет `.dspart` recovery tail.

Если frame-path встречает ошибку, StreamCopy возвращается к обычному per-file River Keeper path для этой группы. Уже опубликованные items определяются journal state и не копируются заново.

COPY→SHA-256→DELETE SOURCE продолжает использовать тот же verify/publish/delete порядок.

## Телеметрия

`Average MiB/s` теперь измеряет текущую transfer session после построения manifest. Время scan/planning больше не занижает среднюю скорость копирования.

## UI / события

StreamCopy UI теперь SSE-first:

- `streamcopy.progress` и `streamcopy.changed` обновляют экран;
- постоянный GET каждые 400 ms убран;
- HTTP GET остаётся редким reconciliation fallback примерно раз в 10 секунд.

Это уменьшает access-log noise и лишние запросы.

## Что пока не включено

- NTFS physical-extent/locality scheduler ещё не включён автоматически: сначала нужны сравнительные benchmarks.
- Remote River/SFTP — следующий отдельный этап 0.8.3.
- Microbatch не отменяет filesystem metadata cost: destination всё равно создаёт каждый файл отдельно.
