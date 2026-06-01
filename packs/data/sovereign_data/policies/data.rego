# Data Platform pack policy — storage protection + backup retention.
#
# NIST 800-53: SC-28 (Protection of Information at Rest), CP-9 (System
# Backup), SI-12 (Information Handling and Retention). The base bundle's
# encryption_at_rest rule covers a fixed set of storage-backed service
# types; this pack adds backup-retention enforcement the base cannot
# express and reaffirms encryption for the pack's own service types.
#
# All rules are inert when the data-specific input fields are absent.
package sovereign.pack.data

import rego.v1

_storage_services := {"managed-database", "vector-db"}

# SC-28: encryption at rest is mandatory for any classified data service.
deny contains sprintf(
	"SC-28: %q data service %q must set encryption_at_rest=true",
	[classification, input.instance_id],
) if {
	input.service_type in _storage_services
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	input.parameters.encryption_at_rest == false
}

# CP-9: a CUI/SECRET managed database must retain backups for >= 7 days.
deny contains sprintf(
	"CP-9: %q database %q backup_retention_days (%d) below the 7-day floor",
	[classification, input.instance_id, retention],
) if {
	input.service_type == "managed-database"
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	retention := input.parameters.backup_retention_days
	retention < 7
}

# SI-12: production (CUI/SECRET) databases must keep deletion protection.
deny contains sprintf(
	"SI-12: %q database %q must keep deletion_protection=true",
	[classification, input.instance_id],
) if {
	input.service_type == "managed-database"
	classification := input.parameters.classification
	classification in {"CUI", "SECRET"}
	input.parameters.deletion_protection == false
}

# Obligation: tag every provisioned data resource with its classification
# so downstream DLP / inventory tooling can enforce handling (AU-2/SI-12).
obligations contains "tag-data-classification" if {
	input.service_type in _storage_services
}
