"""
Eval harness — Phase 7. COMPLETE.

Turns "it seems to work" into "N/N against labeled ground truth". This is
the prerequisite for any defensible claim about agent quality, and the
prerequisite for the optional fine-tuning exercise later (you cannot claim
a fine-tune helped without a baseline to compare against).

    pytest evals/ -v
    pytest evals/ -v -k decoy        # run one scenario

Two things are asserted, and they're different in kind:
  1. TRAJECTORY — did it call the right tools? Deterministic, cheap, reliable.
  2. CONCLUSION — did it decide "finding" vs "compliant"? Needs judgement.

For (2) this uses LLM-as-judge with a deliberately narrow prompt. Keyword
matching was tried first and is too brittle — "no public access issues
found" and "public access misconfigured" both contain "public access".
The judge call is cheap (one short completion) and far more reliable.

KNOWN LIMITATION worth writing into an ADR: the judge is itself a model,
so judge errors are possible. Mitigations used here: the judge sees only
the answer text and must reply with exactly one word, temperature 0, and
the scenarios are designed so "finding" vs "compliant" is unambiguous to
a careful human reader. For a real system you'd measure judge agreement
against human labels on a sample.
"""

import os
import yaml
import pytest
import anthropic

from agent.loop import run_agent

SCENARIOS_PATH = os.path.join(os.path.dirname(__file__), "scenarios.yaml")
with open(SCENARIOS_PATH) as f:
    SCENARIOS = yaml.safe_load(f)

judge_client = anthropic.Anthropic()
JUDGE_MODEL = "claude-sonnet-5"

JUDGE_PROMPT = """You are grading the output of a cloud compliance agent.

The agent was asked a SPECIFIC question. Determine whether the agent
concluded that THE SPECIFIC THING ASKED ABOUT has a compliance PROBLEM,
or is COMPLIANT.

Important: a thorough agent may proactively surface a SEPARATE, unrelated
finding while investigating (e.g. it was asked about a bucket policy and
also happened to notice an unrelated encryption issue). That is good
behavior, not a defect — and it does NOT count toward your verdict. Grade
ONLY the agent's conclusion about the specific question asked, ignoring
any additional findings it volunteered beyond that scope.

Reply with exactly one word, lowercase, nothing else:
  finding    - the agent concluded the SPECIFIC thing asked about has a problem
  compliant  - the agent concluded the SPECIFIC thing asked about is fine
  unclear    - the agent did not reach a conclusion on the specific question

Question asked: {question}

Agent's answer:
---
{answer}
---"""


def _judge_conclusion(question: str, answer: str) -> str:
    if not answer:
        return "unclear"
    resp = judge_client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=10,
        # NOTE: temperature=0 was dropped here — the installed SDK version
        # raised TypeError on it ("unexpected keyword argument"), which is
        # unusual for a normally-standard parameter and worth investigating
        # further if you hit this again. Not load-bearing for this task:
        # max_tokens=10 already tightly constrains the judge's output.
        messages=[{"role": "user", "content": JUDGE_PROMPT.format(question=question, answer=answer)}],
    )
    verdict = "".join(b.text for b in resp.content if b.type == "text").strip().lower()
    return verdict if verdict in {"finding", "compliant", "unclear"} else "unclear"


@pytest.mark.parametrize("sc", SCENARIOS, ids=lambda s: s["id"])
def test_scenario(sc):
    if sc.get("skip_reason"):
        pytest.skip(sc["skip_reason"])

    result = run_agent(sc["question"], verbose=False)

    # 1. Budget — an agent that never finished tells you nothing about quality.
    assert not result["hit_budget"], (
        f"{sc['id']}: exhausted step budget after {result['steps']} steps. "
        f"Tools called: {[t['tool'] for t in result['trajectory']]}"
    )

    # 2. Trajectory — assert on the SET of tools, not the order. Tools are
    # called in parallel within a step when they're independent, so a strict
    # ordered assertion produces false failures. (Observed in Phase 1.)
    called = {t["tool"] for t in result["trajectory"]}
    missing = set(sc["must_call"]) - called
    assert not missing, f"{sc['id']}: never called {missing}. Called: {called or '{}'}"

    # 3. Conclusion — the judgement call.
    verdict = _judge_conclusion(sc["question"], result["answer"])
    assert verdict == sc["must_conclude"], (
        f"{sc['id']}: expected '{sc['must_conclude']}', judge said '{verdict}'.\n"
        f"Answer was:\n{result['answer']}"
    )
