# Архитектура DiskShell

DiskShell строится вокруг смысла хранения, а не вокруг команд ОС.

## Слои

1. **UI / Workspace** — React: диски, обследование, аналитика, планы размещения, файлы, Vault, Storage Lab.
2. **Application API** — Flask blueprints. Браузер не передаёт произвольные shell-команды.
3. **Storage Brain** — классы хранения, placement rules, резерв свободного места и планы размещения.
4. **Read-side engines** — scanner, analytics, previews, archive browser, optional vision, extent inspection.
5. **Write-side engines** — copy/move/Trash, Vault writes, partition operations. У каждой области отдельный safety gate.
6. **Platform adapters** — Windows Storage PowerShell и системные утилиты только там, где их требует Windows.

## Главный принцип

Read-side и write-side разделены. Новый накопитель можно полностью обследовать и построить план, не включая ни одной операции записи.

## Storage Classes

По умолчанию: Incoming, Active, Media, Photos, Documents, Images/ISO, Archive, Backups, Development, Temporary, Vault, Quarantine, Other.

Placement Plan — это предложение: source, target, storage class, размер и причина. План не обязан сразу что-либо перемещать.

## Storage Lab

Storage Lab не притворяется, что приложение знает физическую геометрию пластин HDD. Managed Interleave описывается через логические lanes/extents. Сначала симуляция и read-only extent map, и только потом возможные экспериментальные перемещения.

## Vault

Envelope encryption: Argon2id создаёт KEK из identity + secret; случайный master key шифрует каталог и объекты через AES-GCM; отдельный recovery key независимо оборачивает master key. Unlock-состояние хранится только в RAM сервера и протухает по таймауту.

## Без Rust

Проект Python-only. Тяжёлая работа по возможности остаётся ОС, SQLite и нативным библиотекам, которые вызываются из Python.
