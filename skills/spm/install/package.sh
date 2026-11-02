#!/bin/sh
# Build the two handoff zips from this repository:
#   spm.zip         for the PM: unzip, then `sh spm/install.sh`
#   spm-verify.zip  for engineering: the checker, its sha256 and VERIFY.md
# Usage: sh package.sh [out.zip]     (default: ~/Desktop/spm.zip; spm-verify.zip goes next to it)
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
SKILL=$(cd "$HERE/.." && pwd)
REPO=$(cd "$SKILL/../.." && pwd)
OUT="${1:-$HOME/Desktop/spm.zip}"
case "$OUT" in /*) ;; *) OUT="$(pwd)/$OUT" ;; esac
mkdir -p "$(dirname "$OUT")"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

sha256() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1"; else sha256sum "$1"; fi | cut -d' ' -f1; }

# The layout install.sh expects in the PM's zip (see its header).
P="$STAGE/spm"
mkdir -p "$P/agents" "$P/hooks"
cp -R "$SKILL" "$P/spm"
rm -rf "$P/spm/tests" "$P/spm/install"
find "$P" \( -name '__pycache__' -o -name '.DS_Store' \) -prune -exec rm -rf {} +
cp "$REPO/agents/spm-red-team.md" "$P/agents/"
cp "$SKILL/hooks/spm-trigger.py" "$P/hooks/"
cp "$HERE/install.sh" "$HERE/uninstall.sh" "$P/"
cp "$HERE/PM-README.md" "$P/README.md"
rm -f "$OUT"
(cd "$STAGE" && zip -qr "$OUT" spm)
echo "wrote $OUT"

# Engineering gets only the verifier, its checksum and how to use it.
VOUT="$(dirname "$OUT")/spm-verify.zip"
V="$STAGE/spm-verify"
mkdir -p "$V"
cp "$SKILL/scripts/check_spec.py" "$HERE/VERIFY.md" "$V/"
sha256 "$V/check_spec.py" > "$V/check_spec.py.sha256"
rm -f "$VOUT"
(cd "$STAGE" && zip -qr "$VOUT" spm-verify)
echo "wrote $VOUT (check_spec.py sha256 $(cat "$V/check_spec.py.sha256")) - send this checksum in the handoff message"
