#!/usr/bin/env python3
"""Tests for the local Adom wiki skill package. No pytest and no network.

Run: python3 tests/test_adom_skill.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "adom-skill"
failures = 0
REQUIRED_FIELDS = (
    "slug",
    "title",
    "version",
    "type",
    "description",
    "tags",
    "discovery_triggers",
    "discovery_pitch",
    "sample_prompts",
    "dependencies",
    "scripts",
    "files",
)
FLAG_MARKERS = (
    ".venv/bin/python",
    "tools/adom_import.py",
    "tools/spice_export.py",
    "tools/board_mc.py",
    "--from-file",
    "--kinds",
    "--category",
    "--manufacturer",
    "--date",
    "--report",
    "--netlist",
    "--bind",
    "--runs",
    "--seed",
    "--jobs",
    "--sim",
    "--spec",
    "--timeout",
    "--bom",
    "--allow-adom",
    "--allow-fallback",
    "--out",
    "page.json",
    "exit 2",
)
CREDIT = "Jacob Warren and GrizzlyRay LLC"
ADOM_CREDIT = "an engineer at Adom"


def check(name, cond):
    global failures
    print(f"{'PASS' if cond else 'FAIL'} {name}")
    failures += not cond


def run(cmd, cwd, env, timeout=60):
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def snapshot(path):
    found = {}
    if not path.exists():
        return found
    for item in path.rglob("*"):
        if item.is_file():
            found[item.relative_to(path).as_posix()] = item.read_bytes()
    return found


def script_env(home):
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["CODEX_HOME"] = str(home / "codex")
    env.pop("ADOM_WIKI_SKILL_DEST", None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


package = {}
package_text = ""
skill_text = ""
readme_text = ""
if (SKILL / "package.json").is_file():
    package_text = (SKILL / "package.json").read_text(encoding="utf-8")
    package = json.loads(package_text)
if (SKILL / "SKILL.md").is_file():
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
if (SKILL / "README.md").is_file():
    readme_text = (SKILL / "README.md").read_text(encoding="utf-8")

listed = package.get("files") if isinstance(package.get("files"), list) else []
disk = []
if SKILL.is_dir():
    disk = sorted(item.relative_to(SKILL).as_posix() for item in SKILL.rglob("*") if item.is_file())
missing = [name for name in listed if not (SKILL / name).is_file()]
globbed = [name for name in listed if any(mark in name for mark in "*?[]")]
directories = [name for name in listed if (SKILL / name).is_dir()]
check(
    "required files exist, including everything in files[]",
    SKILL.is_dir()
    and (SKILL / "package.json").is_file()
    and (SKILL / "SKILL.md").is_file()
    and (SKILL / "README.md").is_file()
    and (SKILL / "install.sh").is_file()
    and (SKILL / "uninstall.sh").is_file()
    and not missing
    and not directories,
)
if missing or directories or not SKILL.is_dir():
    print(f"  missing {missing} directories {directories}")

scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
prompts = package.get("sample_prompts")
prompt_ok = (
    isinstance(prompts, list)
    and prompts
    and all(isinstance(item, dict) and item.get("label") and item.get("prompt") for item in prompts)
)
fields_ok = all(name in package for name in REQUIRED_FIELDS)
check(
    "package.json has the skill fields and leaves org out",
    fields_ok
    and package.get("slug") == "opencomponentcards"
    and package.get("title") == "OpenComponentCards for Adom"
    and package.get("version") == "0.1.0"
    and package.get("type") == "skill"
    and isinstance(package.get("description"), str)
    and len(package.get("description", "")) >= 20
    and isinstance(package.get("tags"), list)
    and package.get("tags")
    and isinstance(package.get("discovery_triggers"), list)
    and len(package.get("discovery_triggers", [])) >= 3
    and isinstance(package.get("discovery_pitch"), str)
    and package.get("discovery_pitch")
    and prompt_ok
    and package.get("dependencies") == {}
    and scripts.get("install") == "./install.sh"
    and scripts.get("uninstall") == "./uninstall.sh"
    and "org" not in package
    and "hero" not in package,
)
check(
    "files[] has no globs and matches the files on disk",
    isinstance(listed, list)
    and listed
    and not globbed
    and set(listed) == set(disk)
    and all((SKILL / name).is_file() for name in listed),
)
if globbed or set(listed) != set(disk):
    print(f"  globs {globbed}")
    print(f"  listed {sorted(listed)}")
    print(f"  disk {disk}")

taught = skill_text + "\n" + readme_text
check(
    "the skill names the real flags and the safe defaults",
    all(marker in skill_text for marker in FLAG_MARKERS)
    and "allow-adom" in skill_text
    and "allow-fallback" in skill_text
    and "gitignored" in skill_text.lower() or "out/" in skill_text,
)
check(
    "the credit line is in SKILL.md or README.md",
    CREDIT in taught and ADOM_CREDIT in taught,
)
front = ""
if skill_text.startswith("---"):
    front = skill_text.split("---", 2)[1]
check(
    "SKILL.md frontmatter is invocable",
    "name: opencomponentcards" in front and "user-invocable: true" in front and "description:" in front,
)

install_sh = (SKILL / "install.sh").read_text(encoding="utf-8") if (SKILL / "install.sh").is_file() else ""
uninstall_sh = (SKILL / "uninstall.sh").read_text(encoding="utf-8") if (SKILL / "uninstall.sh").is_file() else ""
for label, text in (("install.sh", install_sh), ("uninstall.sh", uninstall_sh)):
    check(
        f"{label} is strict and does not fetch",
        text.startswith("#!")
        and "set -euo pipefail" in text
        and "sudo" not in text
        and "curl" not in text
        and "wget" not in text
        and "pip " not in text
        and "urllib" not in text
        and "shell=True" not in text
        and "--dry-run" in text
        and "--dest" in text
        and "ADOM_WIKI_SKILL_DEST" in text,
    )

syntax_ok = True
if install_sh and uninstall_sh:
    for name in ("install.sh", "uninstall.sh"):
        proc = run(["bash", "-n", str(SKILL / name)], ROOT, os.environ.copy())
        if proc.returncode != 0:
            syntax_ok = False
            print(proc.stderr)
else:
    syntax_ok = False
check("bash -n accepts both scripts", syntax_ok)

shellcheck = shutil.which("shellcheck")
if shellcheck is None:
    print("SKIP shellcheck: shellcheck is not on PATH")
else:
    proc = run([shellcheck, str(SKILL / "install.sh"), str(SKILL / "uninstall.sh")], ROOT, os.environ.copy())
    check("shellcheck accepts both scripts", proc.returncode == 0)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)

home = Path(tempfile.mkdtemp(prefix="occ-skill-home-"))
dest = Path(tempfile.mkdtemp(prefix="occ-skill-dest-"))
other = Path(tempfile.mkdtemp(prefix="occ-skill-env-"))
try:
    (dest / "other-skill").mkdir()
    (dest / "other-skill" / "KEEP").write_text("keep\n", encoding="utf-8")
    (dest / "keep.txt").write_text("keep\n", encoding="utf-8")
    before = snapshot(dest)
    home_before = snapshot(home)
    env = script_env(home)
    dry_install = run(
        ["bash", str(SKILL / "install.sh"), "--dry-run", "--dest", str(dest)],
        ROOT,
        env,
    )
    dry_uninstall = run(
        ["bash", str(SKILL / "uninstall.sh"), "--dry-run", "--dest", str(dest)],
        ROOT,
        env,
    )
    check(
        "--dry-run on install and uninstall changes nothing",
        dry_install.returncode == 0
        and dry_uninstall.returncode == 0
        and "dry-run" in dry_install.stdout
        and "dry-run" in dry_uninstall.stdout
        and snapshot(dest) == before
        and snapshot(home) == home_before,
    )
    if snapshot(dest) != before or dry_install.returncode != 0 or dry_uninstall.returncode != 0:
        print(dry_install.stdout)
        print(dry_install.stderr)
        print(dry_uninstall.stdout)
        print(dry_uninstall.stderr)

    first = run(["bash", str(SKILL / "install.sh"), "--dest", str(dest)], ROOT, env)
    installed = snapshot(dest)
    skill_dir = dest / "opencomponentcards"
    installed_ok = (
        first.returncode == 0
        and (skill_dir / "SKILL.md").is_file()
        and (skill_dir / "README.md").is_file()
        and (skill_dir / "SKILL.md").read_text(encoding="utf-8") == skill_text
        and (skill_dir / "README.md").read_text(encoding="utf-8") == readme_text
        and (dest / "keep.txt").read_text(encoding="utf-8") == "keep\n"
        and (dest / "other-skill" / "KEEP").is_file()
        and snapshot(home) == home_before
        and not (skill_dir / "tools").exists()
        and not (skill_dir / "cards").exists()
    )
    second = run(["bash", str(SKILL / "install.sh"), "--dest", str(dest)], ROOT, env)
    check(
        "a second install is idempotent",
        installed_ok and second.returncode == 0 and snapshot(dest) == installed,
    )
    if not installed_ok or second.returncode != 0 or snapshot(dest) != installed:
        print(first.stdout)
        print(first.stderr)
        print(second.stdout)
        print(second.stderr)
        print(sorted(installed))
        print(sorted(snapshot(dest)))

    removed = run(["bash", str(SKILL / "uninstall.sh"), "--dest", str(dest)], ROOT, env)
    again = run(["bash", str(SKILL / "uninstall.sh"), "--dest", str(dest)], ROOT, env)
    left = snapshot(dest)
    check(
        "install then uninstall leaves the temp dir clean and a second uninstall is safe",
        removed.returncode == 0
        and again.returncode == 0
        and not skill_dir.exists()
        and left == before
        and snapshot(home) == home_before,
    )
    if left != before or removed.returncode != 0 or again.returncode != 0:
        print(removed.stdout)
        print(removed.stderr)
        print(again.stderr)
        print(sorted(left))

    env_dest = script_env(home)
    env_dest["ADOM_WIKI_SKILL_DEST"] = str(other)
    honored = run(["bash", str(SKILL / "install.sh")], ROOT, env_dest)
    check(
        "ADOM_WIKI_SKILL_DEST overrides the default skill directories",
        honored.returncode == 0
        and (other / "opencomponentcards" / "SKILL.md").is_file()
        and snapshot(home) == home_before,
    )
    if honored.returncode != 0 or snapshot(home) != home_before:
        print(honored.stdout)
        print(honored.stderr)
        print(sorted(snapshot(home)))
    run(["bash", str(SKILL / "uninstall.sh")], ROOT, env_dest)

    refused = run(
        ["bash", str(SKILL / "install.sh"), "--dest", "/usr/opencomponentcards-skill-test"],
        ROOT,
        env,
    )
    check(
        "a destination under /usr is refused",
        refused.returncode != 0
        and "usr" in (refused.stderr + refused.stdout).lower()
        and not Path("/usr/opencomponentcards-skill-test").exists(),
    )
finally:
    shutil.rmtree(home, ignore_errors=True)
    shutil.rmtree(dest, ignore_errors=True)
    shutil.rmtree(other, ignore_errors=True)

adom = shutil.which("adom-wiki")
if adom is None:
    print("SKIP adom-wiki pkg lint and pack: adom-wiki is not on PATH")
else:
    if not SKILL.is_dir():
        check("adom-wiki pkg lint and pack", False)
        lint = None
    else:
        lint = run([adom, "pkg", "lint"], SKILL, os.environ.copy(), timeout=60)
    errors = None
    if lint is not None:
        decoder = json.JSONDecoder()
        for blob in (lint.stdout, lint.stderr):
            text = blob.lstrip()
            if not text.startswith("{"):
                continue
            try:
                payload, _end = decoder.raw_decode(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and "errors" in payload:
                errors = payload.get("errors")
                break
    hero_only = (
        isinstance(errors, list)
        and len(errors) == 1
        and "Hero Studio" in errors[0]
        and "No hero" in errors[0]
    )
    if hero_only:
        print("PASS lint's only error is the Hero Studio image, which this package does not ship")
    elif lint is None:
        check("adom-wiki pkg lint reports no package errors", False)
    else:
        check("adom-wiki pkg lint reports no package errors", lint.returncode == 0)
        print(lint.stdout)
        print(lint.stderr)
    pack = None
    if SKILL.is_dir():
        pack = run([adom, "pkg", "pack", "--json"], SKILL, os.environ.copy(), timeout=60)
    tarball = None
    pack_code = 1 if pack is None else pack.returncode
    if pack is not None:
        try:
            tarball = Path(json.loads(pack.stdout).get("data", {}).get("tarball", ""))
        except json.JSONDecodeError:
            tarball = None
    out_dir = ROOT / "out" / "adom-skill"
    moved = None
    if pack_code == 0 and tarball is not None and tarball.is_file():
        out_dir.mkdir(parents=True, exist_ok=True)
        moved = out_dir / tarball.name
        if moved.exists():
            moved.unlink()
        shutil.move(str(tarball), moved)
    members = []
    if moved is not None:
        listed_tar = run(["tar", "tzf", str(moved)], ROOT, os.environ.copy())
        members = [line.strip() for line in listed_tar.stdout.splitlines() if line.strip()]
    shipped = {name[2:] if name.startswith("./") else name for name in members}
    forbidden = [name for name in shipped if name.startswith(("tests/", ".git", "tools/", "cards/", "schema/")) or "/.git" in name]
    check(
        "the pack tarball contains the listed skill files and nothing else from the repo",
        pack_code == 0
        and moved is not None
        and moved.is_file()
        and set(listed) <= shipped
        and not forbidden
        and "page.json" not in shipped
        and not (SKILL / moved.name).exists(),
    )
    if pack_code != 0 or forbidden or set(listed) - shipped:
        if pack is not None:
            print(pack.stdout)
            print(pack.stderr)
        print(members)

print(f"\n{'all tests passed' if not failures else f'{failures} test(s) failed'}")
sys.exit(1 if failures else 0)
