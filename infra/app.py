#!/usr/bin/env python3
import os
import aws_cdk as cdk
from fixture_stack import FixtureStack
from pipeline_stack import PipelineStack

app = cdk.App()

env = cdk.Environment(
    account=os.getenv("CDK_DEFAULT_ACCOUNT"),
    region="us-east-1",
)

FixtureStack(app, "EvidenceAgentFixture", env=env)
PipelineStack(app, "EvidenceAgentPipeline", env=env)

app.synth()
