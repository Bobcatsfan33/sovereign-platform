# Tests for the layered decision composition (base + pack + tenant).
package sovereign_test

import rego.v1

import data.sovereign

compliant_lb_input := {
    "actor": "alice@agency-x.gov",
    "tenant_id": "agency-x",
    "service_type": "sovereign-envoy-lb",
    "plan_id": "standard-regional",
    "parameters": {
        "region": "us-gov-west-1",
        "tls": true,
        "logging_enabled": true,
        "cipher_suites": ["TLS_AES_256_GCM_SHA384"],
    },
    "context": {
        "action": "provision",
        "require_mfa": true,
        "amr": ["pwd", "mfa"],
    },
}

test_compliant_request_allows if {
    decision := sovereign.decision with input as compliant_lb_input
    decision.allow == true
    count(decision.denies) == 0
}

test_request_with_tls_false_denies_with_sc8 if {
    bad := json.patch(compliant_lb_input, [{"op": "replace", "path": "/parameters/tls", "value": false}])
    decision := sovereign.decision with input as bad
    decision.allow == false
    some msg in decision.denies
    contains(msg, "SC-8")
    "base" in decision.matched_layers
}

test_request_in_commercial_region_denies if {
    bad := json.patch(compliant_lb_input, [{"op": "replace", "path": "/parameters/region", "value": "us-east-1"}])
    decision := sovereign.decision with input as bad
    decision.allow == false
    some msg in decision.denies
    contains(msg, "gov-region")
}

test_multiple_violations_accumulate if {
    bad := json.patch(compliant_lb_input, [
        {"op": "replace", "path": "/parameters/tls", "value": false},
        {"op": "replace", "path": "/parameters/region", "value": "us-east-1"},
        {"op": "remove", "path": "/parameters/logging_enabled"},
    ])
    decision := sovereign.decision with input as bad
    decision.allow == false
    count(decision.denies) >= 3
}

# Exercise every base aggregator line at once so policies/base/compose.rego
# reaches 100% coverage (each base.* sub-rule must contribute at least
# one deny somewhere in the test suite).
# Exercise sovereign.base.allow directly (top-level decision is the
# main entrypoint, but the per-layer 'allow' rule must be callable for
# diagnostics tooling that wants to check a single layer in isolation).
test_base_allow_when_compliant if {
    data.sovereign.base.allow == true with input as compliant_lb_input
}

test_base_allow_false_when_violation if {
    bad := json.patch(compliant_lb_input, [{"op": "replace", "path": "/parameters/tls", "value": false}])
    data.sovereign.base.allow == false with input as bad
}

test_every_base_aggregator_fires if {
    everything_wrong := {
        # tenancy.deny — invalid tenant id
        "tenant_id": "bad id!",
        "service_type": "rag-workspace",
        "plan_id": "small",
        "context": {
            "action": "provision",
            "require_mfa": true,
            "amr": ["pwd"],
        },
        "parameters": {
            # gov_region.deny + transmission.deny + audit_logging.deny +
            # crypto.deny + encryption_at_rest.deny via various missing /
            # non-compliant fields
            "region": "us-east-1",
            "tls": false,
            "logging_enabled": false,
            "encryption_at_rest": false,
            "cipher_suites": ["EXPORT_DES40_CBC_SHA"],
        },
        # allowed_services.deny — service not in the per-tenant list
        "approved_services": ["sovereign-envoy-lb"],
    }
    decision := sovereign.decision with input as everything_wrong
    decision.allow == false
    # All eight base sub-rules contributed.
    some t in decision.denies; contains(t, "AC-6")
    some i in decision.denies; contains(i, "IA-2(11)")
    some a in decision.denies; contains(a, "AU-2")
    some s in decision.denies; contains(s, "SC-8")
    some c in decision.denies; contains(c, "SC-13")
    some e in decision.denies; contains(e, "SC-28")
    some m in decision.denies; contains(m, "CM-7")
    some g in decision.denies; contains(g, "gov-region")
}

# ── Pack layer composition ────────────────────────────────────────────

# A test pack policy that always denies — exercises the pack layer of
# the decision composition.
test_pack_layer_deny_bubbles_up if {
    decision := sovereign.decision with input as compliant_lb_input
        with data.sovereign.pack as {"test-pack": {"deny": {"pack-test: rejected"}}}
    decision.allow == false
    "pack-test: rejected" in decision.denies
    "pack:test-pack" in decision.matched_layers
}

test_tenant_layer_deny_bubbles_up if {
    decision := sovereign.decision with input as compliant_lb_input
        with data.sovereign.tenant as {"agency-x": {"deny": {"tenant-rule: blocked"}}}
    decision.allow == false
    "tenant-rule: blocked" in decision.denies
    "tenant:agency-x" in decision.matched_layers
}

# ── Obligation aggregation ────────────────────────────────────────────

# A pack obligation surfaces in decision.obligations on an allowed request
# without affecting allow (obligations are side-effects, not denials).
test_pack_obligation_surfaces_on_allow if {
    decision := sovereign.decision with input as compliant_lb_input
        with data.sovereign.pack as {"ai": {"deny": set(), "obligations": {"pii-redaction"}}}
    decision.allow == true
    "pii-redaction" in decision.obligations
}

# Obligations from multiple layers (pack + tenant) are merged + sorted.
test_obligations_merge_across_layers if {
    decision := sovereign.decision with input as compliant_lb_input
        with data.sovereign.pack as {"ai": {"deny": set(), "obligations": {"audit-model-provenance"}}}
        with data.sovereign.tenant as {"agency-x": {"deny": set(), "obligations": {"tenant-extra"}}}
    decision.allow == true
    decision.obligations == ["audit-model-provenance", "tenant-extra"]
}

# A compliant request with no obligation-bearing layers has an empty list.
test_no_obligations_when_none_emitted if {
    decision := sovereign.decision with input as compliant_lb_input
    decision.obligations == []
}
