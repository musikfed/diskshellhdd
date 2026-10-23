# DiskShell 0.7.5 — väljalaske juhend

## Põhimõte

Versioonis 0.7.5 on brauser **asendatav tööruumi vaade**, mitte protsesside või püsiva oleku omanik.

```text
UI/vaade      — asendatav
backend       — asendatav täitja
workspace     — püsiv
transfer job  — püsiv
andmed        — püsivad
```

### StreamCopy River Keeper

StreamCopy salvestab SQLite'i job'i, manifesti, lähte- ja sihtketta identiteedi, failide oleku, kinnitatud offset'id, SHA-256 checkpoint'id, progressi, hoiatused ning lease'i.

Pooleliolev fail kirjutatakse nimega `.dspart-<job>`. Pärast ketta eemaldamist või backendi restarti ei usaldata suvalist partial-faili lõppu. River Keeper leiab viimase kontrollitud checkpoint'i, võrdleb source/partial ploki räsi, lõikab kontrollimata saba ära ja jätkab turvalisest punktist.

### Split-brain kaitse

Püsival job'il on `lease_owner` ja `lease_expires_at`. Elus backend uuendab lease'i. Kui protsess kaob, võib uus backend job'i üle võtta alles pärast lease'i aegumist.

### Turvaline COPY

Kaks režiimi:

1. **COPY** — source jääb alles.
2. **COPY → SHA-256 → DELETE SOURCE** — source kustutatakse alles pärast target'i kirjutamist, avaldamist ja tugevat kontrolli.

Kahtluse või vea korral source'i ei kustutata.

## Workspace

Aktiivne leht, aktiivne volume ja scan id asuvad backendi SQLite'is. Refresh, brauseri sulgemine, site data kustutamine või teise brauseri kasutamine ei kustuta autoritatiivset tööruumi olekut.

## Logi

Tavaline HTTP polling ei täida operaatori konsooli.

Sündmuste logi:

```text
data/logs/diskshell.log
```

## Uuendamine

```powershell
git fetch origin
git reset --hard origin/main
npm run build
.\scripts\start-admin.ps1
```

Windowsi physical disk/raw/partition funktsioonid vajavad administraatori õigustes käivitatud backend'i.

## 0.7.5 piirangud

River Keeper on praegu local-only; Commander kasutab eraldi transfer manager'it; osa UI-st kasutab veel polling'ut; osa eelistusi on localStorage'is; partition boundary relocation ja semantiline objektide otsing fotodel ei ole veel valmis.
