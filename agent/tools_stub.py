"""
Stub tool implementations — Phase 1. WORKING.

Hardcoded answers matching findings.md, so the loop can be exercised with
zero AWS dependency. Every return value here corresponds to a seeded finding
in the fixture, so once the real implementations land the agent's conclusions
should be the same.
"""


def check_encryption_status(bucket_name: str) -> str:
    # Finding 2 — KMS rotation disabled
    return (
        f"Bucket '{bucket_name}': default encryption is SSE-KMS, key alias "
        f"'alias/finance-data-key'. Key rotation: DISABLED."
    )


def check_public_access(bucket_name: str) -> str:
    return (
        f"Bucket '{bucket_name}': BlockPublicAcls=True, BlockPublicPolicy=True, "
        f"IgnorePublicAcls=True, RestrictPublicBuckets=True at the bucket level. "
        f"Note: object-level ACLs are not evaluated by this check."
    )


def check_object_acls(bucket_name: str) -> str:
    # Finding 1 — object-level public ACL
    return (
        f"Bucket '{bucket_name}': 1 of 4 objects has a public-read ACL — "
        f"key 'q2-summary.pdf' grants READ to AllUsers."
    )


def check_tls_enforcement(bucket_name: str) -> str:
    # Finding — mirrors the deployed target bucket: it DOES have a policy (the
    # Allow that auto_delete_objects=True injects), but that policy carries no
    # aws:SecureTransport Deny, so plain-HTTP requests are not rejected.
    return (
        f"Bucket '{bucket_name}': bucket policy has no Deny on non-TLS "
        f"requests covering the bucket. FINDING (encryption in transit "
        f"not enforced)."
    )


def check_iam_role_scope(role_name: str) -> str:
    # Finding 3 — over-broad IAM role
    return (
        f"Role '{role_name}': attached policy allows Action 's3:*' on Resource '*'. "
        f"Trust policy restricted to lambda.amazonaws.com."
    )


def query_cloudtrail_history(resource_arn: str, start: str, end: str, event_name: str = None) -> str:
    # Finding 4 — data event logging gap mid-window
    return (
        f"CloudTrail data events for {resource_arn} between {start} and {end}: "
        f"logging ENABLED from {start} until 2026-05-14, then NO data events recorded "
        f"until {end}. Gap of 47 days."
    )


def flag_finding_for_remediation(bucket_name: str, finding: str) -> str:
    # Same safe no-op as tools_aws.py's version — see that file for why.
    return (
        f"[NOT EXECUTED] flag_finding_for_remediation is a write action gated "
        f"behind human approval in the deployed pipeline (Phase 4/5). It does "
        f"not execute here, in the standalone loop or eval harness. Proposed: "
        f"bucket={bucket_name}, finding={finding!r}"
    )


STUB_IMPL = {
    "check_encryption_status": check_encryption_status,
    "check_public_access": check_public_access,
    "check_object_acls": check_object_acls,
    "check_tls_enforcement": check_tls_enforcement,
    "check_iam_role_scope": check_iam_role_scope,
    "query_cloudtrail_history": query_cloudtrail_history,
    "flag_finding_for_remediation": flag_finding_for_remediation,
}
