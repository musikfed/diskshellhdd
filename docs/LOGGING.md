# DiskShell logging 0.7.4

DiskShell treats the console as an operator channel, not an HTTP access log.

Routine successful requests such as roots polling, UI-state updates, StreamCopy status polling, and static-asset 304 responses are not printed.

The event journal is stored at:

```text
data/logs/diskshell.log
```

It records meaningful lifecycle events and failures such as backend start, StreamCopy start/completion/cancel/failure, completed-with-warnings, HTTP 5xx responses, and unhandled backend exceptions.

HTTP request bodies, cookies, passwords, and remote credentials are not journaled.

The log rotates at 5 MiB and keeps up to five backups, preventing unbounded growth.

The UI remains a control surface; polling/render traffic is implementation detail rather than an operator event.
