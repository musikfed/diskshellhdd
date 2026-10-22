# Развёртывание DiskShell 0.5 на Windows 11

## Чистая установка / восстановление

GitHub `main` — источник истины.

```powershell
Set-Location F:\
Remove-Item F:\diskshellhdd -Recurse -Force -ErrorAction SilentlyContinue
git clone "https://github.com/musikfed/diskshellhdd.git" "F:\diskshellhdd"
Set-Location "F:\diskshellhdd"
Copy-Item .env.example .env
uv sync --group dev
uv run ruff check backend tests
uv run pytest -v
npm run ui:install
npm run build
uv run python -m backend.app
```

Открыть `http://127.0.0.1:8765/`.

Если нужны старые scan history / Vault runtime files, заранее сохрани `data` и верни его до первого запуска backend. SQLite migrations выполняются автоматически.

## Disk write в 0.5

Оставлять рекомендуется:

```text
DS_ALLOW_DISK_WRITES=0
```

Это отключает **global override**, но не блокирует администраторский workflow. На странице Disks:

1. выбери physical disk;
2. проверь model / serial / UniqueId / size;
3. нажми «Разблокировать только этот диск»;
4. введи точную фразу;
5. runtime unlock действует 15 минут;
6. после работы нажми «Заблокировать запись».

System / Boot / Application disk разблокировать нельзя.

`DS_ALLOW_DISK_WRITES=1` — глобальный override для контролируемой лаборатории/automation и для обычной эксплуатации не рекомендуется.

## Partition / Volume Manager

0.5 умеет:

- initialize RAW disk как GPT или MBR;
- создать partition в unallocated space;
- использовать максимальный free extent или заданный размер;
- форматировать новый volume в NTFS/exFAT;
- выбрать cluster 4/8/16/32/64 KiB;
- назначить drive letter;
- destructive whole-disk workflow Clear → Initialize GPT → one maximum partition → Format.

Все write-операции требуют per-disk unlock и typed confirmation.

## Stop buttons

Stop доступен для Quick Index, Placement Executor и Security Scan. Отмена cooperative: уже завершённая атомарная операция не отменяется молча.

## Recovery

Recovery page пока read-only: topology snapshots сохраняются в SQLite, raw signature probe читает MBR/GPT и boot sectors. Это диагностическая основа для будущего recovery engine, а не обещание автоматического восстановления данных.

## Security

Используются локальные Microsoft Defender или ClamAV. DiskShell запускает scan без remediation. Если ни один engine не найден, UI это показывает.

## Extras

Preview PDF/7Z/ISO: `uv sync --group dev --extra preview`.

Photos/People: `uv sync --group dev --extra vision`, затем задать локальные YuNet/SFace ONNX paths.

До появления remote-auth оставлять `DS_HOST=127.0.0.1`.

См. также [SAFETY.ru.md](SAFETY.ru.md).
