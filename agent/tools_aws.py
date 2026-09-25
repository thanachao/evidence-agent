"""
Real tool implementations — Phase 3. VERIFIED against the deployed fixture.

Each function mirrors one in tools_stub.py, same name, same signature, same
return type (a plain string the model can read). Swapping between them is a
one-line change in loop.py.
"""

import json

import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
kms = boto3.client("kms")
iam = boto3.client("iam")


def check_encryption_status(bucket_name: str) -> str:
    try:
        enc = s3.get_bucket_encryption(Bucket=bucket_name)
        rules = enc["ServerSideEncryptionConfiguration"]["Rules"]
        algo = rules[0]["ApplyServerSideEncryptionByDefault"]
        kms_key = algo.get("KMSMasterKeyID")
        if not kms_key:
            return f"Bucket '{bucket_name}': encrypted with {algo['SSEAlgorithm']} (AWS-managed, no CMK)."
        rot = kms.get_key_rotation_status(KeyId=kms_key)
        state = "ENABLED" if rot["KeyRotationEnabled"] else "DISABLED"
        return (
            f"Bucket '{bucket_name}': SSE-KMS with key {kms_key}. "
            f"Key rotation: {state}."
        )
    except ClientError as e:
        return f"Bucket '{bucket_name}': could not determine encryption — {e.response['Error']['Code']}"


def check_public_access(bucket_name: str) -> str:
    try:
        cfg = s3.get_public_access_block(Bucket=bucket_name)["PublicAccessBlockConfiguration"]
        return (
            f"Bucket '{bucket_name}': " + ", ".join(f"{k}={v}" for k, v in cfg.items())
            + ". Note: object-level ACLs are not evaluated by this check."
        )
    except ClientError as e:
        return f"Bucket '{bucket_name}': no public access block configured — {e.response['Error']['Code']}"


def check_object_acls(bucket_name: str) -> str:
    # TODO(chao): paginate. This only reads the first page of objects.
    try:
        public_keys = []
        objs = s3.list_objects_v2(Bucket=bucket_name).get("Contents", [])
        for obj in objs:
            acl = s3.get_object_acl(Bucket=bucket_name, Key=obj["Key"])
            for grant in acl.get("Grants", []):
                uri = grant.get("Grantee", {}).get("URI", "")
                if "AllUsers" in uri or "AuthenticatedUsers" in uri:
                    public_keys.append(f"{obj['Key']} ({grant['Permission']})")
        if not public_keys:
            return f"Bucket '{bucket_name}': no public object ACLs found across {len(objs)} objects."
        return f"Bucket '{bucket_name}': PUBLIC object ACLs found — {', '.join(public_keys)}"
    except ClientError as e:
        return f"Bucket '{bucket_name}': could not check object ACLs — {e.response['Error']['Code']}"


def check_tls_enforcement(bucket_name: str) -> str:
    # Enforcing TLS in transit means an explicit Deny on aws:SecureTransport
    # "false". Two ways this comes up short, both findings:
    #   1. No bucket policy at all — nothing denies anything.
    #   2. A Deny that lists bucket-arn/* (objects) but not bucket-arn itself
    #      — bucket-level API calls (e.g. ListObjects) still succeed over HTTP.
    # The SecureTransport condition value from AWS is the STRING "false", not
    # a boolean, so only the string is matched.
    bucket_arn = f"arn:aws:s3:::{bucket_name}"
    objects_arn = f"{bucket_arn}/*"
    try:
        doc = json.loads(s3.get_bucket_policy(Bucket=bucket_name)["Policy"])
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchBucketPolicy":
            return (
                f"Bucket '{bucket_name}': no bucket policy — HTTPS/TLS is not "
                f"enforced at all. FINDING (encryption in transit not required)."
            )
        return f"Bucket '{bucket_name}': could not read bucket policy — {code}"

    covers_bucket = False
    covers_objects = False
    for stmt in doc.get("Statement", []):
        if stmt.get("Effect") != "Deny":
            continue
        if stmt.get("Condition", {}).get("Bool", {}).get("aws:SecureTransport") != "false":
            continue
        resource = stmt.get("Resource")
        resources = resource if isinstance(resource, list) else [resource]
        if bucket_arn in resources:
            covers_bucket = True
        if objects_arn in resources:
            covers_objects = True

    if covers_bucket and covers_objects:
        return (
            f"Bucket '{bucket_name}': bucket policy denies non-TLS requests on both "
            f"the bucket and its objects. Encryption in transit is enforced."
        )
    if covers_objects and not covers_bucket:
        return (
            f"Bucket '{bucket_name}': TLS Deny covers objects ({objects_arn}) but NOT "
            f"the bucket ARN ({bucket_arn}) — bucket-level calls can still run without "
            f"TLS. FINDING (incomplete TLS enforcement)."
        )
    return (
        f"Bucket '{bucket_name}': bucket policy has no Deny on non-TLS requests "
        f"covering the bucket. FINDING (encryption in transit not enforced)."
    )


def check_iam_role_scope(role_name: str) -> str:
    # FIXED: originally only checked ATTACHED (managed) policies via
    # list_attached_role_policies. The fixture's over-broad grant is an
    # INLINE policy — a different API entirely (list_role_policies +
    # get_role_policy) — so the original version reported a false "No
    # wildcard grants found" on the fixture role. Both policy types are
    # checked now. Lesson worth keeping: IAM has two separate mechanisms
    # for attaching permissions to a role, and a tool that only checks
    # one of them is silently blind to the other — this is exactly the
    # kind of incomplete-by-default tool behavior that made an agent
    # confidently wrong in Phase 3.
    try:
        role = iam.get_role(RoleName=role_name)["Role"]
        trust = role["AssumeRolePolicyDocument"]
        findings = []

        attached = iam.list_attached_role_policies(RoleName=role_name)["AttachedPolicies"]
        for p in attached:
            pol = iam.get_policy(PolicyArn=p["PolicyArn"])["Policy"]
            ver = iam.get_policy_version(PolicyArn=p["PolicyArn"], VersionId=pol["DefaultVersionId"])
            for stmt in ver["PolicyVersion"]["Document"].get("Statement", []):
                if stmt.get("Effect") != "Allow":
                    continue
                action = stmt.get("Action")
                resource = stmt.get("Resource")
                if "*" in str(action) or resource == "*":
                    findings.append(f"{p['PolicyName']} (attached): Action={action} Resource={resource}")

        inline_names = iam.list_role_policies(RoleName=role_name)["PolicyNames"]
        for name in inline_names:
            doc = iam.get_role_policy(RoleName=role_name, PolicyName=name)["PolicyDocument"]
            for stmt in doc.get("Statement", []):
                if stmt.get("Effect") != "Allow":
                    continue
                action = stmt.get("Action")
                resource = stmt.get("Resource")
                if "*" in str(action) or resource == "*":
                    findings.append(f"{name} (inline): Action={action} Resource={resource}")

        summary = f"Role '{role_name}': trust policy = {trust}. "
        return summary + (f"BROAD GRANTS: {'; '.join(findings)}" if findings else "No wildcard grants found.")
    except ClientError as e:
        return f"Role '{role_name}': could not check role scope — {e.response['Error']['Code']}"


def query_cloudtrail_history(resource_arn: str, start: str, end: str, event_name: str = None) -> str:
    # TODO(chao): this is the hard one. Decide CloudTrail Lake (SQL, needs an
    # event data store) vs LookupEvents (management events only, 90 days).
    # findings.md Finding 4 assumes Lake. Implement after the fixture proves
    # the gap is visible by hand.
    raise NotImplementedError("Phase 3 — see findings.md Finding 4 before implementing")


def flag_finding_for_remediation(bucket_name: str, finding: str) -> str:
    # SAFE NO-OP outside the deployed pipeline. This tool's real
    # implementation lives in infra/lambda_handlers/execute_write_handler.py
    # and only ever runs after a human approves it via the Step Functions
    # WAIT_FOR_TASK_TOKEN gate. The standalone loop (and this eval harness)
    # has no such gate — so calling the real write logic here would be a
    # genuine, unreviewed AWS mutation triggered by an eval run. That's
    # exactly the failure mode Phase 5 exists to prevent. This placeholder
    # preserves that invariant: no actual write ever happens outside the
    # approved pipeline, no matter what calls this tool.
    return (
        f"[NOT EXECUTED] flag_finding_for_remediation is a write action gated "
        f"behind human approval in the deployed pipeline (Phase 4/5). It does "
        f"not execute here, in the standalone loop or eval harness. Proposed: "
        f"bucket={bucket_name}, finding={finding!r}"
    )


AWS_IMPL = {
    "check_encryption_status": check_encryption_status,
    "check_public_access": check_public_access,
    "check_object_acls": check_object_acls,
    "check_tls_enforcement": check_tls_enforcement,
    "check_iam_role_scope": check_iam_role_scope,
    "query_cloudtrail_history": query_cloudtrail_history,
    "flag_finding_for_remediation": flag_finding_for_remediation,
}
