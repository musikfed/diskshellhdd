# DiskShell 0.7.5 — Release-Handbuch

## Grundidee

In 0.7.5 ist der Browser nur eine **austauschbare Ansicht** des Arbeitsbereichs. Er besitzt weder langlebige Jobs noch den dauerhaften Zustand.

```text
UI/View       — austauschbar
Backend       — austauschbarer Executor
Workspace     — persistent
Transfer-Job  — persistent
Daten         — persistent
```

### StreamCopy River Keeper

StreamCopy speichert Job, Manifest, Volume-Identitäten, Datei-Zustände, bestätigte Offsets, SHA-256-Checkpoints, Fortschritt, Warnungen und Lease-Informationen in SQLite.

Unvollständige Dateien werden als `.dspart-<job>` geschrieben. Nach Hot-Unplug oder Backend-Neustart wird ein beliebiges Partial-Ende nicht vertraut. River Keeper sucht den letzten verifizierten Checkpoint, prüft Source- und Partial-Block erneut, schneidet den unsicheren Rest ab und setzt dort fort.

### Split-Brain-Schutz

Persistente Jobs besitzen `lease_owner` und `lease_expires_at`. Ein lebendes Backend erneuert das Lease. Nach dessen Ausfall darf ein neues Backend den Job erst nach Ablauf des Lease übernehmen.

### Sicheres COPY

Zwei Modi:

1. **COPY** — Quelle bleibt erhalten.
2. **COPY → SHA-256 → DELETE SOURCE** — Quelle wird erst nach Schreiben, Publizieren und starker Prüfung des Ziels gelöscht.

Bei Unsicherheit oder Fehler bleibt die Quelle bestehen.

## Workspace

Aktive Seite, aktives Volume und Scan-ID werden im Backend-SQLite gespeichert. Refresh, Browser-Schließen, Löschen von Site-Daten oder Browser-Wechsel verlieren den maßgeblichen Workspace-Zustand nicht.

## Logging

Normale HTTP-Polling-Zeilen werden nicht in die Operator-Konsole geschrieben.

Journal:

```text
data/logs/diskshell.log
```

## Update

```powershell
git fetch origin
git reset --hard origin/main
npm run build
.\scripts\start-admin.ps1
```

Physical-Disk/Raw/Partition-Funktionen unter Windows benötigen ein als Administrator gestartetes Backend.

## Grenzen von 0.7.5

River Keeper ist local-only; Commander hat noch einen separaten Transfer-Manager; Teile der UI nutzen noch Polling; einige UI-Präferenzen liegen noch in localStorage; physisches Verschieben von Partitionsgrenzen und semantische Objekt-Suche in Fotos sind noch nicht implementiert.
