## Stage 1 — build the SPA bundle ─────────────────────────────────────
# Phase 5.4 STIG hardening: pinned node + nginx tags, non-root nginx
# user, OCI labels, healthcheck, hardened response headers (nginx.conf).
FROM node:22.13.0-alpine AS build
WORKDIR /portal

# Cache deps independent of source changes.
COPY apps/portal/package.json apps/portal/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY apps/portal/ ./
ARG VITE_BROKER_URL=
ARG VITE_AUDIT_URL=
ENV VITE_BROKER_URL=${VITE_BROKER_URL}
ENV VITE_AUDIT_URL=${VITE_AUDIT_URL}
# VITE_DEV_BEARER_TOKEN is inlined into the SPA bundle by Vite at build
# time (a dev convenience; production auth is OIDC). Pass it through a
# BuildKit secret instead of ARG/ENV so the value never persists in an
# image layer or metadata. Falls back to the dev default when no secret
# is mounted (e.g. CI), so the build is unchanged without one.
RUN --mount=type=secret,id=vite_dev_bearer_token \
    VITE_DEV_BEARER_TOKEN="$(cat /run/secrets/vite_dev_bearer_token 2>/dev/null || echo dev-token)" \
    npm run build

## Stage 2 — serve the static bundle ──────────────────────────────────
# `nginx:stable-alpine` ships an `nginx` non-root user but the default
# config still binds :80 (privileged). We rebind to :8080 inside the
# container and let the orchestrator publish on :8088 externally —
# matches docker-compose port mapping.
#
# Bumped from 1.27.4 → 1.30.3 to remediate CVE-2026-42945 ("NGINX Rift",
# CVSS 9.2 Critical — heap buffer overflow in ngx_http_rewrite_module,
# affects all versions 0.6.27–1.30.0). Fixed in 1.30.1+/1.31.0+.
FROM nginx:1.30.3-alpine

LABEL org.opencontainers.image.title="sovereign-platform-portal" \
      org.opencontainers.image.description="Sovereign Platform self-service catalog SPA (React/TS)" \
      org.opencontainers.image.source="https://github.com/Bobcatsfan33/sovereign-platform" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.vendor="Sovereign Platform"

# Refresh Alpine packages so the runtime layer picks up the latest
# security patches available at build time. The base image bump to
# 1.30.3-alpine should resolve the libxml2 CVE-2026-6732 fix as well
# (newer Alpine ships 2.13.9-r1+ on x86_64). `--update-cache` makes
# the cache key change per build so buildx's gha cache cannot replay
# a stale apk layer past a published fix.
RUN apk --no-cache --update-cache upgrade

COPY apps/portal/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /portal/dist /usr/share/nginx/html

# Make nginx's runtime paths writable by the unprivileged user.
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /var/log/nginx \
 && touch /var/run/nginx.pid \
 && chown nginx:nginx /var/run/nginx.pid \
 # Drop the default privileged listener and run on 8080 inside the container.
 && sed -i 's/listen 80;/listen 8080;/' /etc/nginx/conf.d/default.conf

USER nginx
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O- http://localhost:8080/ > /dev/null 2>&1 || exit 1
