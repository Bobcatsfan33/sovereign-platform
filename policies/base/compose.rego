# Aggregates every base.* sub-policy's deny rules into a single
# sovereign.base.deny set. Adding a new base rule means dropping a
# file under policies/base/<name>.rego AND adding one import + one
# aggregator line here.
package sovereign.base

import rego.v1

import data.sovereign.base.allowed_services
import data.sovereign.base.audit_logging
import data.sovereign.base.crypto
import data.sovereign.base.encryption_at_rest
import data.sovereign.base.gov_region
import data.sovereign.base.tenancy
import data.sovereign.base.transmission

deny contains msg if { some msg in tenancy.deny }
deny contains msg if { some msg in audit_logging.deny }
deny contains msg if { some msg in transmission.deny }
deny contains msg if { some msg in crypto.deny }
deny contains msg if { some msg in encryption_at_rest.deny }
deny contains msg if { some msg in allowed_services.deny }
deny contains msg if { some msg in gov_region.deny }

default allow := false
allow if count(deny) == 0
