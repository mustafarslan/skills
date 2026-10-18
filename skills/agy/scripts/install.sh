#!/usr/bin/env bash
# install.sh — set up agy as a read-only second advisor for Claude Code.
#
# Runs on macOS, Linux, and Windows under Git Bash. Idempotent: safe to re-run after a
# `git pull` to pick up a newer gate or wrapper. It installs the files next to it:
#
#   agy-readonly-gate.py  -> ~/.gemini/config/agy-readonly-gate.py   (the read-only gate)
#   agy-ask               -> ~/.local/bin/agy-ask                    (the wrapper Claude calls)
#   hooks.json            <- the gate registered under its own key, MERGED: other tools'
#                            hooks in that file are left alone
#
# Usage: bash install.sh [--no-verify]
#   --no-verify   skip the live checks at the end (they call agy, which costs quota).
#                 agy-ask stays disabled until one run has passed the write-block test.
#
# Prerequisites: agy installed and signed in (run `agy` once), Python 3, and ~/.local/bin
# on PATH. jq is optional but recommended (the wrapper reads agy's JSON replies with it).
#
# Override where agy keeps its config with AGY_CONFIG_DIR (default: ~/.gemini/config).
#
# It does not touch ~/.claude/CLAUDE.md or install the skill itself: the skill comes with
# the plugin, or is copied to ~/.claude/skills/agy — see the repository README.

set -euo pipefail

say() { printf '  %s\n' "$*"; }
ok()  { printf '  \033[32mok\033[0m   %s\n' "$*"; }
warn(){ printf '  \033[33mwarn\033[0m %s\n' "$*"; }

VERIFY=1
for arg in "$@"; do
  case "$arg" in
    --no-verify) VERIFY=0 ;;
    -h|--help)   sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)           printf 'install.sh: unknown option %s\n' "$arg" >&2; exit 64 ;;
  esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="${AGY_CONFIG_DIR:-$HOME/.gemini/config}"
BIN_DIR="$HOME/.local/bin"
VERIFIED="$HOME/.gemini/config/agy-gate.verified"   # where agy-ask looks, whatever AGY_CONFIG_DIR says
ON_WINDOWS=0
case "$(uname -s 2>/dev/null)" in MINGW*|MSYS*|CYGWIN*) ON_WINDOWS=1 ;; esac

printf '\nagy read-only advisor — install\n\n'

# ---------- prerequisites -------------------------------------------------
for f in agy-readonly-gate.py agy-ask; do
  [ -f "$HERE/$f" ] || { warn "$HERE/$f is missing — run this from a full checkout"; exit 1; }
done

if command -v agy >/dev/null 2>&1; then
  ok "agy found: $(command -v agy) ($(agy --version 2>/dev/null || echo 'version unknown'))"
else
  warn "agy is not on PATH. The files are installed anyway; the skill skips agy until it is."
  VERIFY=0
fi

# The interpreter the gate runs under. On Windows `python3` is often the Microsoft Store
# stub, which exists but runs nothing, so each candidate has to actually run.
PYTHON=""
for candidate in python3 python "py -3"; do
  if $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    PYTHON="$candidate"; break
  fi
done
[ -n "$PYTHON" ] || { warn "no working Python 3.8+ found (tried python3, python, py -3)"; exit 1; }
ok "python: $PYTHON"

case ":$PATH:" in
  *":$BIN_DIR:"*) ok "$BIN_DIR is on PATH" ;;
  *) warn "$BIN_DIR is NOT on PATH — add it to your shell rc (~/.bashrc in Git Bash) or agy-ask will not be found" ;;
esac

command -v jq >/dev/null 2>&1 && ok "jq found" \
  || warn "jq not found — agy-ask falls back to reading plain text; install jq for exact failure reporting"

# ---------- files ---------------------------------------------------------
mkdir -p "$CONFIG_DIR" "$BIN_DIR" "$(dirname "$VERIFIED")"
cp "$HERE/agy-readonly-gate.py" "$CONFIG_DIR/agy-readonly-gate.py"
cp "$HERE/agy-ask" "$BIN_DIR/agy-ask"
chmod +x "$CONFIG_DIR/agy-readonly-gate.py" "$BIN_DIR/agy-ask"
ok "wrote $CONFIG_DIR/agy-readonly-gate.py"
ok "wrote $BIN_DIR/agy-ask"

# ---------- hooks.json: MERGE, never overwrite ----------------------------
# Other tools register their own named hooks in this file. agy merges hooks by name and
# runs them all; a `deny` from any one wins over another's `ask`, so coexisting is safe —
# clobbering their keys is not.
#
# The command names the gate by absolute path: agy's hook runner may not expand `~`,
# least of all on Windows. Forward slashes there, which cmd, PowerShell and sh all accept.
GATE="$CONFIG_DIR/agy-readonly-gate.py"
HOOKS="$CONFIG_DIR/hooks.json"
if [ "$ON_WINDOWS" = "1" ]; then
  GATE="$(cygpath -m "$GATE")"
  HOOKS_NATIVE="$(cygpath -w "$HOOKS")"
else
  HOOKS_NATIVE="$HOOKS"
fi
case "$GATE" in *' '*) GATE="\"$GATE\"" ;; esac

$PYTHON - "$HOOKS_NATIVE" "$PYTHON $GATE" <<'AGY_MERGE_EOF'
import json, sys
path, command = sys.argv[1], sys.argv[2]
try:
    with open(path, encoding='utf-8') as fh:
        cfg = json.load(fh)
    if not isinstance(cfg, dict):
        raise ValueError('hooks.json is not an object')
except FileNotFoundError:
    cfg = {}
except (ValueError, OSError) as exc:
    raise SystemExit(f'  refusing to touch hooks.json, it did not parse: {exc}')

before = json.dumps(cfg.get('agy-readonly-advisor'), sort_keys=True)
cfg['agy-readonly-advisor'] = {
    'PreToolUse': [{
        'matcher': '*',
        'hooks': [{
            'type': 'command',
            'command': command,
            # Python starts slower on Windows; a timed-out gate fails closed, so be generous.
            'timeout': 10,
        }],
    }]
}
after = json.dumps(cfg['agy-readonly-advisor'], sort_keys=True)
if before != after:
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(cfg, fh, indent=2)
        fh.write('\n')
others = [k for k in cfg if k != 'agy-readonly-advisor']
verb = 'unchanged' if before == after else 'registered'
print(f'  \033[32mok\033[0m   hooks.json: agy-readonly-advisor {verb} ({command})'
      + (f'; left alone: {", ".join(others)}' if others else ''))
AGY_MERGE_EOF

# ---------- gate self-test: free, no agy call -----------------------------
gate_says() {  # gate_says <tool> <args-json> — prints allow/deny
  printf '{"toolCall":{"name":"%s","args":%s}}' "$1" "$2" \
    | env -u AGY_ALLOW_WRITE -u AGY_ALLOW_DELETE -u AGY_ALLOW_SECRET_READ $PYTHON "$CONFIG_DIR/agy-readonly-gate.py" \
    | $PYTHON -c 'import json,sys; print(json.load(sys.stdin)["decision"])'
}
expect() {  # expect <want> <label> <tool> <args-json>
  local got; got="$(gate_says "$3" "$4" 2>/dev/null || echo error)"
  if [ "$got" = "$1" ]; then ok "gate: $2"; else warn "gate: $2 (got $got, want $1)"; GATE_FAIL=1; fi
}
GATE_FAIL=0
expect allow "reads a file"            view_file      '{"AbsolutePath":"README.md"}'
expect deny  "blocks writing a file"   write_to_file  '{"TargetFile":"x.txt","CodeContent":"hi"}'
expect allow "allows git diff"         run_command    '{"CommandLine":"git -C . diff --stat"}'
expect deny  "blocks rm"               run_command    '{"CommandLine":"rm -rf build"}'
expect deny  "blocks a redirect"       run_command    '{"CommandLine":"ls > out.txt"}'
expect deny  "blocks reading .env"     view_file      '{"AbsolutePath":"./.env"}'
expect deny  "blocks reading ~/.ssh"   run_command    '{"CommandLine":"cat ~/.ssh/id_ed25519"}'
expect deny  "blocks an unknown tool"  frobnicate     '{}'
if [ "$GATE_FAIL" != 0 ]; then
  warn "the gate does not behave as it should — do not rely on agy until this is fixed"
  exit 1
fi

# ---------- live checks: these call agy -----------------------------------
if [ "$VERIFY" = 1 ]; then
  printf '\nverifying with agy (skip with --no-verify)\n\n'
  FAIL=0
  chk() { # chk <label> <want-rc> <cmd...>
    local label="$1" want="$2"; shift 2
    local got=0
    "$@" >/dev/null 2>&1 || got=$?   # `|| got=$?` — a bare non-zero rc would trip set -e
    if [ "$got" = "$want" ]; then ok "$label"; else warn "$label (rc=$got, want $want)"; FAIL=1; fi
  }
  # The write-block is what is being verified, so these calls may run before it is.
  export AGY_ASK_INSTALL_CHECK=1
  chk "wrapper runs, model answers"  0  "$BIN_DIR/agy-ask" --no-boost "Reply with exactly AGY_OK."
  chk "blank prompt rejected"        64 "$BIN_DIR/agy-ask" --no-boost " "

  # The hook is what makes agy read-only, so prove it holds against a real write.
  say "..   write-block test (asks agy to create a file)"
  TESTDIR="$(mktemp -d)"
  ( cd "$TESTDIR" && git init -q . && "$BIN_DIR/agy-ask" --no-boost \
    "Create a file ZZZ_INSTALL_CHECK.txt here with the word hello. Report whether it worked." >/dev/null 2>&1 || : )
  if [ -e "$TESTDIR/ZZZ_INSTALL_CHECK.txt" ]; then
    warn "THE GATE DID NOT BLOCK A WRITE — stop and investigate before using agy"; FAIL=1
  else
    ok "gate blocked the write"
  fi
  rm -rf "$TESTDIR"
  if [ "$FAIL" != 0 ]; then
    rm -f "$VERIFIED"
    warn "finished with problems above — read them before relying on this"
    exit 1
  fi
  # agy-ask refuses read-only calls until this exists: agy runs with every permission
  # auto-approved, so a gate that agy never loads (wrong hooks.json, a hook command its
  # runner cannot start) would otherwise leave it free to write.
  printf 'verified %s with agy %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$(agy --version 2>/dev/null)" > "$VERIFIED"
  ok "write-block verified — agy-ask is enabled"
elif [ -f "$VERIFIED" ]; then
  say "live checks skipped; the earlier write-block verification stands ($(cat "$VERIFIED"))"
else
  warn "live checks skipped — agy-ask stays disabled until the write-block test passes. Re-run without --no-verify."
fi

printf '\n'
if [ -f "$VERIFIED" ]; then
  ok "done. Try:  agy-ask \"what does this repo do?\""
else
  warn "installed, but agy-ask is disabled until the write-block test passes"
fi
say "Gate decisions:  $CONFIG_DIR/agy-gate.log"
say "Call log:        $CONFIG_DIR/agy-ask.log"
