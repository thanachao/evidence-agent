"""
The agent loop — Phase 1. WORKING.

Generalized from the version you already ran. Two changes from that file:
  1. Tools and implementations are imported, not defined inline.
  2. USE_REAL_TOOLS flips the whole system between stub and AWS mode.

The loop itself does not change again for the rest of the project. Phase 4
wraps it in Step Functions; Phase 6 exposes the same tools over MCP; Phase 8
re-hosts it. None of those rewrite what is below.

Run:
    python -m agent.loop
"""

import anthropic

from agent.schemas import TOOLS
from agent.tools_stub import STUB_IMPL

# Flip to True once tools_aws.py is verified against the deployed fixture.
USE_REAL_TOOLS = True

if USE_REAL_TOOLS:
    from agent.tools_aws import AWS_IMPL as TOOL_IMPL
else:
    TOOL_IMPL = STUB_IMPL

client = anthropic.Anthropic()

MODEL = "claude-sonnet-5"   # pinned deliberately — see docs/adr/0002
MAX_STEPS = 8               # guardrail: bounded investigation


def run_agent(question: str, verbose: bool = True) -> dict:
    """Returns a dict so Phase 7 evals can assert on trajectory, not just text."""
    messages = [{"role": "user", "content": question}]
    trajectory = []

    for step in range(1, MAX_STEPS + 1):
        if verbose:
            print(f"\n--- step {step} ---")

        response = client.messages.create(
            model=MODEL, max_tokens=2048, tools=TOOLS, messages=messages
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                trajectory.append({"step": step, "tool": block.name, "input": block.input})
                if verbose:
                    print(f"  called: {block.name}({block.input})")

                out = TOOL_IMPL[block.name](**block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": out,
                })
            messages.append({"role": "user", "content": results})
            continue

        answer = "".join(b.text for b in response.content if b.type == "text")
        return {"answer": answer, "trajectory": trajectory, "steps": step, "hit_budget": False}

    return {"answer": None, "trajectory": trajectory, "steps": MAX_STEPS, "hit_budget": True}


if __name__ == "__main__":
    q = (
        "Check bucket 'finance-reports-prod-556957334146' for encryption "
        "status, public access configuration, and any public object ACLs. "
        "Also check the IAM role 'fixture-report-processor-role' for "
        "overly broad permissions. Cite the evidence for each finding."
    )
    result = run_agent(q)
    print("\n" + "=" * 70)
    print(result["answer"] or f"Hit step budget after {result['steps']} steps.")
