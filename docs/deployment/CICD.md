# Remedisys — CI/CD

Companion to [GCP_DEPLOYMENT.md](GCP_DEPLOYMENT.md). That doc covers the
runtime topology; this one covers what happens between `git push` and a
running container.

## Workflows

Two files under `.github/workflows/`:

| File            | Triggers                          | Purpose                                                  |
|-----------------|-----------------------------------|----------------------------------------------------------|
| `ci.yaml`       | PR to `main`, push to `main`      | Lint + install smoke test. Every PR runs this.           |
| `deploy.yaml`   | Push to `main`, `workflow_dispatch` | Build image, push to Artifact Registry, roll forward on the GCE VM. |

Concurrency is scoped per-ref: a second push to the same branch cancels
the earlier CI run (`cancel-in-progress: true`) but queues deploys
(`cancel-in-progress: false`) so we never have two deploys racing on the
same VM.

## `ci.yaml` — what each job does

### `lint`
Runs `pre-commit run --all-files`. That chain is configured in
`.pre-commit-config.yaml` at the repo root and today covers ruff
(Python), prettier (JS/CSS/MD), and eslint. Adding a new hook there
automatically gates PRs — no workflow change needed.

### `install-smoke-test`
Spins up MariaDB 10.6 and Redis 7 as service containers, runs
`bench init`, pulls `erpnext` and `healthcare` (Marley Health) at
`version-16`, copies this checkout into `apps/remedisys`, then:

1. `bench new-site --install-app` for all three apps
2. `bench migrate` (exercises `after_install` + `after_migrate` hooks,
   including `setup_cleanup.hide_unused_workspaces`)
3. `bench list-apps` as a final sanity check

**This is why it matters**: a lot of Frappe bugs only show up during
install/migrate. Running the full install on every PR catches broken
fixtures, bad hook imports, and migrations that don't apply cleanly.

Takes ~6-8 minutes. It's informational only — not a deploy gate —
because the lint job is the faster signal and we don't want to block
deploys on a transient MariaDB flake.

## `deploy.yaml` — what each job does

### `wait-for-ci`
Uses `lewagon/wait-on-check-action` to block until the `Lint` job on
the same commit finishes green. The install-smoke-test is **not**
waited on (see above). If lint fails, deploy never starts.

### `build-and-push`
1. `google-github-actions/auth` using `GCP_SA_KEY` JSON
2. `gcloud auth configure-docker` for `asia-south1-docker.pkg.dev`
3. Buildx with **registry cache** at
   `${image}:buildcache` — second+ builds are ~2-3x faster because
   `bench get-app healthcare` and `pip install` layers are cached
4. Pushes two tags: `:<commit-sha>` (pinnable) and `:latest`
   (convenience)

### `deploy`
SSHes into the GCE VM (`appleboy/ssh-action`) and runs:

```bash
cd ~/remedisys-deploy
docker compose pull backend
docker compose up -d --remove-orphans backend
docker compose exec -T backend bench --site $SITE migrate
docker compose exec -T backend bench --site $SITE clear-cache
```

Gated on GitHub's `production` environment — if you've configured
required reviewers on that environment in repo settings, the deploy
pauses for approval here.

### Smoke test
Polls `https://$SITE_NAME/api/method/ping` six times at 10s intervals.
Returns 200 within 60s or the job fails. Failure **doesn't roll back**
— it just flags the deploy as red so a human can investigate. The
previous image is still on the VM if a manual rollback is needed
(see GCP_DEPLOYMENT.md → Rollback).

## Required secrets

All five are set under **Settings → Secrets and variables → Actions**:

| Secret         | Used by                                  |
|----------------|------------------------------------------|
| `GCP_SA_KEY`   | `build-and-push` → GCP auth              |
| `GCE_HOST`     | `deploy` → SSH target                    |
| `GCE_SSH_USER` | `deploy` → SSH user                      |
| `GCE_SSH_KEY`  | `deploy` → SSH private key               |
| `SITE_NAME`    | `deploy` → `bench --site <name>` target  |

Generation commands live in
[GCP_DEPLOYMENT.md](GCP_DEPLOYMENT.md#one-time-gcp-setup).

## Rotating a secret

1. Generate the new value (e.g. a new service account key).
2. **Add** it to GitHub as a new secret name (e.g. `GCP_SA_KEY_V2`).
3. Flip the workflow to reference the new name in one PR.
4. After the PR merges and one deploy succeeds, delete the old secret.

Never overwrite a secret in place during a live deploy — in-flight
jobs continue with the old value and half-deployed state is the worst
case.

## Testing the pipeline locally

### The lint job
```bash
pip install pre-commit
pre-commit run --all-files
```

Runs the same checks CI does. Fix everything locally before pushing.

### The install smoke test
You can mimic it with Docker:

```bash
docker run --rm -it \
    -v "$PWD":/home/frappe/apps/remedisys \
    -w /home/frappe \
    frappe/erpnext:v16 bash -lc '
        cd frappe-bench &&
        bench get-app --branch version-16 healthcare https://github.com/frappe/health &&
        cp -r /home/frappe/apps/remedisys apps/remedisys &&
        bench new-site ci.localhost \
            --admin-password admin \
            --install-app erpnext \
            --install-app healthcare \
            --install-app remedisys &&
        bench --site ci.localhost migrate
    '
```

Slower than CI (no service containers) but catches the same class of
issues.

### The deploy job
Don't run end-to-end locally — it mutates the prod VM. Instead:

1. **Dry-run the build**: `docker build -t remedisys-test .`
2. **Dry-run compose**: on the VM, `docker compose config` to validate.
3. **Manual deploy**: the shell commands from
   [GCP_DEPLOYMENT.md → Manual deploy](GCP_DEPLOYMENT.md#manual-deploy-bypass-ci).

## Things that have caught us before

- **Healthcare branch drift**: when Marley Health cuts a new branch the
  pinned `--branch version-16` in both `Dockerfile` and `ci.yaml` must
  agree. Mismatch shows up as a migrate failure in the smoke test, not
  at build time.
- **Buildx cache bloat**: registry cache at `:buildcache` grows
  unbounded. If pulls start timing out, delete the tag in Artifact
  Registry — the next build rebuilds cold (~15 min) but subsequent
  builds are fast again.
- **`concurrency: cancel-in-progress: true` on CI**: rebasing during
  review cancels the in-flight lint job, which looks like a red X in
  GitHub's UI. That's expected. Check the *latest* run, not the
  cancelled one.
