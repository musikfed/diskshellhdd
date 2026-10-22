# Архитектура DiskShell 0.4

## Принцип

```text
React UI
   ↓
Application API
   ↓
Storage Brain ─ Analytics ─ Preview ─ People ─ Vault
   ↓
Placement Planner / Safe Executor
   ↓
Filesystem + Windows storage adapters
   ↓
NTFS / Windows / HDD
```

PowerShell не является архитектурным центром. Это всего лишь один adapter для Windows Storage API.

## Read side

`Get-Disk/Get-Partition/Get-Volume`, Quick Index, Analytics, preview, archive/ISO browse, duplicates candidates/hashing, Photos/People, NTFS extent query и benchmark. Read side включён всегда.

## Write side

File workspace, Placement Executor, Vault writes, archive extraction, Partition Magic и будущий extent mover — независимые domains с независимыми gates.

Placement Executor не делает обычный `Move-Item` вслепую:

- same volume: проверка исходника → atomic rename/move → verification → journal; возможен rollback;
- cross volume: copy во временный target → verify size или SHA-256 → atomic publish target → исходник остаётся на месте для ручной проверки.

## Storage Brain

Storage Classes описывают назначение данных, а не физические разделы: Incoming, Active, Media, Photos, Documents, Images, Archive, Backups, Development, Temporary, Vault, Quarantine, Other.

Planner сопоставляет факты файла с правилами, строит target paths, предотвращает конфликты имён и считает projected free space. Перемещение данных внутри одного тома не считается дополнительным расходом места; cross-volume copy считается.

## Vault

Envelope encryption: identity+secret → Argon2id KEK → wrapped random 256-bit master key. Recovery key независимо wraps тот же master key. Catalog зашифрован AES-GCM. Большие objects пишутся chunked AES-GCM, поэтому терабайтный файл не загружается целиком в RAM. Unlock key хранится в памяти backend, browser использует HttpOnly SameSite cookie.

## Photos / People

При установленном `vision` extra и локальных YuNet/SFace ONNX моделях DiskShell детектирует лица, получает embeddings, хранит их в SQLite и группирует в Persons. Запросы `alone` и `with_others` основаны на количестве лиц в фото. Никакого cloud API.

## Partition Magic

Любая разрушительная операция требует: включённый disk gate → повторное обнаружение disk identity → disk не protected → точная typed confirmation. Основной предполагаемый layout большого storage HDD: GPT + один NTFS/exFAT partition.

## Storage Lab

Три разных понятия не смешиваются:

1. Allocation/extent map — фактические VCN→LCN extents, доступные ОС.
2. Target layout — логическая модель Managed Interleave.
3. HDD firmware geometry — скрыта и не контролируется DiskShell.

0.4 умеет симулировать target layout, читать file extents и собирать read benchmark. Actual `FSCTL_MOVE_FILE` mover остаётся заблокированным до тестов на целевом HDD.
