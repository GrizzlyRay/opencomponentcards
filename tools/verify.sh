#!/usr/bin/env bash
# Verify cards against the trusted-signer policy in trust/signers.yaml.
# Usage: tools/verify.sh [--min-level registry|community|verified] CARD...
set -euo pipefail
exec python3 "$(dirname "$0")/verify_signer.py" "$@"
