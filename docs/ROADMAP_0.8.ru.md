# DiskShell 0.8.x — Engineering Roadmap

Опорный релиз: **0.7.5 River Keeper**.

## Принцип

DiskShell развивается как persistent workspace runtime:

```text
durable state + durable jobs + replaceable executors + replaceable views
```

## 1–13

1. **River Keeper torture / failure injection.** Автоматические crash/restart/checkpoint тесты + ручной Windows hot-unplug checklist. Реальный USB hot-unplug остаётся hardware validation, CI его физически воспроизвести не может.
2. **Event fabric.** SSE first, WebSocket только если понадобится duplex. События: workspace, StreamCopy, disks/endpoints, jobs, scans.
3. **Backend-owned view state.** Пути, раскрытые панели, scan/job ids и другие рабочие настройки уходят из authoritative localStorage в SQLite workspace state.
4. **StreamCopy v2 throughput.** Microfile batching/frames, экспериментальный scheduler для HDD locality, отдельная телеметрия scan/transfer.
5. **Persistent Commander.** Copy/upload/download/remote transfer journal + lease/checkpoints/restart recovery.
6. **Relocation Planner.** Read-only анализ C:/другого scan: system/hot/data/cache, штатный перенос, junction candidate, archive candidate.
7. **Snapshot / atomic updater.** Snapshot текущего commit + data backup → update/build/health check → rollback при ошибке.
8. **Multi-view / multi-monitor.** Явное пользовательское “Open current view in new window”; detached view не перезаписывает global active page.
9. **Remote StreamCopy.** Persistent river поверх SFTP после безопасного credential/profile rebind; FTP только после оценки restart semantics.
10. **Disk descriptor map.** Графическое отображение disk → offsets → partitions → free gaps → filesystem/health/write state.
11. **Partition boundary planner.** Безопасный plan для grow/shrink end. Перемещение start boundary не маскируется под обычный Resize-Partition: требуется relocation/recreate/offline strategy. System/boot сначала read-only plan.
12. **Photo search.** Face/person search + similarity по embeddings; object/subject semantic search — local model capability, без cloud-by-default.
13. **Fast file catalog.** SQLite current catalog + FTS/indexes, обновление во время scan, быстрый поиск без обхода файловой системы на каждый запрос.

## Safety gates

- destructive partition execution не добавляется без identity binding, snapshot/backup warnings, typed confirmation и повторного inventory;
- system/boot/application disk остаются protected для write execution;
- source deletion только после сильной проверки;
- remote credentials не сохраняются открытым текстом;
- event stream не должен содержать secrets/request bodies.

## Release slicing

- **0.8.0 Foundation:** release docs, event fabric, server view state, multi-view, file catalog/search, descriptor map, resize planner.
- **0.8.1 Data intelligence:** relocation planner, face similarity, local object tagging/search.
- **0.8.2 Transfer convergence:** Commander persistent journal + StreamCopy microbatch experiments.
- **0.8.3 Remote River:** SFTP persistent StreamCopy and credential rebind.
- **0.8.4 Runtime updates:** snapshot/atomic updater hardening and rollback verification.
