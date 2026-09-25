#!/usr/bin/env bash
# Builds a Lambda-ready deployment package WITHOUT Docker.
#
# How: pip can download pre-built Linux wheels for a different platform
# than the one you're running on, as long as you force wheel-only mode
# (--only-binary=:all:) — this skips any local compilation entirely, so
# there's nothing that needs a Linux machine (or Docker pretending to be
# one) to build. anthropic's dependencies (notably pydantic-core, which
# has compiled Rust code) all publish prebuilt manylinux wheels, so this
# works cleanly.
#
# Run this ONCE before `cdk deploy`, and again whenever agent/ or
# infra/lambda_handlers/ change.
set -e

STAGING_DIR="../lambda_build"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR/infra"

# Only copy what Lambda actually needs — not the whole ai-lab tree
# (no .venv, no .git, no cdk.out — that recursive-copy bug is gone
# entirely with this approach, since we're not packaging ".." anymore).
cp -r ../agent "$STAGING_DIR/agent"
cp -r lambda_handlers "$STAGING_DIR/infra/lambda_handlers"
touch "$STAGING_DIR/infra/__init__.py"

pip install \
  --platform manylinux2014_x86_64 \
  --target "$STAGING_DIR" \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --upgrade \
  anthropic

echo "Lambda package staged at $STAGING_DIR"
