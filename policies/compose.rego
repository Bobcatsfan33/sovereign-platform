# Top-level decision: combine base + pack + tenant layers.
# Every layer's denies surface in the result; the request is allowed
# only when every layer is empty.
#
# Layer evaluation order is informational — they all run; the
# semantic contract is "any deny rejects".
package sovereign

import rego.v1

import data.sovereign.base

denies contains msg if { some msg in base.deny }

denies contains msg if {
    some pack
    pack_denies := data.sovereign.pack[pack].deny
    some msg in pack_denies
}

denies contains msg if {
    some tenant
    tenant_denies := data.sovereign.tenant[tenant].deny
    some msg in tenant_denies
}

default allow := false
allow if count(denies) == 0

# Surface which top-level layers contributed denies so the audit log
# and the user-facing error message can cite the source. The broker
# uses this to construct the 403 problem-detail body.
matched_layers contains "base" if { count(base.deny) > 0 }
matched_layers contains sprintf("pack:%s", [pack]) if {
    some pack
    count(data.sovereign.pack[pack].deny) > 0
}
matched_layers contains sprintf("tenant:%s", [tenant]) if {
    some tenant
    count(data.sovereign.tenant[tenant].deny) > 0
}

# Aggregate obligations from every pack and tenant layer. Obligations are
# side-effects the broker MUST honour on allow (PII redaction, audit
# tagging, validator registration, ...). The base bundle emits none; packs
# and tenants do. Unlike denies, obligations do not reject the request —
# they are carried in the decision so the broker can enforce them.
obligations contains ob if {
    some pack
    some ob in data.sovereign.pack[pack].obligations
}

obligations contains ob if {
    some tenant
    some ob in data.sovereign.tenant[tenant].obligations
}

decision := {
    "allow": allow,
    "denies": sort([d | d := denies[_]]),
    "matched_layers": sort([l | l := matched_layers[_]]),
    "obligations": sort([o | o := obligations[_]]),
}
