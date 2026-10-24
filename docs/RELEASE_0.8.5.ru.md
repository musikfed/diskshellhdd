# DiskShell 0.8.5 — HDD NTFS Locality Scheduler

## Что добавлено

StreamCopy получил второй локальный ordering mode:

```text
Manifest / directory order
NTFS first-LCN locality · EXP
```

Locality mode работает только для **Local HDD source** и включается вручную.

## Как работает

После обычного manifest scan DiskShell read-only читает у каждого файла первый доступный NTFS LCN через Windows:

```text
CreateFile
  -> DeviceIoControl(FSCTL_GET_RETRIEVAL_POINTERS)
  -> first allocated LCN
  -> sort manifest by first LCN
  -> existing River Keeper copy engine
```

То есть меняется только порядок чтения source-файлов.

Не меняются:

- содержимое файлов;
- destination filesystem semantics;
- River Keeper checkpoints;
- microfile RAM frames;
- WRITE gates;
- NTFS extents на source или destination.

`DS_ALLOW_EXTENT_MOVES` locality scheduler **не включает и не использует**.

## Зачем

Для механического HDD directory order может заставлять головку много раз прыгать между далеко расположенными файлами. First-LCN order является приближением к более последовательному чтению файловой системы.

Особенно имеет смысл экспериментировать на:

- больших каталогах с тысячами файлов;
- HDD source;
- данных, которые физически разнесены по NTFS;
- HDD→HDD и HDD→SSD копировании.

## Что LCN НЕ означает

LCN — logical cluster number, видимый NTFS.

Это **не** точная физическая координата platter/head/cylinder. Современный HDD скрывает:

- zoning;
- remapping;
- spare sectors;
- caches;
- read-ahead;
- NCQ/command scheduling;
- реальную angular/head geometry.

Поэтому DiskShell называет режим locality scheduler, а не «physical platter sorter».

## Safety / fallback

- режим read-only;
- если LCN получить нельзя, файл не теряется и не пропускается;
- known-LCN файлы сортируются по LCN;
- unknown-LCN файлы остаются в исходном стабильном порядке после них;
- если ни одного LCN прочитать не удалось, manifest фактически остаётся исходным и пишется warning;
- SFTP Remote River всегда использует manifest order;
- SSD/Flash UI locality не активирует.

## Почему не default

0.8.5 специально оставляет режим opt-in.

Сравни два прогона одного и того же набора:

1. Manifest order.
2. NTFS first-LCN locality.

Смотри итоговое elapsed time, стабильность MiB/s и число файлов/сек. Только после реальных benchmark результатов имеет смысл решать, включать ли locality автоматически для конкретного профиля.
