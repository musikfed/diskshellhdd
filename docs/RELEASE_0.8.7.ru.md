# DiskShell 0.8.7

## Изоляция workspace по вкладкам

- Scan, Storage Planner, Diagnostics, Security, Vault и StreamCopy больше не хранят рабочие пути и transient job id в общем для всех вкладок `localStorage`.
- Job id конкретной вкладки хранится в backend-строке `workspace_views` для её `view_id`; `sessionStorage` используется только как per-view fallback браузера.
- При продвижении состояния в default workspace transient job id удаляются. Новая вкладка может унаследовать полезную навигацию и пути, но не чужую выполняющуюся задачу.
- StreamCopy восстанавливает только job, явно принадлежащий текущему view. Автоподхват глобально последней active/last задачи удалён.

## Безопасность SFTP tree

- SFTP metadata теперь читается через `lstat`, поэтому symbolic link определяется без перехода к его цели.
- При построении remote manifest symbolic links пропускаются — аналогично локальной политике для symlink/junction.
- Recursive remote delete удаляет сам symbolic link и не проходит внутрь связанного с ним каталога.

## Очистка

Удалено устаревшее глобальное browser-state хранение для затронутых admin workflows. Рабочие storage-модули не удалялись.

## Проверка

Добавлены regression-тесты для фильтрации transient job id в default workspace и безопасной обработки SFTP symlink при metadata/tree walk.

Семантика разрешений на запись дисков и перемещение extents не менялась.
