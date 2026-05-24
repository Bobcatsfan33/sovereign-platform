# NIST 800-53 SC-13 — Cryptographic Protection.
# Only FIPS 140-2 / 140-3 approved cipher suites are allowed on
# any service that declares cipher_suites.
package sovereign.base.crypto

import rego.v1

# Subset of TLS 1.3 + 1.2 suites currently on the FIPS-approved list.
fips_approved := {
    "TLS_AES_256_GCM_SHA384",
    "TLS_AES_128_GCM_SHA256",
    "TLS_CHACHA20_POLY1305_SHA256",
    "TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384",
    "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256",
    "TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384",
    "TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256",
}

deny contains sprintf(
    "SC-13: cipher suite %q is not FIPS-approved",
    [suite],
) if {
    some suite in input.parameters.cipher_suites
    not fips_approved[suite]
}
