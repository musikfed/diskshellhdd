# Snapshot-first update / rollback

0.8.0 добавляет `scripts/update-safe.ps1`.

## Что он делает

1. Проверяет активный StreamCopy и по умолчанию отказывается обновляться во время живой river-job.
2. Через SQLite backup API создаёт snapshot в `data/update-snapshots/<timestamp>`.
3. Сохраняет текущий git commit.
4. Fetch + переключение на `origin/main`.
5. Устанавливает frontend dependencies и делает build.
6. Запускает backend lint/tests и frontend lint.
7. Если любой этап падает — runtime откатывается на предыдущий commit; state snapshot остаётся нетронутым.

Запуск:

```powershell
npm run update:safe:win
```

Принудительное обновление при active StreamCopy возможно напрямую через script с `-Force`, но это не рекомендуемый обычный путь.

Snapshot не копирует payload transfer-файлов: `.dspart` остаются на target volumes и восстанавливаются River Keeper через journal.
