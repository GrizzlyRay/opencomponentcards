# Signer Trust

A Sigstore signature tells you who signed a card and that it hasn't changed since. It doesn't tell you whether you should trust that signer. That's what `trust/signers.yaml` is for: a short, public allow-list of the identities this project recognizes, what level each one is, and which cards each one may sign.

## Trust Levels

| Level | Who | What it promises |
| --- | --- | --- |
| `registry` | This repo's sign workflow | The card was published by GrizzlyRay/opencomponentcards and hasn't been modified. It does **not** claim anyone checked the numbers against a datasheet. |
| `community` | A contributor signing with their own GitHub identity | That person reviewed and signed this exact card. |
| `verified` | A vetted manufacturer or lab | An identity we've confirmed belongs to that organization signed this exact card, inside the scope we approved. |

Levels are ordered `registry` < `community` < `verified`. A tool can require a minimum level, for example `--min-level verified` for cards that feed a production design.

On day one there's exactly one signer: the GrizzlyRay sign workflow at the `registry` level. Every card in the repo carries that signature.

## The Policy File

Each entry in `trust/signers.yaml` has:

- `id`: a short slug
- `name`: who it is
- `kind`: `registry`, `community`, or `verified`
- `identity.san_regex`: an anchored regex for the certificate identity (the SAN in the Sigstore certificate)
- `identity.issuer`: the OIDC issuer, like `https://token.actions.githubusercontent.com` or `https://github.com/login/oauth`
- `scope`: `paths` (globs like `cards/real/acme-*.yaml`) and/or `manufacturers` (matched against the card's `part.manufacturer`). If both are present, a card must match both.
- `added`: the date the entry was added
- `approval`: a link to the public issue or PR where it was approved

The file is checked against [schema/signers.schema.json](../schema/signers.schema.json) in CI.

## Verifying a Card

```sh
tools/verify.sh cards/real/royalohm-0603waf470kt5e.yaml
tools/verify.sh --min-level verified cards/real/*.yaml
```

For each card, the verifier finds signers at or above the minimum level whose scope covers the card, then asks cosign to verify `<card>.sigstore.json` against each one's identity and issuer. It prints the signer's name and level, and fails if the identity isn't in the list, the card is outside the signer's scope, the card was changed, or there's no bundle.

## How to Apply

1. Open a new issue and pick the **Become a Signer** form.
2. Fill in who you are, the identity you'll sign with, proof that it's you (a GitHub org with your domain verified, or a link from your own site or wiki naming the identity), and which cards you want to sign.
3. Jacob Warren reviews it in public and may ask questions in the comments.
4. If it's approved, a small PR adds your entry with a link back to the issue. Once it merges, your signatures are recognized. If not, the issue is closed with a note.

Entries can be removed the same way, in public, if a signature is misused or a key identity changes hands.

## How Signers Sign

Signing uses cosign keyless signing, the same free tool our workflow uses. There's no private key to manage; the certificate is tied to your GitHub login (or your workflow's identity).

```sh
cosign sign-blob --yes --bundle cards/real/acme-part.yaml.sigstore.json cards/real/acme-part.yaml
```

That opens a browser to sign in with GitHub. In a GitHub Actions workflow, give the job `permissions: id-token: write` and the workflow's identity is used instead. Then open a PR with the bundle.

Today each card has one bundle file, so a card signed by a community or verified signer carries that signer's bundle. Supporting several bundles per card is one of the later steps below.

## Later Steps

- **Multiple signatures** for high-stakes cards, for example requiring both the registry and a verified manufacturer.
- **in-toto** attestations to record how a card was produced (datasheet, extraction, review).
- **TUF** to sign the policy file itself and delegate trust, so clients can update the signer list safely.

## Prior Art

This model borrows from PyPI and npm trusted publishing, where a package index trusts a specific CI workflow identity through OIDC instead of long-lived tokens, and from Sigstore's identity-based verification.
