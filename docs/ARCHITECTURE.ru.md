# Архитектура DiskShell 0.5.6

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

## Per-disk write authorization

0.5.6 разделяет global override и runtime authorization. При `DS_ALLOW_DISK_WRITES=0` выбранный непротектед disk можно разблокировать на 15 минут. Authorization связан с physical identity; если Number/UniqueId/Serial/Size меняются, запись снова блокируется.

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

## Storage wizard 0.5.6

Разметка разделена на отдельные слои: Initialize partition table, create partition/volume и whole-disk destructive workflow. Форматирование использует Windows Storage `Format-Volume`; поддерживаемые профили DiskShell: NTFS, exFAT, ReFS, FAT32 и FAT.

Размер тома валидируется вместе с allocation unit до destructive execution. Для NTFS/FAT/FAT32 учитываются cluster-count limits. Whole-disk wizard может создать первый том меньше физического диска и оставить остаток Unallocated.

Job progress делится на determinate и indeterminate. Files Copy/Move и Placement знают total bytes; Quick Index, Defender/ClamAV и destructive Windows Storage operations не подделывают процент.

## Adaptive Macro Interleave 0.5.6

Целевая раскладка — это не random fragmentation. Алгоритм использует lane policies с `min / target / max band`, weighted fair scheduling и extent budget.

Seek-derived floor вычисляется из измеренных sequential throughput и seek latency. Если полоса слишком короткая для данного HDD, effective minimum повышается, но не выше max policy.

При сегментации файла выбирается число почти равных extents. Это устраняет короткий tail fragment. Маленькие файлы остаются целыми и могут группироваться внутри общей lane band.

Пример базовых target bands: Media ~512 MiB, Photo ~192 MiB, Interactive ~96 MiB, Cold ~1 GiB, Temporary ~128 MiB. Эти значения не являются физической геометрией HDD и могут адаптироваться.

До включения реальных FSCTL_MOVE_FILE операций требуется сравнить normal NTFS, contiguous и simulated adaptive interleave на реальном диске по sequential/random/mixed workload.

## Commander / remote transport 0.5.6

File Manager использует endpoint descriptors (`local` или `remote`) и единый cancellable Commander job. Remote profiles содержат SFTP/FTP credentials только в RAM. SFTP использует Paramiko; FTP/FTPS — ftplib. Cross-endpoint move выполняется как copy → size verification → delete source после успеха.

Preview remote-файла выполняется через bounded temporary cache backend. Archive/Preview providers затем работают так же, как для локального файла.

Direct transfer не меняет destination policy. Smart placement отдельно вычисляет Storage Class и lane/target-band hint. Это логическая политика размещения; она не является гарантией физической HDD geometry.
