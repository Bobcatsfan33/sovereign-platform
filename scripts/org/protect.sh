#!/usr/bin/env bash
# scripts/org/protect.sh — branch protection as code (SH-2). Requires an admin
# PAT. Enforces: PR required, 1 approving review (not the author), required
# status checks, no force-push/deletion, code-owner review, signed commits.
#
#   bash scripts/org/protect.sh sovereign-platform
#
# NOTE: leave protection DISABLED until a second maintainer exists — with a
# single owner, "require a review that is not the author" makes every merge
# impossible. Run this the moment the second maintainer is added.
set -euo pipefail

repo="${1:?usage: protect.sh <repo>}"

gh api -X PUT "repos/Bobcatsfan33/${repo}/branches/main/protection" \
  -H "Accept: application/vnd.github+json" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["security-suite / build-scan-sign", "ci"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "require_code_owner_reviews": true,
    "require_last_push_approval": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_signatures": true
}
JSON

echo "branch protection applied to ${repo}:main"
