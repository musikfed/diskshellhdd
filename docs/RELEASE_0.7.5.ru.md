# DiskShell 0.7.5 — Release Guide

## Что зафиксировано в этом релизе

0.7.5 — первая версия, где DiskShell рассматривает браузер как **сменный интерфейс рабочего места**, а не как владельца процессов и состояния.

Ключевой принцип:

```text
UI/view       — заменяемый
backend       — заменяемый исполнитель
workspace     — persistent
transfer job  — persistent
data          — persistent
```

### StreamCopy River Keeper

StreamCopy хранит в SQLite:

- job и media/profile параметры;
- manifest;
- source/destination volume identity;
- состояние каждого файла;
- confirmed offsets;
- SHA-256 checkpoints;
- warnings/progress;
- lease owner + expiry.

Незавершённый файл пишется как `.dspart-<job>`. После hot-unplug или backend restart непроверенный хвост не считается надёжным: River Keeper ищет последний подтверждённый checkpoint, повторно сверяет SHA-256 source/partial диапазона, отрезает сомнительный хвост и продолжает от безопасной точки.

### Защита от split-brain

Persistent state сам по себе не создаёт split-brain. Опасность появляется только если два процесса одновременно считают одну job своей.

Для этого у job есть:

```text
lease_owner
lease_expires_at
```

Живой backend обновляет lease. После смерти процесса lease истекает и новый backend может claim'ить job.

### COPY вместо разрушительного Move

StreamCopy имеет два режима:

1. **COPY** — source остаётся.
2. **COPY → SHA-256 → DELETE SOURCE** — source удаляется только после успешной записи, публикации и сильной проверки target.

Если есть сомнение, conflict, missing target или verification error — source не удаляется.

## Workspace

Актуальная вкладка, active volume и scan id хранятся в SQLite backend.

Поэтому:

- refresh не сбрасывает рабочее место;
- закрытие браузера не сбрасывает рабочее место;
- очистка cookies/localStorage не является потерей authoritative state;
- другой браузер на том же DiskShell открывает последнее backend workspace state.

## Логи

Routine HTTP polling не печатается в консоль.

Операторский журнал:

```text
data/logs/diskshell.log
```

Он ротируется и содержит значимые lifecycle events / warnings / failures, а не каждый успешный GET.

## Установка / обновление

```powershell
git fetch origin
git reset --hard origin/main
npm run build
.\scripts\start-admin.ps1
```

Для physical disk / raw / partition функций Windows backend должен быть запущен с Administrator privileges.

## Быстрая проверка после запуска

1. Открой `/api/health` и проверь версию `0.7.5`.
2. Убедись, что UI восстановил последнюю workspace-вкладку.
3. Проверь `data/logs/diskshell.log`.
4. Для StreamCopy сначала тестируй COPY без удаления source.
5. Hot-unplug/restart recovery проверяй на данных, для которых существует отдельная резервная копия.

## Известные границы 0.7.5

- StreamCopy River Keeper пока local-only.
- Commander имеет собственный transfer manager и не использует тот же persistent river journal после backend restart.
- UI ещё использует polling в ряде разделов.
- Не всё view-state перенесено из localStorage в backend workspace.
- Physical partition boundary relocation ещё не реализован.
- Object search по содержимому фото ещё не является полноценным semantic vision search.
- File index пока ориентирован на scan snapshots, а не на постоянно обновляемую near-real-time mini database.

## Важная эксплуатационная идея

Не сохранять «окно программы», а сохранять **состояние мира программы**.

После crash/reboot новый процесс должен восстановить persistent state и продолжить работу безопасным способом, а браузер только заново подключается к этому состоянию.
