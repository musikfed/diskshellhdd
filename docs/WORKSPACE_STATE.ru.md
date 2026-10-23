# DiskShell 0.7.3 · серверное workspace-состояние

DiskShell больше не считает `dashboard` обязательной стартовой страницей. Навигация — это состояние локального рабочего места.

Backend хранит в SQLite `data/diskshell.db`:

- актуальную вкладку (`active_page`);
- активный том (`active_volume`);
- текущий scan id (`scan_id`).

При открытии UI React сначала читает `/api/ui-state` и только после этого рендерит рабочую вкладку. Поэтому очистка cookies/localStorage, другой браузер на том же локальном DiskShell или обычный refresh не сбрасывают рабочее место.

Browser localStorage остаётся только fallback-кэшем на случай временной недоступности backend и не является источником истины.

Никаких popup/window.open не используется. Блокировщик всплывающих окон на восстановление вкладки не влияет.

Если StreamCopy работает, а пользователь ушёл на другую вкладку, в шапке появляется `↩ StreamCopy · <status>`. При возврате StreamCopy повторно подключается к backend-owned job. Если активной job уже нет, вкладка умеет показать последнюю backend job, в том числе из другого браузера.

## Локальная модель

Это intentionally single-workspace режим без учётной записи: последний переход в любом открытом браузере становится актуальным workspace state для этого экземпляра DiskShell. Для будущего multi-user/multi-device масштаба состояние можно будет привязать к workspace/user id.

## Граница

Workspace state переживает restart backend, потому что хранится в SQLite. Живой StreamCopy worker пока RAM-only: restart backend завершает текущий worker. Для восстановления самой передачи после restart нужен отдельный persistent transfer journal.
