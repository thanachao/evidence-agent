"""
Strands + AgentCore port — Phase 8.

The SAME agent, rebuilt on AWS's managed stack. The point of this file is
NOT that it's better than agent/loop.py — it's that having built both, you
can say precisely what the managed layer buys and what it costs. That
comparison is the actual interview answer; the port is just what earns you
the right to make it.

    pip install strands-agents strands-agents-tools     # needs Python 3.10+

Two modes below:
  A. Tools passed directly as Python functions (@tool decorator)
  B. Tools consumed over MCP from mcp_server/server.py — proves the Phase 6
     server is genuinely reusable, not just a demo

WHAT YOU GAVE UP vs agent/loop.py (write this into an ADR yourself):
  - visibility into every state transition; the loop is inside the SDK now
  - the explicit step budget in loop.py becomes the SDK's own turn limits
  - Step Functions' durable, inspectable execution history
WHAT YOU GAINED:
  - lifecycle controls, tracing, and evals without hand-building them
  - model portability (Bedrock, Anthropic, OpenAI, others) behind one interface
  - a straight path to AgentCore Runtime for hosting
"""

import os

from strands import Agent, tool
from strands.models.anthropic import AnthropicModel

if os.getenv("USE_REAL_TOOLS", "false").lower() == "true":
    from agent.tools_aws import AWS_IMPL as IMPL
else:
    from agent.tools_stub import STUB_IMPL as IMPL

# Strands defaults to Bedrock as its model provider — a DIFFERENT provider
# than every other phase in this project, which talks to the Anthropic API
# directly. Explicit here so this stays consistent with agent/loop.py's
# pinned model (see docs/adr/0002) rather than silently routing through
# Bedrock's separate model-access approval process.
_model = AnthropicModel(
    client_args={"api_key": os.environ["ANTHROPIC_API_KEY"]},
    model_id="claude-sonnet-5",
    max_tokens=2048,
)


# --- Mode A: tools as decorated Python functions -----------------------
# Strands reads the type hints and docstring to build the schema — so the
# docstring here plays exactly the role `description` plays in
# agent/schemas.py. Same lesson as Phase 1: this text IS the decision
# signal, not documentation.

@tool
def check_encryption_status(bucket_name: str) -> str:
    """Check default encryption and KMS key rotation status for an S3 bucket."""
    return IMPL["check_encryption_status"](bucket_name)


@tool
def check_public_access(bucket_name: str) -> str:
    """Check bucket-level S3 Block Public Access settings. Does not evaluate object ACLs."""
    return IMPL["check_public_access"](bucket_name)


@tool
def check_object_acls(bucket_name: str) -> str:
    """Check object-level ACLs within a bucket for public grants."""
    return IMPL["check_object_acls"](bucket_name)


@tool
def check_tls_enforcement(bucket_name: str) -> str:
    """Check whether a bucket's policy denies non-HTTPS (non-TLS) requests. No policy enforces nothing."""
    return IMPL["check_tls_enforcement"](bucket_name)


@tool
def check_iam_role_scope(role_name: str) -> str:
    """Check an IAM role's trust policy and attached policies for overly broad grants."""
    return IMPL["check_iam_role_scope"](role_name)


LOCAL_TOOLS = [check_encryption_status, check_public_access, check_object_acls,
               check_tls_enforcement, check_iam_role_scope]


def run_local(question: str):
    """Mode A — tools in-process. Compare this to the ~40 lines of loop in agent/loop.py."""
    agent = Agent(model=_model, tools=LOCAL_TOOLS)
    return agent(question)


# --- Mode B: same tools, consumed over MCP ----------------------------

def run_via_mcp(question: str):
    """Mode B — identical tools, reached over MCP instead of imported.

    This is the payoff of Phase 6: mcp_server/server.py is consumed here by
    Strands, and by Claude Desktop, with zero code duplication.
    """
    from mcp import stdio_client, StdioServerParameters
    from strands.tools.mcp import MCPClient

    client = MCPClient(lambda: stdio_client(StdioServerParameters(
        command="python", args=["-m", "mcp_server.server"],
    )))

    with client:
        agent = Agent(model=_model, tools=client.list_tools_sync())
        return agent(question)


if __name__ == "__main__":
    q = ("Check bucket finance-reports-prod-556957334146 for encryption and public access issues, "
         "including object-level ACLs. Cite what you found.")

    print("=" * 70, "\nMODE A — tools in-process\n", "=" * 70)
    print(run_local(q))

    print("=" * 70, "\nMODE B — same tools over MCP\n", "=" * 70)
    print(run_via_mcp(q))
