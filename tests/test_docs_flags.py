#!/usr/bin/env python3
"""Every argparse flag is named in the matching doc page. No pytest and no network.

Run: python3 tests/test_docs_flags.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import board_mc  # noqa: E402
import spice_export  # noqa: E402

failures = 0
PAGES = (
    (spice_export, ROOT / "docs" / "spice-export.md"),
    (board_mc, ROOT / "docs" / "board-mc.md"),
)
README_PATHS = (
    "tools/spice_export.py",
    "tools/board_mc.py",
    "adom-skill/",
    "docs/spice-export.md",
    "docs/board-mc.md",
)


def check(name, cond):
    global failures
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    failures += not cond


def argparse_flags(module):
    """Option strings from the tool's real parser, including -h and --help."""
    captured = {}
    original = module._Parser

    class Capture(original):
        def parse_args(self, args=None, namespace=None):
            captured["parser"] = self
            raise SystemExit(0)

    module._Parser = Capture
    try:
        module.main([])
    except SystemExit:
        pass
    finally:
        module._Parser = original
    parser = captured.get("parser")
    if parser is None:
        return []
    flags = []
    for action in parser._actions:
        flags.extend(action.option_strings)
    return flags


def contains_flag(text, flag):
    return re.search(re.escape(flag) + r"(?![A-Za-z0-9-])", text) is not None


readme = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").is_file() else ""
layout = ""
unreleased = ""
if "## Repository layout" in readme and "## Quick start" in readme:
    layout = readme.split("## Repository layout", 1)[1].split("## Quick start", 1)[0]
if "## Changelog" in readme and "**v0.2" in readme:
    unreleased = readme.split("## Changelog", 1)[1].split("**v0.2", 1)[0]
for name in README_PATHS:
    check(f"repository layout lists {name}", name in layout)
    check(f"Unreleased changelog names {name}", name in unreleased)

for module, page in PAGES:
    flags = argparse_flags(module)
    text = page.read_text(encoding="utf-8") if page.is_file() else ""
    missing = [flag for flag in flags if not contains_flag(text, flag)]
    check(
        f"{page.name} names every {module.__name__} flag",
        bool(flags) and not missing and page.is_file(),
    )
    if missing or not flags:
        print(f"  flags {flags}")
        print(f"  missing {missing}")

print(f"\n{'all tests passed' if not failures else f'{failures} test(s) failed'}")
sys.exit(1 if failures else 0)
