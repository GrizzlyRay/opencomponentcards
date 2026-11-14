#!/bin/bash
# Install the OpenComponentCards skill files. Apache-2.0.
# Copies SKILL.md and README.md into the chosen skills directory.
# Does not copy the OpenComponentCards tree and does not install packages.
set -euo pipefail

PKG_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
SKILL_NAME="opencomponentcards"
FILES=(SKILL.md README.md)

normalize_path() {
  local input="$1"
  local rest part path
  if [ -z "$input" ]; then
    echo "error: empty path" >&2
    return 1
  fi
  case "$input" in
    /*) ;;
    *) input="$(pwd)/$input" ;;
  esac
  path="/"
  rest="${input#/}"
  while [ -n "$rest" ]; do
    part="${rest%%/*}"
    if [ "$rest" = "$part" ]; then
      rest=""
    else
      rest="${rest#*/}"
    fi
    case "$part" in
      ""|.) ;;
      ..)
        if [ "$path" != "/" ]; then
          path="$(dirname "$path")"
        fi
        ;;
      *)
        if [ "$path" = "/" ]; then
          path="/$part"
        else
          path="$path/$part"
        fi
        ;;
    esac
  done
  printf '%s\n' "$path"
}

is_system_path() {
  case "$1" in
    /|/usr|/usr/*|/opt|/opt/*|/bin|/bin/*|/sbin|/sbin/*|/System|/System/*|/Library|/Library/*|/Applications|/Applications/*|/etc|/etc/*|/private/etc|/private/etc/*)
      return 0
      ;;
  esac
  return 1
}

warn_runtime() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "warning: python3 is not on PATH. The tools expect .venv/bin/python in a local clone." >&2
    return 0
  fi
  if ! python3 -c 'import yaml' >/dev/null 2>&1; then
    echo "warning: PyYAML is not installed for python3. The tools expect .venv/bin/python in a local clone." >&2
  fi
}

DRY=0
DESTS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY=1
      shift
      ;;
    --dest)
      if [ "$#" -lt 2 ]; then
        echo "error: --dest needs a directory" >&2
        exit 1
      fi
      DESTS+=("$2")
      shift 2
      ;;
    --dest=*)
      DESTS+=("${1#--dest=}")
      shift
      ;;
    *)
      echo "error: unknown argument $1" >&2
      exit 1
      ;;
  esac
done

if [ "${#DESTS[@]}" -eq 0 ]; then
  if [ -n "${ADOM_WIKI_SKILL_DEST:-}" ]; then
    DESTS+=("$ADOM_WIKI_SKILL_DEST")
  else
    DESTS+=("${HOME}/.claude/skills")
    DESTS+=("${CODEX_HOME:-$HOME/.codex}/skills")
  fi
fi

warn_runtime

for dest_raw in "${DESTS[@]}"; do
  dest="$(normalize_path "$dest_raw")"
  if is_system_path "$dest"; then
    echo "error: refusing system path $dest" >&2
    exit 1
  fi
  skill_dir="$dest/$SKILL_NAME"
  if [ "$DRY" -eq 1 ]; then
    echo "dry-run: install $SKILL_NAME into $skill_dir"
    for name in "${FILES[@]}"; do
      echo "dry-run: copy $PKG_DIR/$name -> $skill_dir/$name"
    done
    continue
  fi
  mkdir -p "$skill_dir"
  for name in "${FILES[@]}"; do
    cp "$PKG_DIR/$name" "$skill_dir/$name"
  done
  stamp="$skill_dir/.installed-by-opencomponentcards"
  printf '%s\n' "${FILES[@]}" > "$stamp"
  echo "installed $SKILL_NAME into $skill_dir"
done
