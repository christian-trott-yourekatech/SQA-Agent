#!/usr/bin/env bash
# Install (or reinstall) sqa-tool from the public repository.
# Re-running upgrades to the latest published version.

set -euo pipefail

uv tool install --reinstall \
    git+https://github.com/christian-trott-yourekatech/SQA-Agent.git
