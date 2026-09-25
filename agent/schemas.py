"""
Tool schemas — the contract the model sees.

This is the ONLY thing the model knows about your tools: name, description,
and argument shape. It never sees the implementations in tools_stub.py or
tools_aws.py. That separation is what lets you swap fake tools for real
boto3 calls without the model (or the loop) knowing the difference.

One schema per finding in findings.md. Keep them in sync — if you add a
finding, add a tool here.
"""

_BUCKET_ARG = {
    "type": "object",
    "properties": {
        "bucket_name": {"type": "string", "description": "The name of the S3 bucket to check."}
    },
    "required": ["bucket_name"],
}

TOOLS = [
    {
        "name": "check_encryption_status",
        "description": (
            "Check the default encryption configuration and KMS key rotation status "
            "for a given S3 bucket. Use this when the question is about whether data "
            "at rest is encrypted, what key is used, or whether key rotation is enabled."
        ),
        "input_schema": _BUCKET_ARG,
    },
    {
        "name": "check_public_access",
        "description": (
            "Check the bucket-level S3 Block Public Access settings for a given bucket. "
            "Use this when the question is about whether the bucket as a whole could be "
            "publicly accessible. Does NOT evaluate individual object ACLs."
        ),
        "input_schema": _BUCKET_ARG,
    },
    {
        "name": "check_object_acls",
        "description": (
            "Check individual object-level ACLs within a bucket for public grants. "
            "Use this when bucket-level settings look correct but you need to confirm "
            "no individual object is publicly readable. This is a separate surface from "
            "bucket-level Block Public Access."
        ),
        "input_schema": _BUCKET_ARG,
    },
    {
        "name": "check_tls_enforcement",
        "description": (
            "Check whether a bucket's policy denies non-HTTPS (non-TLS) requests, i.e. "
            "whether encryption in transit is enforced. Use this when the question is "
            "about data in transit, HTTPS-only access, or the aws:SecureTransport "
            "condition. A bucket with NO policy enforces nothing. A Deny that covers "
            "the object ARNs but not the bucket ARN itself still leaves bucket-level "
            "API calls reachable without TLS."
        ),
        "input_schema": _BUCKET_ARG,
    },
    {
        "name": "check_iam_role_scope",
        "description": (
            "Check an IAM role's trust policy and attached permission policies for "
            "overly broad grants such as wildcard actions or unrestricted principals. "
            "Use this when the question is about least privilege or who can assume a role."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "role_name": {"type": "string", "description": "The name of the IAM role to inspect."}
            },
            "required": ["role_name"],
        },
    },
    {
        "name": "query_cloudtrail_history",
        "description": (
            "Query CloudTrail history for a resource over a specific time window. Use this "
            "when the question asks whether something was true THROUGHOUT a period, rather "
            "than right now — for example whether logging stayed enabled for a full quarter. "
            "Point-in-time configuration checks cannot answer historical questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "resource_arn": {"type": "string", "description": "ARN of the resource to query history for."},
                "start": {"type": "string", "description": "Window start, ISO 8601 date (e.g. 2026-04-01)."},
                "end": {"type": "string", "description": "Window end, ISO 8601 date (e.g. 2026-06-30)."},
                "event_name": {"type": "string", "description": "Optional CloudTrail event name to filter on."},
            },
            "required": ["resource_arn", "start", "end"],
        },
    },
    {
        "name": "flag_finding_for_remediation",
        "description": (
            "Flag a confirmed compliance finding on a bucket for remediation, by tagging "
            "the bucket. This is a WRITE action with real consequences — only call this "
            "after you have gathered clear, cited evidence of a genuine finding, not on "
            "a suspicion. This action requires human approval before it takes effect; "
            "execution will pause until a person reviews and approves it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bucket_name": {"type": "string", "description": "The bucket the finding applies to."},
                "finding": {"type": "string", "description": "A concise, evidence-based description of the finding driving this flag."},
            },
            "required": ["bucket_name", "finding"],
        },
    },
]
