#!/usr/bin/env bash
# Post a couple of sample provisioning requests to a locally-running
# broker stack so dashboards / audit trail / metering have data to show.
#
# Requires: a running 'make up' stack and curl. jq is used to pretty-print
# if present, otherwise raw JSON.
set -euo pipefail

BROKER="${BROKER:-http://localhost:8080}"
USER="${BROKER_USERNAME:-broker}"
PASS="${BROKER_PASSWORD:-broker}"

pretty() {
    if command -v jq >/dev/null 2>&1; then
        jq .
    else
        cat
    fi
}

provision() {
    local instance_id="$1"
    local plan="$2"
    local port="$3"
    local upstream="$4"
    echo "── provisioning $instance_id (plan=$plan, port=$port, upstream=$upstream) ──"
    curl -sS -u "$USER:$PASS" -X PUT \
        "$BROKER/v2/service_instances/$instance_id" \
        -H 'Content-Type: application/json' \
        -d "{
            \"service_id\":\"sovereign-envoy-lb\",
            \"plan_id\":\"$plan\",
            \"organization_guid\":\"demo-org\",
            \"space_guid\":\"demo-space\",
            \"parameters\":{
                \"region\":\"us-east-1\",
                \"listeners\":[{\"name\":\"http\",\"port\":$port,\"protocol\":\"HTTP\"}],
                \"routes\":[{\"host\":\"app.local\",\"prefix\":\"/\",\"cluster\":\"app\"}],
                \"clusters\":[{\"name\":\"app\",\"endpoints\":[\"$upstream\"]}]
            }
        }" | pretty
    echo
}

bind() {
    local instance_id="$1"
    local binding_id="$2"
    echo "── binding $binding_id to $instance_id ──"
    curl -sS -u "$USER:$PASS" -X PUT \
        "$BROKER/v2/service_instances/$instance_id/service_bindings/$binding_id" \
        -H 'Content-Type: application/json' \
        -d '{}' | pretty
    echo
}

provision demo-lb       standard-regional 8088 host.docker.internal:3000
provision demo-multi    multi-region      8089 host.docker.internal:3001
bind      demo-lb       demo-binding
echo "── catalog ──"
curl -sS -u "$USER:$PASS" "$BROKER/v2/catalog" | pretty
