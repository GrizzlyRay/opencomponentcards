#!/bin/bash
# Remove the OpenComponentCards skill files this package installed. Apache-2.0.
# Deletes only the recorded files and is safe to run twice.
set -euo pipefail

SKILL_NAME="opencomponentcards"
STAMP_NAME=".installed-by-opencomponentcards"

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

for dest_raw in "${DESTS[@]}"; do
  dest="$(normalize_path "$dest_raw")"
  if is_system_path "$dest"; then
    echo "error: refusing system path $dest" >&2
    exit 1
  fi
  skill_dir="$dest/$SKILL_NAME"
  stamp="$skill_dir/$STAMP_NAME"
  if [ ! -f "$stamp" ]; then
    if [ "$DRY" -eq 1 ]; then
      echo "dry-run: nothing to remove under $skill_dir"
    else
      echo "nothing to remove under $skill_dir"
    fi
    continue
  fi
  while IFS= read -r rel || [ -n "$rel" ]; do
    [ -n "$rel" ] || continue
    case "$rel" in
      /*|*..*)
        echo "error: bad installed path $rel" >&2
        exit 1
        ;;
    esac
    target="$skill_dir/$rel"
    if [ "$DRY" -eq 1 ]; then
      echo "dry-run: would remove $target"
    else
      rm -f "$target"
    fi
  done < "$stamp"
  if [ "$DRY" -eq 1 ]; then
    echo "dry-run: would remove $stamp"
  else
    rm -f "$stamp"
    rmdir "$skill_dir" 2>/dev/null || true
  fi
done
