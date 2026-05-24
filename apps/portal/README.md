# Sovereign Platform — Portal

Phase 4 of the roadmap: a static React/TS SPA that lets non-technical
program managers browse the service catalog, provision resources with a
guided wizard, watch their running instances, and review compliance
posture — all without touching the OSB API directly.

## Stack

- **React 19** + TypeScript (strict)
- **Vite 6** for dev + build
- **Tailwind CSS v4** for styling (utility-first; no design-system dependency)
- **React Router 7** for client-side routing
- **TanStack Query 5** for broker / audit-service data fetching
- **Vitest** + **@testing-library/react** + **jest-axe** for unit and
  accessibility tests (gated in CI; zero `axe-core` violations required)

## Pages

| Route | Page | Source of truth |
| --- | --- | --- |
| `/` | Catalog browse — pack-grouped service cards | `/v2/catalog` + the catalog DB |
| `/provision/:serviceId` | Multi-step provisioning wizard with policy pre-check | broker `/v2/policy/check`, then `PUT /v2/service_instances/{id}` |
| `/instances` | Live instance dashboard | broker `/v2/instances` (tenant-scoped) |
| `/compliance` | Compliance dashboard — posture, recent violations, audit log | audit-service `/events` |

## Dev

```bash
cd apps/portal
npm ci
npm run dev           # http://localhost:5173, proxies /v2 to broker on :8080
npm run typecheck
npm run lint
npm test
npm run build         # static bundle in dist/
```

The dev server proxies `/v2/*` to the broker and `/audit/*` to the
audit-service, so the SPA never needs CORS in dev. In production the
broker has CORS enabled with an explicit allow-list of portal origins.

## Accessibility

Every page-level test includes a `jest-axe` audit. CI fails on any
violation. The `Layout` component renders a skip-to-main-content link,
every interactive control has an accessible name, color contrast
exceeds AA targets, and `prefers-reduced-motion` is honoured.

## Auth

A simple login screen accepts either:

- a JWT bearer token (production — issued by the agency IdP per Phase 3.5),
- an OSB Basic username/password pair, or
- the dev-mode `DEV_BEARER_TOKEN` (one-click for local docker-compose).

The chosen credential is held in `sessionStorage` for the tab and sent
on every request via `Authorization: Bearer …` or `Authorization: Basic …`
depending on the source.
