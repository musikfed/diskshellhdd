# StreamCopy EXP 0.7.5 · River Keeper

StreamCopy — отдельный экспериментальный local-copy engine. Обычный Commander не заменён и использует собственный transfer manager.

## Идея

Папка является одной логической рекой данных:

```text
SOURCE
  ↓ persistent manifest
producer
  ↓ bounded RAM queue
consumer
  ↓ .dspart
  ↓ verified publish
DESTINATION
```

RAM используется только как ограниченный рабочий буфер. Состояние самой задачи хранится в SQLite `data/diskshell.db`.

## Persistent River Journal

В SQLite сохраняются:

- job и её профиль;
- source/destination path;
- стабильная identity локальных томов;
- manifest items;
- size + source mtime каждого item;
- статус каждого файла;
- подтверждённый offset;
- checkpoints и SHA-256 каждого checkpoint-блока;
- counters/progress/warnings;
- lease owner/expiry для защиты от двух backend-владельцев одной job.

Это рабочее состояние transfer engine, а не обычный текстовый log.

## Checkpoint / “шаг назад”

Checkpoint по умолчанию — **128 MiB**. Незавершённый файл пишется в детерминированный:

```text
name.ext.dspart-<job-id>
```

После обрыва StreamCopy не доверяет фактическому размеру partial как произвольному offset.

Он идёт назад по сохранённым checkpoints и для кандидата проверяет SHA-256 соответствующего диапазона:

```text
source block
partial block
stored checkpoint digest
```

Только если все значения совпали, этот offset считается безопасным. Неподтверждённый хвост partial отрезается и участок записывается заново.

Если безопасный checkpoint не найден, текущий файл начинается заново с offset 0. Уже завершённые и опубликованные файлы не копируются повторно.

## Hot-unplug

SOURCE и DESTINATION bindятся к stable local volume identity (Windows Volume GUID, serial fallback).

```text
running
  ↓ disk removed
waiting_endpoint
  ↓ same volume identity returns
recovering
  ↓ verify checkpoint / truncate unsafe tail
running
```

Новый носитель с той же буквой диска не принимается как исходный endpoint.

## Restart backend

Незавершённые jobs остаются в SQLite. При старте backend запускается recovery manager.

У каждой активной job есть lease:

```text
lease_owner
lease_expires_at
```

Пока живой backend обновляет lease, другой backend не получает job. После смерти процесса lease истекает, новый backend claim'ит задачу и восстанавливает её из journal/checkpoints.

Живой Python thread не восстанавливается — создаётся новый worker той же persistent job.

## Browser

Browser остаётся только control surface. Закрытие, refresh, очистка cookies/localStorage или другой браузер не уничтожают job. Workspace state хранится backend-side, а StreamCopy UI заново подключается к active/latest persistent job.

## COPY вместо Move

StreamCopy не имеет отдельного разрушительного Move primitive.

Есть два режима:

1. **COPY** — источник остаётся. Проверка: Size или SHA-256.
2. **COPY → SHA-256 → DELETE SOURCE** — target сначала полностью записывается, проверяется SHA-256 и публикуется. Только затем удаляется соответствующий source file.

Если backend упал после publish, но до source delete, recovery видит completed target, повторно проверяет его и завершает только безопасную delete-фазу.

Если есть skipped/conflict/error, соответствующий source не удаляется.

## Destination conflicts

Существующий конечный target автоматически не перезаписывается. Item получает warning/skip. Собственные partial-файлы имеют job-specific `.dspart` имя и не считаются готовым target.

## Media profile

Media type задаётся вручную и фиксируется для job:

- HDD;
- SSD/NVMe;
- flash.

USB2/USB3/USB4 — transport hint, а не media type. Поэтому USB3 HDD → USB3 HDD остаётся HDD→HDD pipeline.

Drive cache — только hint для bounded RAM queue. Например HDD cache 32 MiB → 128 MiB не означает 128 MiB приложения.

## Scope

0.7.5 River Keeper local-only. Remote SFTP/FTP StreamCopy пока не реализован; remote transfers остаются в Commander. Extent-ordering/physical-locality scheduler и RAW placement также пока не входят в StreamCopy.
