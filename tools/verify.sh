#!/usr/bin/env bash
# Verify a card's Sigstore bundle. Usage: tools/verify.sh cards/examples/example_resistor.yaml
set -euo pipefail
card="$1"
cosign verify-blob "$card" \
  --bundle "${card}.sigstore.json" \
  --certificate-identity "https://github.com/GrizzlyRay/opencomponentcards/.github/workflows/sign.yml@refs/heads/main" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
