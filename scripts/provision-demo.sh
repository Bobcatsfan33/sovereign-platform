#!/usr/bin/env bash
set -euo pipefail
curl -sS -X PUT http://localhost:8080/v2/service_instances/demo-lb \
  -H 'Content-Type: application/json' \
  -d '{"service_id":"sovereign-envoy-lb","plan_id":"standard-regional","organization_guid":"demo-org","space_guid":"demo-space","parameters":{"region":"us-east-1","listeners":[{"name":"http","port":8088,"protocol":"HTTP"}],"routes":[{"host":"app.local","prefix":"/","cluster":"app"}],"clusters":[{"name":"app","endpoints":["host.docker.internal:3000"]}]}}' | jq .
