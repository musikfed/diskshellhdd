# DiskShell 0.7.5 — Guide de version

## Principe

Dans 0.7.5, le navigateur est une **vue remplaçable** de l’espace de travail. Il n’est pas propriétaire des tâches ni de l’état durable.

```text
vue UI        — remplaçable
backend       — exécuteur remplaçable
workspace     — persistant
transfer job  — persistant
data          — persistantes
```

### StreamCopy River Keeper

StreamCopy conserve dans SQLite le job, le manifeste, l’identité des volumes, l’état de chaque fichier, les offsets confirmés, les checkpoints SHA-256, la progression, les avertissements et le lease.

Un fichier incomplet est écrit sous la forme `.dspart-<job>`. Après une déconnexion de disque ou un redémarrage du backend, River Keeper revient au dernier checkpoint vérifié, contrôle à nouveau les blocs source/partial, supprime la fin non vérifiée et reprend depuis le point sûr.

### Protection split-brain

Chaque job persistant possède `lease_owner` et `lease_expires_at`. Un backend actif renouvelle le lease. Après sa disparition, un autre backend peut récupérer le job lorsque le lease expire.

### COPY sûr

Deux modes:

1. **COPY** — la source reste intacte.
2. **COPY → SHA-256 → DELETE SOURCE** — suppression de la source seulement après écriture, publication et vérification forte de la cible.

En cas de doute ou d’erreur, la source n’est pas supprimée.

## Workspace et navigateur

La page active, le volume actif et le scan id sont stockés côté backend dans SQLite. Un refresh, la fermeture du navigateur, la suppression des cookies/localStorage ou l’ouverture d’un autre navigateur ne définissent donc pas l’état autoritaire.

## Journal

Le trafic HTTP normal n’encombre pas la console.

Journal opérateur:

```text
data/logs/diskshell.log
```

## Mise à jour

```powershell
git fetch origin
git reset --hard origin/main
npm run build
.\scripts\start-admin.ps1
```

Les fonctions physical disk/raw/partition sous Windows nécessitent un backend lancé en Administrateur.

## Limites 0.7.5

River Keeper est local-only; Commander possède encore son propre moteur de transfert; plusieurs écrans utilisent encore du polling; certaines préférences UI sont encore dans localStorage; le déplacement physique des frontières de partition et la recherche sémantique d’objets dans les photos restent à développer.
