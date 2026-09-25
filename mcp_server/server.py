"""
MCP server — Phase 6. COMPLETE.

Wraps the SAME functions agent/loop.py uses. No reimplementation — that's
the whole point of MCP: the tool logic is written once and any compliant
host can call it.

    pip install fastmcp
    python -m mcp_server.server                      # run as stdio server
    npx @modelcontextprotocol/inspector python -m mcp_server.server   # interactive test

To use from Claude Desktop, add to claude_desktop_config.json:
    {
      "mcpServers": {
        "evidence-agent": {
          "command": "/full/path/to/.venv/bin/python",
          "args": ["-m", "mcp_server.server"],
          "cwd": "/full/path/to/ai-lab",
          "env": {"AWS_PROFILE": "personal", "USE_REAL_TOOLS": "true"}
        }
      }
    }

VERSION NOTE: the MCP Python SDK shipped v2.0.0 as stable and REMOVED
mcp.server.fastmcp entirely (renamed to mcp.server.mcpserver.MCPServer).
Rather than chase that new API, this uses the standalone `fastmcp` package
instead — the officially recommended upgrade path, and a single import
change from the old `mcp.server.fastmcp` module. Same @mcp.tool() decorator,
same FastMCP(...) constructor, same mcp.run() — nothing else differs.
"""

import os

from fastmcp import FastMCP

# Same switch as agent/loop.py — one env var flips the whole server between
# stub mode (safe, no AWS, good for demoing) and real mode.
if os.getenv("USE_REAL_TOOLS", "false").lower() == "true":
    from agent.tools_aws import AWS_IMPL as IMPL
else:
    from agent.tools_stub import STUB_IMPL as IMPL

mcp = FastMCP("evidence-agent")


@mcp.tool()
def check_encryption_status(bucket_name: str) -> str:
    """Check default encryption configuration and KMS key rotation status for an S3 bucket.

    Use when the question is about whether data at rest is encrypted, what key
    is used, or whether key rotation is enabled.
    """
    return IMPL["check_encryption_status"](bucket_name)


@mcp.tool()
def check_public_access(bucket_name: str) -> str:
    """Check bucket-level S3 Block Public Access settings.

    Does NOT evaluate individual object ACLs — use check_object_acls for that.
    """
    return IMPL["check_public_access"](bucket_name)


@mcp.tool()
def check_object_acls(bucket_name: str) -> str:
    """Check individual object-level ACLs within a bucket for public grants.

    A separate surface from bucket-level Block Public Access: a bucket can be
    locked down at the bucket level while individual objects remain public.
    """
    return IMPL["check_object_acls"](bucket_name)


@mcp.tool()
def check_tls_enforcement(bucket_name: str) -> str:
    """Check whether a bucket's policy denies non-HTTPS (non-TLS) requests.

    Use when the question is about encryption in transit / HTTPS-only access.
    No bucket policy enforces nothing; a Deny that covers object ARNs but not
    the bucket ARN itself still leaves bucket-level calls reachable over HTTP.
    """
    return IMPL["check_tls_enforcement"](bucket_name)


@mcp.tool()
def check_iam_role_scope(role_name: str) -> str:
    """Check an IAM role's trust policy and attached policies for overly broad grants.

    Use when the question is about least privilege or who can assume a role.
    """
    return IMPL["check_iam_role_scope"](role_name)


@mcp.tool()
def query_cloudtrail_history(resource_arn: str, start: str, end: str, event_name: str = None) -> str:
    """Query CloudTrail history for a resource over a time window.

    Use when the question asks whether something was true THROUGHOUT a period
    rather than right now. Point-in-time config checks cannot answer historical
    questions. Dates are ISO 8601 (e.g. 2026-04-01).
    """
    return IMPL["query_cloudtrail_history"](resource_arn, start, end, event_name)


if __name__ == "__main__":
    mcp.run()
