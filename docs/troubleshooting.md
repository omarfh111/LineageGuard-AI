# Diagnostic et récupération

## Contrôle de base

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8000/api/v1/health
docker compose logs backend --tail 200
```

Les services `backend` et `frontend` doivent être `healthy`. Après une modification de `.env` ou du code :

```powershell
docker compose up --build -d
```

## Docker Desktop ne démarre pas

Vérifier que Docker Desktop affiche `Engine running`. Si le message indique que la virtualisation n'est pas détectée, activer la virtualisation matérielle dans le BIOS/UEFI ou demander l'aide de l'administrateur IT. Docker Desktop en mode Linux utilise WSL 2 ; les conteneurs Windows ne sont pas nécessaires à ce projet.

## DataHub ou analyse indisponible

| Symptôme | Cause probable | Action |
|---|---|---|
| `DATAHUB_GMS_URL is not configured` | variable absente | configurer l'URL appropriée au mode Docker/local |
| `DATAHUB_GMS_TOKEN is not configured` | URL non locale sans token | créer un token DataHub et le mettre seulement dans `.env` |
| DataHub ne répond pas sur `9002` | Quickstart arrêté | exécuter `.\scripts\start-datahub.ps1` |
| Actif/schéma absent | jeu exemple non chargé | exécuter `.\scripts\load-showcase-data.ps1` |

Dans Docker, l'adresse GMS locale est `http://host.docker.internal:8080`. Hors Docker, elle est `http://localhost:8080`.

## Critique NVIDIA échoue

Ne copiez pas la clé dans les logs. Vérifier uniquement les noms de variables dans `.env` :

```env
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_CRITIC_MODEL=z-ai/glm-5.2
NVIDIA_TIMEOUT_SECONDS=90
```

Causes possibles : clé révoquée, modèle non disponible dans le compte, quota de prototype atteint, délai réseau ou réponse non conforme. Après correction du fichier, recréer le backend :

```powershell
docker compose up -d --force-recreate backend
```

La critique est non bloquante : elle ne peut ni changer le plan ni écrire dans DataHub.

## OpenAI ou Groq en erreur

Un `ERROR` ne devient jamais un `PASS` par défaut. La décision devient `AWAITING_HUMAN` si un seul juge est indisponible, ou `BLOCKED` si les deux le sont.

1. Lire les derniers logs backend sans exposer les clés :

   ```powershell
   docker compose logs backend --tail 200
   ```

2. Vérifier le modèle configuré dans la console du fournisseur, sa clé, ses limites et son état.
3. Attendre et relancer une seule fois en cas de limite ou surcharge ; `JUDGE_MAX_RETRIES` borne déjà les tentatives automatiques.
4. Réduire la profondeur de lineage ou le périmètre si l'analyse contient de très nombreux actifs. Le paquet de jugement est déjà compacté et les métadonnées GraphQL brutes sont exclues.

Groq utilise un JSON Schema strict pour le verdict. Cette contrainte évite les réponses mal formées ; elle ne doit pas être supprimée pour masquer un problème de qualité.

## `NEEDS_REPAIR` malgré des clés valides

C'est une décision métier/sécurité, pas une panne technique. Lire :

- les `critical_errors` ;
- les `repair_instructions` ;
- les `audit_rationale` ;
- la formule de risque, les preuves et les limites de métadonnées.

Corriger le changement ou le plan puis créer une nouvelle analyse. Ne choisissez pas un modèle plus permissif pour forcer le double PASS.

## Write-back refusé

| Message / statut | Signification |
|---|---|
| `DATAHUB_WRITEBACK_ENABLED is false` | protection normale : aucune écriture autorisée |
| `Unknown server-owned judging run` | `run_id` absent ou non persistant |
| erreur 422 durant `prepare` | Gate 0 ou double PASS absent |
| `FAILED` | appel document DataHub échoué après persistence de l'audit |

Inspecter la proposition et l'audit :

```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/writebacks/<run_id>"
Invoke-RestMethod "http://localhost:8000/api/v1/writebacks/<run_id>/audit"
```

Ne supprimez pas le volume Docker si vous devez conserver l'historique SQLite :

```powershell
docker compose down
```

Éviter `docker compose down -v`, qui supprime aussi le volume persistant de l'application.
