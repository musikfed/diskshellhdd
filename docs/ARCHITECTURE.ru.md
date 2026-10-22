# Архитектура DiskShell 0.6.0

```text
React/Vite Admin Workbench
        ↓
Flask Application API
        ↓
Storage Brain ─ Analytics ─ Preview ─ People ─ Vault
        │             ├─ Recovery / Forensics (read-only)
        │             └─ Security scanner adapters
        ↓
Cancelable Jobs / Safe Executors
        ↓
Filesystem + Windows Storage adapters
        ↓
NTFS / Windows / HDD
```

PowerShell — только Windows storage adapter, а не модель продукта.

## Write authorization

Physical disk WRITE и file WRITE — независимые runtime gates.

- `DS_ALLOW_DISK_WRITES=0`: global override выключен; non-protected physical disk можно вручную WRITE-enable до ручного выключения/restart backend. Разрешение связано с Number + UniqueId + Serial + Size.
- `DS_ALLOW_FILE_WRITES=0`: global file override выключен; Commander/Storage Brain могут временно включить FILE WRITE только в RAM backend.
- System / Boot / Application disks остаются backend-protected.

System / Boot / Application disk блокируются до любого destructive executor.

## Partition / Volume layer

`volume_manager.py` отвечает за initialize, create partition + format volume и drive-letter assignment. Whole-disk Clear/Format остаётся отдельным explicit destructive workflow.

## Jobs / Stop

Quick Index и Placement Executor cooperative-cancellable. Cross-volume placement copy идёт chunks с проверкой cancel и temporary partial target. Security scan запускается внешним local scanner process и может быть terminated.

## Persistence

Scan facts, placement plans, operation journal, Recovery snapshots и Security results хранятся в SQLite. UI хранит только active identifiers/settings в localStorage и восстанавливает plan после refresh из backend.

## Recovery / Forensics

Read-only raw probes распознают MBR `55AA`, GPT `EFI PART` и boot-sector identifiers NTFS/exFAT/FAT32/BitLocker. Это диагностический слой, не write-side recovery.

## Security

Adapters: Microsoft Defender (`MpCmdRun.exe`) и ClamAV (`clamscan`). DiskShell не выдаёт себя за отдельный antivirus engine и не поставляет собственную сигнатурную базу.

## Storage Lab

Managed Interleave остаётся logical target-layout моделью поверх NTFS. Firmware geometry HDD не контролируется. Extent relocation остаётся отдельным заблокированным experimental domain.

## Storage wizard 0.6.0

Разметка разделена на отдельные слои: Initialize partition table, create partition/volume и whole-disk destructive workflow. Форматирование использует Windows Storage `Format-Volume`; поддерживаемые профили DiskShell: NTFS, exFAT, ReFS, FAT32 и FAT.

Размер тома валидируется вместе с allocation unit до destructive execution. Для NTFS/FAT/FAT32 учитываются cluster-count limits. Whole-disk wizard может создать первый том меньше физического диска и оставить остаток Unallocated.

Job progress делится на determinate и indeterminate. Files Copy/Move и Placement знают total bytes; Quick Index, Defender/ClamAV и destructive Windows Storage operations не подделывают процент.

## Adaptive Macro Interleave 0.6.0

Целевая раскладка — это не random fragmentation. Алгоритм использует lane policies с `min / target / max band`, weighted fair scheduling и extent budget.

Seek-derived floor вычисляется из измеренных sequential throughput и seek latency. Если полоса слишком короткая для данного HDD, effective minimum повышается, но не выше max policy.

При сегментации файла выбирается число почти равных extents. Это устраняет короткий tail fragment. Маленькие файлы остаются целыми и могут группироваться внутри общей lane band.

Пример базовых target bands: Media ~512 MiB, Photo ~192 MiB, Interactive ~96 MiB, Cold ~1 GiB, Temporary ~128 MiB. Эти значения не являются физической геометрией HDD и могут адаптироваться.

До включения реальных FSCTL_MOVE_FILE операций требуется сравнить normal NTFS, contiguous и simulated adaptive interleave на реальном диске по sequential/random/mixed workload.

## Commander / remote transport 0.6.0

File Manager использует endpoint descriptors (`local` или `remote`) и единый cancellable Commander job. Remote profiles содержат SFTP/FTP credentials только в RAM. SFTP использует Paramiko; FTP/FTPS — ftplib. Cross-endpoint move выполняется как copy → size verification → delete source после успеха.

Preview remote-файла выполняется через bounded temporary cache backend. Archive/Preview providers затем работают так же, как для локального файла.

Direct transfer не меняет destination policy. Smart placement отдельно вычисляет Storage Class и lane/target-band hint. Это логическая политика размещения; она не является гарантией физической HDD geometry.


## Placement execution 0.6.0

Большой Placement Plan хранится в SQLite и выдаётся UI страницами. Новый plan создаётся с `selected=0`; executor читает только явно отмеченные строки. Это позволяет работать со scan на сотни тысяч файлов без загрузки всего plan в браузер или executor.

Cross-volume path: chunked copy → fsync → Size/SHA-256 verification → atomic publish. Source остаётся до ручной проверки. После publish выполняется read-only NTFS extent query.

`layout_lane` и `target_band_bytes` — **policy**, не обещание физической геометрии. Layout verification сравнивает фактический NTFS-visible extent count с приблизительным ожидаемым macro-band count и выдаёт `conforming / drift / unavailable`. Это диагностический этап перед будущим Managed Interleave writer.

## Runtime server

При `DS_DEBUG=0` `python -m backend.app` использует Waitress. Elevated Administrator/root процесс должен оставаться привязанным к loopback, пока не реализована полноценная remote authentication.
