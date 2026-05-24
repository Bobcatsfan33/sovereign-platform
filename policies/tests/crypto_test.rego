package sovereign.base.crypto_test

import rego.v1

import data.sovereign.base.crypto

test_fips_approved_suites_allow if {
    count(crypto.deny) == 0 with input as {
        "parameters": {
            "cipher_suites": [
                "TLS_AES_256_GCM_SHA384",
                "TLS_AES_128_GCM_SHA256",
            ],
        },
    }
}

test_legacy_rc4_denies if {
    "SC-13: cipher suite \"TLS_RSA_WITH_RC4_128_SHA\" is not FIPS-approved" in crypto.deny with input as {
        "parameters": {"cipher_suites": ["TLS_RSA_WITH_RC4_128_SHA"]},
    }
}

test_no_cipher_param_allows if {
    # Crypto policy is opt-in: services that don't declare cipher_suites
    # are not subject to this rule (TLS itself is enforced by SC-8).
    count(crypto.deny) == 0 with input as {"parameters": {}}
}

test_mixed_approved_and_legacy_denies_only_legacy if {
    denies := crypto.deny with input as {
        "parameters": {
            "cipher_suites": [
                "TLS_AES_256_GCM_SHA384",
                "EXPORT_DES40_CBC_SHA",
            ],
        },
    }
    count(denies) == 1
    some msg in denies
    contains(msg, "EXPORT_DES40_CBC_SHA")
}
