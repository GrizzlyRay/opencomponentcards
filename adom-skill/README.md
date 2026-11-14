# OpenComponentCards for Adom

A local skill for the OpenComponentCards tools. It teaches an agent to import a card, export plain SPICE numbers, and run a board Monte Carlo from a clone of https://github.com/GrizzlyRay/opencomponentcards.

Author: Jacob Warren and GrizzlyRay LLC. Where this package mentions Adom, the credit is an engineer at Adom.

Install the skill files with `./install.sh`. Remove them with `./uninstall.sh`. Both accept `--dry-run` and `--dest DIR`. When `--dest` is omitted, `ADOM_WIKI_SKILL_DEST` selects the directory. Otherwise the scripts use `~/.claude/skills` and `${CODEX_HOME:-$HOME/.codex}/skills`. They copy this skill only. They do not copy the OpenComponentCards tree, and they do not install Python packages.

Read SKILL.md before running a tool. Keep `--allow-adom` and `--allow-fallback` off unless the user asks. Keep every `--out` path under `out/`. Do not commit a draft or a real page.json.
