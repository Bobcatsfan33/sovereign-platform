package sovereign.pack.finops_test

import rego.v1

import data.sovereign.pack.finops

test_hard_budget_over_denies if {
	some msg in finops.deny with input as {
		"tenant_id": "cade2",
		"finops": {"enforcement": "hard", "current_spend": 1200, "budget_limit": 1000},
	}
	contains(msg, "SA-2")
	contains(msg, "cade2")
}

test_hard_budget_under_allows if {
	count(finops.deny) == 0 with input as {
		"tenant_id": "cade2",
		"finops": {"enforcement": "hard", "current_spend": 500, "budget_limit": 1000},
	}
}

test_soft_budget_over_does_not_deny if {
	count(finops.deny) == 0 with input as {
		"tenant_id": "cade2",
		"finops": {"enforcement": "soft", "current_spend": 1200, "budget_limit": 1000},
	}
}

test_soft_budget_over_warns if {
	some msg in finops.warn with input as {
		"tenant_id": "cade2",
		"finops": {"enforcement": "soft", "current_spend": 1200, "budget_limit": 1000},
	}
	contains(msg, "soft")
}

test_no_finops_context_is_inert if {
	count(finops.deny) == 0 with input as {"tenant_id": "cade2"}
	count(finops.warn) == 0 with input as {"tenant_id": "cade2"}
}

test_currency_surfaced if {
	some msg in finops.deny with input as {
		"tenant_id": "x",
		"finops": {"enforcement": "hard", "current_spend": 10, "budget_limit": 1, "currency": "EUR"},
	}
	contains(msg, "EUR")
}
