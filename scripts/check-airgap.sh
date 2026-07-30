#!/usr/bin/env bash
# check-airgap.sh — Fail CI if a shipped runtime tool gains a new outbound
# network call to a host other than localhost/the local Ollama endpoint.
#
# Scope: config/includes.chroot/usr/local/bin/* — the scripts that run on a
# booted NeurOS system. Build-time hooks (config/hooks/live/*) legitimately
# fetch packages from the internet while building the ISO, same as any Linux
# distro's package manager; they are not part of the running system's
# air-gap guarantee and are intentionally excluded here.
#
# Any literal http(s):// URL whose host is not localhost/127.0.0.1/0.0.0.0
# and is not on the allowlist below fails the check. This catches new
# outbound calls; it does not try to catch every possible obfuscation.
#
# Usage: ./scripts/check-airgap.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

BIN_DIR="config/includes.chroot/usr/local/bin"

# host -> file it's allowed in (one pair per line: "file:host")
# Each entry here is a known, reviewed, user-invoked exception to the
# air-gap guarantee. Adding a new host here is a deliberate decision —
# it should show up in code review.
ALLOWLIST="
neuros-music:www.youtube.com
neuros-network:google.com
neuros-network:1.1.1.1
neuros-speak:github.com
"

FOUND=0

# Literal-URL scanning (below) misses outbound calls made through a
# third-party HTTP client whose target URL is built at runtime (env
# var, f-string, config value) rather than typed as a literal in the
# file. stdlib urllib is used throughout these tools to talk to the
# local Ollama endpoint, so importing it is not itself a signal.
# `requests`/`httpx` are not stdlib, are not used anywhere in this
# tree today, and exist only to make arbitrary HTTP calls ergonomic -
# so any import of one is a hard fail here regardless of URL literals.
while IFS= read -r -d '' f; do
  name="$(basename "$f")"
  match="$(grep -nE '^\s*(import|from)\s+(requests|httpx)\b' "$f" 2>/dev/null || true)"
  if [ -n "$match" ]; then
    echo "AIR-GAP VIOLATION: $name imports a non-stdlib HTTP client not used " \
         "anywhere else in this tree (can make outbound calls with a " \
         "runtime-built URL that the literal-URL scan below can't see):"
    echo "$match" | sed "s#^#  $name:#"
    FOUND=1
  fi
done < <(find "$BIN_DIR" -type f -not -name '*.pyc' -not -path '*/__pycache__/*' -print0)

# Raw-socket / DNS-tool scanning: catches outbound calls that contain no
# http(s):// literal at all, e.g. socket.create_connection(("1.1.1.1", 53))
# or shelling out to nslookup/dig/host with a literal target host. The
# URL scan below can't see either of these.
while IFS= read -r -d '' f; do
  name="$(basename "$f")"
  while IFS=: read -r line host; do
    [ -z "${host:-}" ] && continue
    case "$host" in
      localhost|127.0.0.1|0.0.0.0) continue ;;
      -*|+*) continue ;;  # a CLI flag (e.g. dig's "+short"), not a hostname
    esac

    allowed=0
    while IFS=: read -r al_file al_host; do
      [ -z "${al_file:-}" ] && continue
      if [ "$name" = "$al_file" ] && [ "$host" = "$al_host" ]; then
        allowed=1
        break
      fi
    done <<< "$ALLOWLIST"

    if [ "$allowed" -eq 0 ]; then
      echo "AIR-GAP VIOLATION: $name:$line makes a raw network call to non-local host '$host'"
      FOUND=1
    fi
  done < <( { grep -noP "socket\.(create_connection|connect)\(\(\s*[\"']\K[^\"']+" "$f" 2>/dev/null || true
              grep -noP "\[\s*[\"'](nslookup|dig|host)[\"']\s*,\s*[\"']\K[^\"']+" "$f" 2>/dev/null || true; } )
done < <(find "$BIN_DIR" -type f -not -name '*.pyc' -not -path '*/__pycache__/*' -print0)

while IFS= read -r -d '' f; do
  name="$(basename "$f")"
  while IFS=: read -r line url; do
    [ -z "${url:-}" ] && continue
    host="$(echo "$url" | sed -E 's#https?://##; s#[/:].*##')"
    case "$host" in
      localhost|127.0.0.1|0.0.0.0|"") continue ;;
      *.w3.org|w3.org) continue ;;  # SVG XML namespace URI, not fetched
    esac
    # Skip f-string interpolated hosts (e.g. http://{config[host]}) -- these
    # resolve to the local Ollama endpoint at runtime, not a literal host.
    case "$host" in
      \{*) continue ;;
    esac
    # Skip placeholder text like "https://..." in --help docstrings
    case "$url" in
      *"..."*) continue ;;
    esac

    allowed=0
    while IFS=: read -r al_file al_host; do
      [ -z "${al_file:-}" ] && continue
      if [ "$name" = "$al_file" ] && [ "$host" = "$al_host" ]; then
        allowed=1
        break
      fi
    done <<< "$ALLOWLIST"

    if [ "$allowed" -eq 0 ]; then
      echo "AIR-GAP VIOLATION: $name:$line calls external host '$host' ($url)"
      FOUND=1
    fi
  done < <(grep -noE "https?://[^\"'\` \\)]+" "$f" 2>/dev/null || true)
done < <(find "$BIN_DIR" -type f -not -name '*.pyc' -not -path '*/__pycache__/*' -print0)

if [ "$FOUND" -ne 0 ]; then
  echo ""
  echo "One or more shipped tools call an external host that isn't on the"
  echo "air-gap allowlist in scripts/check-airgap.sh. If this is intentional"
  echo "(a new opt-in, user-invoked feature), add it to the ALLOWLIST with a"
  echo "one-line justification in the same PR. Otherwise, remove the call."
  exit 1
fi

echo "Air-gap check passed: no unreviewed outbound network calls found in $BIN_DIR."
