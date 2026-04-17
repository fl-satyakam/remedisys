# Remedisys — GCP Deployment

Describes the production topology, how a change reaches prod, and the
manual levers available when CI isn't sufficient.

## Current production topology

```
                    Internet
                       │
                       ▼
       ┌─────────────────────────────┐
       │  Cloud Run                  │
       │  med-note-helper (SPA)      │   asia-south1
       │  378176154078.*.run.app     │
       └──────────────┬──────────────┘
                      │ /api/* proxy
                      ▼
       ┌─────────────────────────────┐
       │  GCE VM remedisys-backend   │
       │  34.180.31.224              │   e2-standard-2
       │  nginx + docker-compose     │
       └──────────────┬──────────────┘
                      │ docker network
                      ▼
      ┌──────────────────────────────┐
      │  Frappe/ERPNext container    │
      │  image: asia-south1-docker.  │
      │    pkg.dev/mongodb-460409/   │
      │    remedisys/custom:<sha>    │
      │  site: remedisys.34-180-31-  │
      │    224.nip.io                │
      └──────┬────────────┬──────────┘
             │            │
         MariaDB       Redis
        (container)  (container)
```

- **GCP project**: `mongodb-460409`
- **Region**: `asia-south1`
- **Artifact Registry repo**: `remedisys` (Docker)
- **Image**: `asia-south1-docker.pkg.dev/mongodb-460409/remedisys/custom`

The `vex-gateway` VM (34.180.13.69) is unrelated and slated for removal
— see current-state assessment.

## The image

Built from `Dockerfile` at the repo root. Layers:

1. `frappe/erpnext:v16` — Frappe + ERPNext + system deps
2. `bench get-app healthcare` — Marley Health
3. `COPY . apps/remedisys/` — this commit
4. `bench setup requirements --app remedisys`
5. `bench build --app remedisys` — asset bundle

The Dockerfile is version-controlled; CI builds it on every push to
`main`. Image tags: `<commit-sha>` + `latest`.

## The deploy flow (automated)

Triggered by a push to `main`:

1. **Gate on CI** — `deploy.yaml` blocks until the `Lint` job on the
   same commit passes. The install smoke test is informational on PR
   and not a deploy gate (runs on every PR anyway).
2. **Build & push** — `docker/build-push-action` with Buildx cache
   tagged `:buildcache` for fast incremental rebuilds.
3. **Deploy** — SSH into the GCE VM, `docker compose pull backend` +
   `up -d`, then `bench migrate` and `clear-cache` inside the running
   container.
4. **Smoke test** — CI polls `https://<site>/api/method/ping` for
   HTTP 200 with a 60-second budget. Failure fails the job but the
   image is already in place; see *Rollback* below.

## Required GitHub secrets

Set under **Settings → Secrets and variables → Actions**:

| Secret         | What                                              |
|----------------|---------------------------------------------------|
| `GCP_SA_KEY`   | JSON key for a service account with `roles/artifactregistry.writer` on `projects/mongodb-460409` |
| `GCE_HOST`     | VM IP or hostname (e.g. `34.180.31.224`)          |
| `GCE_SSH_USER` | SSH user (typically `ubuntu` or project email)    |
| `GCE_SSH_KEY`  | Private key matching a public key in the VM's `~/.ssh/authorized_keys` |
| `SITE_NAME`    | Frappe site, e.g. `remedisys.34-180-31-224.nip.io` |

The `production` environment (in workflow `environment: production`)
should be configured with **required reviewers** in repo settings so
deploys pause for approval.

## One-time GCP setup

If you're bringing up a fresh project:

```bash
# Enable required services
gcloud services enable \
    artifactregistry.googleapis.com \
    compute.googleapis.com \
    run.googleapis.com \
    --project=mongodb-460409

# Create the Artifact Registry repo
gcloud artifacts repositories create remedisys \
    --repository-format=docker \
    --location=asia-south1 \
    --project=mongodb-460409

# Service account for CI
gcloud iam service-accounts create remedisys-deployer \
    --display-name="Remedisys GitHub Actions deployer"

gcloud projects add-iam-policy-binding mongodb-460409 \
    --member="serviceAccount:remedisys-deployer@mongodb-460409.iam.gserviceaccount.com" \
    --role="roles/artifactregistry.writer"

gcloud iam service-accounts keys create key.json \
    --iam-account="remedisys-deployer@mongodb-460409.iam.gserviceaccount.com"
# Paste key.json contents into GitHub secret GCP_SA_KEY; delete the local file.
```

## Manual deploy (bypass CI)

Rarely needed. From a machine authed as `satyakam.singhal@recur.club`:

```bash
gcloud auth configure-docker asia-south1-docker.pkg.dev

docker build -t asia-south1-docker.pkg.dev/mongodb-460409/remedisys/custom:manual .
docker push asia-south1-docker.pkg.dev/mongodb-460409/remedisys/custom:manual

gcloud compute ssh remedisys-backend --zone=asia-south1-a --command="
  cd ~/remedisys-deploy
  sudo docker compose pull backend
  sudo docker compose up -d --remove-orphans backend
  sudo docker compose exec -T backend bench --site remedisys.34-180-31-224.nip.io migrate
"
```

## Rollback

The previous good image is always on the VM. Fastest path:

```bash
gcloud compute ssh remedisys-backend --zone=asia-south1-a --command="
  cd ~/remedisys-deploy
  # inspect recent images
  sudo docker image ls asia-south1-docker.pkg.dev/mongodb-460409/remedisys/custom

  # pin the previous sha in docker-compose.yaml and restart
  sudo sed -i 's|custom:.*|custom:<previous-sha>|' docker-compose.yaml
  sudo docker compose up -d backend
"
```

Data rollback (MariaDB) is not automated. Restore from the nightly
snapshot (see **Backups** below) if a migration corrupted state.

## Backups

- **MariaDB**: nightly `mysqldump` cron on the VM → `/home/frappe/backups/` → synced to `gs://mongodb-460409-remedisys-backups` every morning.
- **Redis**: ephemeral; no backup needed (it's cache + queue).
- **Site files**: `sites/remedisys.*/public/files` is volume-mounted; nightly `gsutil rsync` to GCS.

Retention: 30 days of nightly dumps, 12 months of weeklies.

## Site configuration

Sensitive values (DB password, OpenAI key, encryption key) live in
`sites/<site>/site_config.json` **on the VM**. They are not baked into
the image. The file is generated once by `bench new-site` and edited in
place.

Any secret rotation:

```bash
gcloud compute ssh remedisys-backend --zone=asia-south1-a --command="
  cd ~/remedisys-deploy
  sudo docker compose exec backend bench --site <site> set-config openai_api_key 'sk-...'
  sudo docker compose restart backend
"
```

## Common failure modes

| Symptom                           | Likely cause                    | Fix |
|-----------------------------------|---------------------------------|-----|
| `bench migrate` hangs             | Redis not reachable             | `docker compose restart redis-cache redis-queue` |
| 502 from nginx                    | Backend container crash         | `docker compose logs backend --tail=200` |
| Static assets 404                 | `bench build` skipped           | Image was built without assets; rebuild image |
| Login page loops                  | Session cookie `Secure` flag under http | Ensure site is served over HTTPS; check nginx config |
| `after_migrate` fails             | New code expects a field that isn't migrated yet | Trace in `docker compose logs backend`, hotfix in a PR |
