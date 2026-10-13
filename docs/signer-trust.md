# Signer Trust

Each card can carry several signatures, one per signer. A Sigstore signature tells you who signed a card and that it hasn't changed since. It doesn't tell you whether you should trust that signer. That's what `trust/signers.yaml` is for: a short, public allow-list of the identities this project recognizes, what level each one is, and which cards each one may sign.

## Trust Levels

| Level | Who | What it promises |
| --- | --- | --- |
| `registry` | This repo's sign workflow | The card was published by GrizzlyRay/opencomponentcards and hasn't been modified. It does **not** claim anyone checked the numbers against a datasheet. |
| `community` | A contributor signing with their own GitHub identity | That person reviewed and signed this exact card. |
| `verified` | A vetted manufacturer or lab | An identity we've confirmed belongs to that organization signed this exact card, inside the scope we approved. |

Levels are ordered `registry` < `community` < `verified`. A tool can require a minimum level, for example `--min-level verified` for cards that feed a production design.

On day one there's exactly one signer: the GrizzlyRay sign workflow at the `registry` level. Every card in the repo carries that signature, and others can add their own next to it.

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

It can also have an optional `policies` list for cards that need more than one signature:

```yaml
policies:
  - id: production-power
    description: Power parts need the registry plus a verified manufacturer.
    paths: ["cards/real/power/**"]
    require: { min_signers: 2, kinds: [registry, verified] }
```

A rule applies to every card matching `paths`. It needs at least `min_signers` different valid signers whose kind is in `kinds` (any kind if `kinds` is left out). None are turned on yet.

The file is checked against [schema/signers.schema.json](../schema/signers.schema.json) in CI.

## Where Signatures Live

Each card has a sibling folder holding one Sigstore bundle per signer, named after the signer's `id`:

```
cards/real/royalohm-0603waf470kt5e.yaml
cards/real/royalohm-0603waf470kt5e.yaml.sigs/
  grizzlyray-sign-workflow.sigstore.json
  acme-corp.sigstore.json
```

The sign workflow only writes its own file, `grizzlyray-sign-workflow.sigstore.json`. It never overwrites or deletes anyone else's.

## Verifying a Card

```sh
tools/verify.sh cards/real/royalohm-0603waf470kt5e.yaml
tools/verify.sh --min-level verified cards/real/*.yaml
tools/verify.sh --strict cards/**/*.yaml
```

The verifier checks every bundle in the card's `.sigs/` folder against the signer named in its file name: the identity and issuer must match, and the card must be inside that signer's scope. It prints each signer and level, then the highest valid level.

A card passes when:

- at least one valid, in-scope signature meets `--min-level` (default `registry`), and
- every `policies` rule matching the card is satisfied.

Bundles that don't check out (an unknown signer id, the wrong identity, out of scope, or a signature made before the card was edited) are reported as errors and never count. They don't fail the card on their own unless you pass `--strict`. The card also fails if it has no signatures at all.

## When a Card Changes

A signature covers the exact bytes of the card. When a card is edited, the workflow re-signs it with its own identity, but everyone else's signature goes stale and the verifier flags it. Those signers need to re-sign the new version and open a PR with their updated bundle. Until they do, their signature doesn't count, and any policy that relied on it will fail.

## How to Apply

1. Open a new issue and pick the **Become a Signer** form.
2. Fill in who you are, the identity you'll sign with, proof that it's you (a GitHub org with your domain verified, or a link from your own site or wiki naming the identity), and which cards you want to sign.
3. Jacob Warren reviews it in public and may ask questions in the comments.
4. If it's approved, a small PR adds your entry with a link back to the issue. Once it merges, your signatures are recognized. If not, the issue is closed with a note.

Entries can be removed the same way, in public, if a signature is misused or a key identity changes hands.

## How Signers Sign

Signing uses cosign keyless signing, the same free tool our workflow uses. There's no private key to manage; the certificate is tied to your GitHub login (or your workflow's identity).

```sh
mkdir -p cards/real/acme-part.yaml.sigs
cosign sign-blob --yes --bundle cards/real/acme-part.yaml.sigs/acme-corp.sigstore.json cards/real/acme-part.yaml
```

That opens a browser to sign in with GitHub. In a GitHub Actions workflow, give the job `permissions: id-token: write` and the workflow's identity is used instead. Name the file after your signer `id` in `trust/signers.yaml`, then open a PR with just that file.

## Later Steps

- **in-toto** attestations to record how a card was produced (datasheet, extraction, review).
- **TUF** to sign the policy file itself and delegate trust, so clients can update the signer list safely.

## Prior Art

This model borrows from PyPI and npm trusted publishing, where a package index trusts a specific CI workflow identity through OIDC instead of long-lived tokens, and from Sigstore's identity-based verification.
