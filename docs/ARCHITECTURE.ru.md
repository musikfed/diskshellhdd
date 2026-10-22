# Архитектура DiskShell 0.5

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

0.5 разделяет global override и runtime authorization. При `DS_ALLOW_DISK_WRITES=0` выбранный непротектед disk можно разблокировать на 15 минут. Authorization связан с physical identity; если Number/UniqueId/Serial/Size меняются, запись снова блокируется.

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
