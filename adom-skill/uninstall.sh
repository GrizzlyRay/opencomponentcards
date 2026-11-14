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

# Resolve symlinks with pwd -P. A missing tail is kept. macOS realpath and
# readlink -f both fail on a path that does not exist yet, and realpath has
# no portable -m flag.
_resolve_real_path() {
  local input="$1"
  local depth="${2:-0}"
  local path missing part parent target
  if [ "$depth" -gt 40 ]; then
    echo "error: too many symlinks in $input" >&2
    return 1
  fi
  path="$(normalize_path "$input")" || return 1
  missing=""
  while [ ! -e "$path" ] && [ ! -L "$path" ] && [ "$path" != "/" ]; do
    part="$(basename "$path")"
    if [ -n "$missing" ]; then
      missing="${part}/${missing}"
    else
      missing="$part"
    fi
    path="$(dirname "$path")"
  done
  if [ -L "$path" ]; then
    target="$(readlink "$path")" || return 1
    case "$target" in
      /*) ;;
      *)
        parent="$(dirname "$path")"
        parent="$(_resolve_real_path "$parent" "$((depth + 1))")" || return 1
        if [ "$parent" = "/" ]; then
          target="/${target}"
        else
          target="${parent}/${target}"
        fi
        ;;
    esac
    if [ -n "$missing" ]; then
      if [ "$target" = "/" ]; then
        target="/${missing}"
      else
        target="${target}/${missing}"
      fi
    fi
    target="$(_resolve_real_path "$target" "$((depth + 1))")" || return 1
    printf '%s\n' "$target"
    return 0
  fi
  if [ -d "$path" ]; then
    path="$(CDPATH='' cd -P -- "$path" && pwd -P)" || return 1
  elif [ -e "$path" ]; then
    part="$(basename "$path")"
    parent="$(dirname "$path")"
    parent="$(CDPATH='' cd -P -- "$parent" && pwd -P)" || return 1
    if [ "$parent" = "/" ]; then
      path="/${part}"
    else
      path="${parent}/${part}"
    fi
  fi
  if [ -n "$missing" ]; then
    if [ "$path" = "/" ]; then
      path="/${missing}"
    else
      path="${path}/${missing}"
    fi
    path="$(normalize_path "$path")" || return 1
  fi
  printf '%s\n' "$path"
}

resolve_real_path() {
  _resolve_real_path "$1" 0
}

path_is_under() {
  local path="$1"
  local root="$2"
  if [ -z "$root" ] || [ "$root" = "/" ]; then
    return 1
  fi
  if [ "$path" = "$root" ]; then
    return 0
  fi
  case "$path" in
    "$root"/*) return 0 ;;
  esac
  return 1
}

is_system_path() {
  case "$1" in
    /|/usr|/usr/*|/bin|/bin/*|/sbin|/sbin/*|/etc|/etc/*|/opt|/opt/*|/var|/var/*|/private|/private/*|/System|/System/*|/Library|/Library/*|/Applications|/Applications/*)
      return 0
      ;;
  esac
  return 1
}

is_home_path() {
  local resolved
  if [ -z "${HOME:-}" ]; then
    return 1
  fi
  resolved="$(resolve_real_path "$HOME")" || return 1
  path_is_under "$1" "$resolved"
}

# On macOS /tmp is /private/tmp and the per-user temp dir resolves under
# /private/var/folders. Refuse /private and /var, then allow those temp
# trees, or a normal temp dest is refused after the real path is known.
is_temp_path() {
  local path="$1"
  local candidate resolved
  for candidate in /tmp /var/folders /private/var/folders; do
    if [ -d "$candidate" ]; then
      resolved="$(resolve_real_path "$candidate")" || continue
      if path_is_under "$path" "$resolved"; then
        return 0
      fi
    fi
  done
  if [ -n "${TMPDIR:-}" ] && [ -d "${TMPDIR%/}" ]; then
    resolved="$(resolve_real_path "${TMPDIR%/}")" || return 1
    case "$resolved" in
      /|/usr|/bin|/sbin|/etc|/opt|/var|/private|/System|/Library|/Applications)
        return 1
        ;;
    esac
    if path_is_under "$path" "$resolved"; then
      return 0
    fi
  fi
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
  dest="$(resolve_real_path "$dest_raw")" || exit 1
  if ! is_home_path "$dest" && ! is_temp_path "$dest" && is_system_path "$dest"; then
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
