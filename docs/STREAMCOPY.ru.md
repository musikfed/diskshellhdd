# StreamCopy EXP 0.7.2

StreamCopy — отдельный экспериментальный local-copy engine. Обычный Commander не изменён.

## Модель

Папка сначала сканируется один раз в manifest, после чего данные проходят через ограниченный producer/consumer ring buffer:

```text
SOURCE → producer → bounded RAM queue → consumer → DESTINATION
```

Файлы на приёмнике остаются обычными файлами файловой системы. RAW-сектора и собственный формат хранения не используются.

## Ручной профиль носителей

Тип SOURCE и DESTINATION выбирается оператором и блокируется на время job:

- HDD;
- SSD/NVMe;
- USB flash/card.

Подключение задаётся отдельно: Internal, USB 2.0, USB 3.x, USB4/Thunderbolt или Unknown. USB не меняет media type. Поэтому HDD→HDD через USB 3.x остаётся HDD→HDD sequential pipeline.

Для двух USB-устройств есть topology hint: unknown, shared hub/controller или separate paths/controllers.

Drive cache SOURCE/DESTINATION задаётся вручную как hint. Это не размер RAM buffer. Для тестовой пары 32 MiB → 128 MiB при USB3/USB3 и неизвестной topology используется 8 MiB chunk и ограниченная очередь до 48 MiB; shared USB path уменьшает очередь до 32 MiB.

## Safety

StreamCopy использует общий FILE WRITE gate. Существующий destination-файл в 0.7.2 не перезаписывается автоматически: item получает warning/skip. Один unreadable source item также должен быть пропущен без остановки всего batch.

Это экспериментальный движок: пока нет Move, remote/SFTP, persistent journal, resume после restart, extent-ordering или RAW-placement.


## Backend-owned jobs и повторное подключение UI

StreamCopy job принадлежит backend, а не React-странице. Переход на другую страницу DiskShell, refresh или закрытие вкладки браузера не посылают cancel и не останавливают worker. UI сохраняет active job id локально; при повторном открытии сначала пытается восстановить его, а затем запрашивает у backend последнюю активную StreamCopy job. После подключения снова показываются исходный/целевой пути, профиль и живой прогресс.

Это не persistence после restart backend: текущий job registry и worker threads остаются RAM-only. Перезапуск backend требует отдельного persistent journal/resume слоя.
