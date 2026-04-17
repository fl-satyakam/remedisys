#!/usr/bin/env bash
# Manual deploy path for Remedisys → GCP (asia-south1).
#
# Normal flow: push to `main` and GitHub Actions (.github/workflows/deploy.yaml)
# builds, pushes, and rolls forward automatically. Use this script only when
# you need to ship uncommitted local changes or CI is broken.
#
# See docs/deployment/GCP_DEPLOYMENT.md for the full topology.
#
# Usage:
#   ./scripts/deploy-gcp.sh              # build + push + migrate (local tag)
#   TAG=manual ./scripts/deploy-gcp.sh   # custom image tag
#   SKIP_BUILD=1 ./scripts/deploy-gcp.sh # just run migrate on the VM
#
# Auth (one-time):
#   gcloud auth login
#   gcloud auth configure-docker asia-south1-docker.pkg.dev

set -euo pipefail

# Strip proxy env Frappe devs often have set — see memory/feedback_gcloud_proxy_env.md
unset CLOUDSDK_PROXY_TYPE || true

PROJECT="${PROJECT:-mongodb-460409}"
REGION="${REGION:-asia-south1}"
ZONE="${ZONE:-${REGION}-a}"
REPO="${REPO:-remedisys}"
IMAGE_NAME="${IMAGE_NAME:-custom}"
VM_NAME="${VM_NAME:-remedisys-backend}"
SITE_NAME="${SITE_NAME:-remedisys.34-180-31-224.nip.io}"
TAG="${TAG:-manual-$(date +%Y%m%d-%H%M%S)}"
SKIP_BUILD="${SKIP_BUILD:-0}"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${IMAGE_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log() { printf '\033[1;36m[deploy]\033[0m %s\n' "$*"; }

if [[ "$SKIP_BUILD" != "1" ]]; then
	log "building ${IMAGE}:${TAG}"
	docker build -t "${IMAGE}:${TAG}" -t "${IMAGE}:latest" "$REPO_ROOT"

	log "pushing to Artifact Registry"
	docker push "${IMAGE}:${TAG}"
	docker push "${IMAGE}:latest"
fi

log "rolling forward backend on ${VM_NAME}"
gcloud compute ssh "$VM_NAME" --zone="$ZONE" --project="$PROJECT" --command="
	set -euo pipefail
	cd ~/remedisys-deploy
	sudo docker compose pull backend
	sudo docker compose up -d --remove-orphans backend
	sudo docker compose exec -T backend bench --site '${SITE_NAME}' migrate
	sudo docker compose exec -T backend bench --site '${SITE_NAME}' clear-cache
"

log "smoke-testing https://${SITE_NAME}/api/method/ping"
for i in 1 2 3 4 5 6; do
	STATUS=$(curl -s -o /dev/null -w "%{http_code}" "https://${SITE_NAME}/api/method/ping" || echo 0)
	if [[ "$STATUS" == "200" ]]; then
		log "✓ site healthy — deploy ${TAG} live"
		exit 0
	fi
	log "attempt $i: HTTP $STATUS, retrying in 10s"
	sleep 10
done

log "✗ smoke test failed — check container logs: gcloud compute ssh ${VM_NAME} --zone=${ZONE} -- 'sudo docker compose -f ~/remedisys-deploy/docker-compose.yaml logs --tail=100 backend'"
exit 1
