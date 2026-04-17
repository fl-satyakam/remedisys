# Remedisys production image.
#
# Layered on top of the official frappe/erpnext image so we inherit:
#   - Frappe runtime (python + node + bench)
#   - ERPNext
#   - apt dependencies (wkhtmltopdf, etc.)
#
# We add Healthcare (Marley Health) and this app. The image is then
# mounted at runtime by docker-compose alongside MariaDB + Redis.

ARG FRAPPE_VERSION=v16

FROM frappe/erpnext:${FRAPPE_VERSION}

USER frappe
WORKDIR /home/frappe/frappe-bench

# Healthcare comes from the Marley Health repo (frappe/health).
# Keep the branch aligned with FRAPPE_VERSION to avoid schema drift.
ARG HEALTHCARE_BRANCH=version-16
RUN bench get-app --branch ${HEALTHCARE_BRANCH} \
    healthcare https://github.com/frappe/health

# Install Remedisys from the build context so the image carries the
# commit under test — no runtime `git clone` on the VM.
COPY --chown=frappe:frappe . apps/remedisys/
RUN bench setup requirements --app remedisys

# Build JS/CSS bundles at image time so we don't pay for it on boot.
RUN bench build --app remedisys
