# DiskShell logging 0.7.4

DiskShell использует консоль как операторский канал, а не как HTTP access-log.

## Консоль

В нормальной работе не печатаются routine requests:

- `GET /api/files/roots 200`;
- `GET /api/ui-state 200`;
- `PATCH /api/ui-state 200`;
- polling StreamCopy;
- `304` для frontend assets.

В консоли остаются только предупреждения и ошибки, которые требуют внимания.

## Event journal

Журнал находится в:

```text
data/logs/diskshell.log
```

Он хранит значимые события, например:

- backend start;
- StreamCopy start;
- StreamCopy completed;
- completed with warnings;
- operator cancel;
- StreamCopy failure;
- HTTP 5xx / unhandled backend exception.

Тела HTTP запросов, cookies, пароли и remote credentials в журнал не записываются.

## Ротация

`diskshell.log` ограничен 5 MiB. Хранится до пяти старых rotated-файлов. Это не позволяет журналу бесконечно расти.

UI остаётся control surface: polling и отрисовка интерфейса не являются операторскими событиями и поэтому не засоряют журнал.
