#!/usr/bin/env python3
"""PreToolUse gate for the Antigravity CLI (agy).

agy is used here as a READ-ONLY second advisor. This hook is the machine gate that
enforces it: every tool call agy attempts is checked against an allowlist, and
anything that could write, delete, or otherwise change the world is hard-denied.

Fail-closed by design: unknown tools are denied, unparseable input is denied, and
an unexpected exception is denied.

Escape hatch: set AGY_ALLOW_WRITE=1 in the environment to disable the gate, and
additionally AGY_ALLOW_DELETE=1 to permit destructive operations.

Reading is allowed, with one exception: places where secrets are kept. What an advisor
reads goes to the model, so `.env*` files, `*.pem`, `*.key`, and everything under
`~/.ssh`, `~/.aws` and `~/.config` are denied to every tool, read tools and shell alike,
and so is a search, a listing or a wildcard that starts ABOVE one of those directories
(the home directory, `/`), since it would reach into them. This holds with
AGY_ALLOW_WRITE=1 too. Its own escape hatch is AGY_ALLOW_SECRET_READ=1.

What this cannot stop: a recursive search of the workspace itself still shows matching
lines of a `.env` that lies in it, and `git log -p` shows whatever was committed. A
secret that is in the repository is in the repository.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time

LOG_PATH = os.path.expanduser('~/.gemini/config/agy-gate.log')

# Tools that only observe. Everything not listed here is denied.
READ_TOOLS = frozenset(
    {
        'view_file',
        'view_file_outline',
        'view_code_item',
        'view_content_chunk',
        'grep_search',
        'code_search',
        'internal_search',
        'find',
        'finda',
        'find_all_references',
        'list_directory',
        'list_resources',
        'read_notebook',
        'read_resource',
        'read_terminal',
        'read_url_content',
        'read_browser_page',
        'retrieve_content',
        'retrieve_memory',
        'search_web',
        'tool_search',
        'command_status',
        'directory_rules',
        'conversation_history',
        'view_code_item',
        'mquery',
        'moma',
        # Names agy actually emits, which differ from the step-type enum.
        'list_dir',
        'find_by_name',
        'codebase_search',
        'semantic_search',
        'view_line_range',
        'search_in_file',
        'view_web_document_content',
        'read_web_page',
        'grep',
        'glob',
    }
)

# A read tool we have not met yet should not cost a turn. Allow unknown tools whose
# name is unambiguously read-shaped, unless it also carries a mutating verb.
READ_PREFIXES = ('view_', 'read_', 'list_', 'find_', 'search_', 'grep_', 'get_', 'inspect_')
MUTATING_WORDS = (
    'write', 'edit', 'replace', 'delete', 'remove', 'create', 'move', 'rename',
    'patch', 'apply', 'commit', 'deploy', 'install', 'run', 'exec', 'update',
    'insert', 'append', 'set_', 'put_', 'post_', 'send_', 'kill', 'restart',
)


# ---- places where secrets are kept: denied to every tool, reading included --------------------

HOME = os.path.expanduser('~')
SECRET_DIRS = ('.ssh', '.aws', '.config')            # under the home directory
SECRET_SUFFIXES = ('.pem', '.key')                   # by name, anywhere
SECRET_PREFIX = '.env'                               # `.env`, `.env.local`, `.envrc`: by name, anywhere
GLOB = re.compile(r'[*?\[]')
# Keys of a tool's arguments whose value is a place, whatever it looks like.
PLACE_KEYS = ('path', 'file', 'dir', 'uri', 'target', 'folder', 'root', 'cwd')
# Commands whose first plain argument is a pattern or a script, not a place.
PATTERN_FIRST = frozenset({'rg', 'grep', 'awk', 'sed'})


def _where(path: str, cwd: str) -> str:
    """The place a path names: `~` expanded, relative to `cwd`, links followed, and in lower case
    (the usual macOS and Windows file systems do not tell `.SSH` from `.ssh`)."""
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    return os.path.realpath(os.path.normpath(path)).lower()


def _inside(path: str, directory: str) -> bool:
    return path == directory or path.startswith(directory.rstrip(os.sep) + os.sep)


def secret_place(raw: str, cwd: str, by_name: bool = True) -> str:
    """Why `raw` may not be read, or '' if it may. `raw` is one argument: a path, `file://path`,
    or git's `revision:path`. Without `by_name` only the protected directories are looked at: for a
    word that is probably a search term (`rg .env src` looks for the text `.env`)."""
    if not raw or raw.startswith(('http://', 'https://')):
        return ''
    candidates = [raw[7:] if raw.startswith('file://') else raw]
    if ':' in raw and not raw.startswith(('/', 'file://')):
        candidates.append(raw.rsplit(':', 1)[1])                 # `HEAD:.env`, `main:deploy/prod.pem`
    protected = [(f'~/{name}', _where(os.path.join(HOME, name), cwd)) for name in SECRET_DIRS]
    for candidate in candidates:
        if not candidate:
            continue
        name = os.path.basename(candidate.rstrip('/')).lower()
        if by_name and (name.startswith(SECRET_PREFIX) or name.endswith(SECRET_SUFFIXES)):
            return f'`{name}` is a kind of file that holds secrets'
        fixed = GLOB.split(candidate, 1)[0]
        wildcard = fixed != candidate
        if wildcard and not fixed.endswith('/'):
            fixed = os.path.dirname(fixed) or '.'                # `~/.s*` starts in `~`, not in `~/.s`
        place = _where(fixed, cwd)
        for shown, directory in protected:
            if _inside(place, directory):
                return f'`{candidate}` is inside {shown}, where secrets are kept'
            if _inside(directory, place):
                # A search, a listing or a wildcard from above a protected directory reaches into it.
                return f'`{candidate}` is above {shown}, where secrets are kept: name a place inside the project'
    return ''


def _strings(value, key: str = ''):
    """Every string in a tool's arguments, with the key it was found under."""
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for name, inner in value.items():
            yield from _strings(inner, str(name))
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _strings(inner, key)


def secret_in_arguments(args: dict) -> str:
    """For any tool but the shell: the first argument that names a place where secrets are kept.
    A value is taken for a place when its key says so or when it is written like one; a search
    term such as `api.key` is not a place."""
    cwd = os.getcwd()
    for key, value in _strings(args):
        named_as_place = any(word in key.lower() for word in PLACE_KEYS)
        written_as_place = value.startswith(('/', '~', './', '../', 'file://'))
        if named_as_place or written_as_place:
            why = secret_place(value, cwd)
            if why:
                return why
    return ''


def secret_in_command(command: str, args: dict) -> str:
    """For the shell: the first word of the command that names a place where secrets are kept."""
    cwd = next((args[key] for key in ('Cwd', 'cwd', 'WorkingDirectory', 'workdir') if isinstance(args.get(key), str) and args[key]), os.getcwd())
    try:
        tokens = shell_tokens(command)
    except ValueError:
        return ''                                                # unparseable: check_shell denies it anyway
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token == '|':
            segments.append([])
        else:
            segments[-1].append(token)
    for segment in segments:
        if not segment:
            continue
        head = os.path.basename(segment[0])
        pattern_to_skip = head in PATTERN_FIRST
        for token in segment[1:]:
            if token.startswith('-'):
                _, _, value = token.partition('=')               # `--file=PATH`
                if value:
                    why = secret_place(value, cwd)
                    if why:
                        return why
                continue
            # The first plain word of grep, rg, sed and awk is usually the search term or the script. It is
            # still not allowed to point into a protected directory: after `-f` it is a file that is read.
            why = secret_place(token, cwd, by_name=not pattern_to_skip)
            pattern_to_skip = False
            if why:
                return why
    return ''


def looks_read_only(tool: str) -> bool:
    if any(word in tool for word in MUTATING_WORDS):
        return False
    return tool.startswith(READ_PREFIXES)

# ---- the Blender and Godot MCP servers: reading only -------------------------------------------
# So agy can inspect an open .blend file or Godot project through their MCP servers. Each server's
# tool names are listed here one by one; nothing else on those servers passes. Running code
# (execute_blender_code), rendering to a file, moving the user's editor view, and every op that
# writes, runs or plays are denied. A `*_manage` tool passes only with one of the ops named for it.
MCP_SERVER_PREFIX = re.compile(r'^(?:mcp_*[:/.-]?_*)?(?:blender|godot(?:[-_]ai)?)(?:_+|[:/.-])')
MCP_READ_TOOLS = frozenset(
    {
        # Blender (projects.blender.org/lab/blender_mcp)
        'get_blendfile_summary_datablocks',
        'get_blendfile_summary_datablocks_for_cli',
        'get_blendfile_summary_missing_files',
        'get_blendfile_summary_missing_files_for_cli',
        'get_blendfile_summary_of_linked_libraries',
        'get_blendfile_summary_of_linked_libraries_for_cli',
        'get_blendfile_summary_path_info',
        'get_blendfile_summary_path_info_for_cli',
        'get_blendfile_summary_usage_guess',
        'get_blendfile_summary_usage_guess_for_cli',
        'get_object_detail_summary',
        'get_objects_summary',
        'get_python_api_docs',
        'get_screenshot_of_area_as_image',
        'get_screenshot_of_window_as_image',
        'get_screenshot_of_window_as_json',
        'search_api_docs',
        'search_manual_docs',
        # Godot (godot-ai)
        'editor_state',
        'scene_get_hierarchy',
        'node_get_properties',
        'node_find',
        'logs_read',
    }
)
MCP_READ_OPS = {
    'scene_manage': {'get_roots'},
    'script_manage': {'read', 'find_symbols'},
    'filesystem_manage': {'read_text', 'search'},
    'project_manage': {'settings_get'},
    'animation_manage': {'list', 'get', 'validate'},
    'resource_manage': {'search', 'load', 'inspect', 'get_info'},
    'editor_manage': {'state'},
}
# A screenshot passes as long as it does not swing the editor camera round to frame something.
MCP_CAMERA_KEYS = ('view_target', 'azimuth', 'elevation', 'fov', 'coverage')


MCP_READ_SERVERS = ('blender', 'godot')


def mcp_read_only(tool: str, args: dict) -> bool:
    """True when `tool` is a reading call on the Blender or Godot MCP server. agy sends MCP calls as
    `call_mcp_tool` with {ServerName, ToolName, Arguments} (seen 2026-10-17); a prefixed tool name
    (`mcp_blender_...`) is accepted too."""
    if tool == 'call_mcp_tool':
        if str(args.get('ServerName', '')).lower() not in MCP_READ_SERVERS:
            return False
        inner = args.get('Arguments')
        return mcp_read_only(str(args.get('ToolName', '')).lower(), inner if isinstance(inner, dict) else {})
    name = MCP_SERVER_PREFIX.sub('', tool, count=1)
    if name in MCP_READ_TOOLS:
        return True
    if name == 'editor_screenshot':
        return not any(args.get(k) not in (None, '', False) for k in MCP_CAMERA_KEYS)
    if name in MCP_READ_OPS:
        return str(args.get('op', '')).lower() in MCP_READ_OPS[name]
    return False


# Bookkeeping / control-flow steps that are not world-changing tool calls.
BOOKKEEPING = frozenset(
    {
        'ask_question',
        'checkpoint',
        'critique',
        'ephemeral_message',
        'error_message',
        'findings',
        'finish',
        'generic',
        'knowledge_artifacts',
        'knowledge_generation',
        'notify_user',
        'plan_input',
        'planner_response',
        'proposal_feedback',
        'suggested_responses',
        'system_message',
        'task_boundary',
        'tool_call_choice',
        'tool_call_proposal',
        'trajectory_choice',
        'trajectory_search',
        'user_input',
        'wait',
        'dummy',
        'unspecified',
        # /boost fans out through subagents; denying this would pin boost to Solo.
        # `schedule` is the orchestrator's wait-for-subagent step — denying it makes
        # print mode return the interim "I have delegated..." message instead of the answer.
        'invoke_subagent',
        'browser_subagent',
        'schedule',
        # The boost orchestrator's own bookkeeping. These move agy's internal task state,
        # never the filesystem, and every tool a subagent uses still passes this gate
        # independently. Denying them is what made boost return an interim note.
        'manage_task',
        'manage_subagents',
        'task_manager',
        'update_plan',
        'create_plan',
        'manager_feedback',
        'brain_update',
        'memory',
    }
)

SHELL_TOOLS = frozenset({'run_command', 'shell_exec'})

# Keys the command string might live under, across tool shapes.
COMMAND_KEYS = ('CommandLine', 'commandLine', 'command', 'Command', 'cmd', 'script')

# First tokens permitted in a shell command.
SHELL_ALLOW = frozenset(
    {'rg', 'grep', 'ls', 'cat', 'head', 'tail', 'wc', 'jq', 'tree', 'fd', 'find', 'sed', 'git', 'echo', 'pwd', 'file', 'stat', 'basename', 'dirname', 'sort', 'uniq', 'cut', 'awk', 'column', 'nl', 'diff'}
)

# Never allowed as a first token, whatever else is true.
SHELL_DENY = frozenset(
    {'rm', 'rmdir', 'mv', 'cp', 'sh', 'bash', 'zsh', 'fish', 'python', 'python3', 'node', 'perl', 'ruby', 'eval', 'exec', 'env', 'xargs', 'tee', 'sudo', 'su', 'chmod', 'chown', 'ln', 'touch', 'mkdir', 'truncate', 'dd', 'curl', 'wget', 'npm', 'npx', 'yarn', 'pnpm', 'make', 'docker', 'kubectl', 'gh', 'brew', 'pip', 'pip3', 'uv', 'alembic', 'psql'}
)

GIT_ALLOW = frozenset(
    {'status', 'log', 'diff', 'show', 'ls-files', 'rev-parse', 'blame', 'branch', 'remote', 'describe', 'shortlog', 'cat-file', 'ls-tree', 'config', 'worktree', 'grep', 'merge-base', 'name-rev', 'tag', 'count-objects', 'for-each-ref'}
)

# Survive-quoting checks, done on the raw string: command substitution and a literal
# newline change meaning wherever they appear.
RAW_DENY = re.compile(r'[`\n\r]|\$\(')

# Real shell operators, recognised only when UNQUOTED — `grep 'Foo<T>'` is a search term,
# `ls > f` is a redirect, and only a tokenizer can tell them apart. `|` is absent: a
# pipeline is allowed as long as every segment's command is.
DENY_OPERATORS = frozenset({';', '&', '&&', '||', '>', '>>', '<', '<<', '<<<', '>|', '&>', '|&', '(', ')', '$'})

# `git -C <dir>`, `git -c k=v` and friends take a value. Skipping the flag but not its
# value made the directory look like the subcommand, which denied the `git -C "$TREE" diff`
# the PR skills tell agy to run.
GIT_VALUE_FLAGS = frozenset({'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path'})


def shell_tokens(command: str) -> list[str]:
    lex = shlex.shlex(command, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    return list(lex)


def git_subcommand(rest: list[str]) -> str:
    i = 0
    while i < len(rest):
        token = rest[i]
        if token in GIT_VALUE_FLAGS:
            i += 2
            continue
        if token.startswith('-'):
            i += 1
            continue
        return token
    return ''


def log(tool: str, decision: str, reason: str, extra: str = '') -> None:
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as fh:
            fh.write(
                '{ts}\t{tool}\t{decision}\t{reason}\t{extra}\n'.format(
                    ts=time.strftime('%Y-%m-%dT%H:%M:%S'),
                    tool=tool,
                    decision=decision,
                    reason=reason.replace('\t', ' ').replace('\n', ' '),
                    extra=extra[:400].replace('\t', ' ').replace('\n', ' '),
                )
            )
    except OSError:
        pass


def emit(tool: str, decision: str, reason: str, extra: str = '') -> None:
    log(tool, decision, reason, extra)
    out: dict[str, str] = {'decision': decision}
    if reason:
        out['reason'] = reason
    sys.stdout.write(json.dumps(out))
    sys.exit(0)


def check_shell(tool: str, args: dict) -> None:
    command = None
    for key in COMMAND_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            command = value.strip()
            break
    if command is None:
        emit(tool, 'deny', 'Read-only advisor: could not find the command string to vet, so it is denied.', json.dumps(args)[:300])

    if RAW_DENY.search(command):
        emit(tool, 'deny', 'Read-only advisor: command substitution and multi-line commands are not allowed.', command)

    try:
        tokens = shell_tokens(command)
    except ValueError:
        emit(tool, 'deny', 'Read-only advisor: command could not be parsed, so it is denied.', command)
    if not tokens:
        emit(tool, 'deny', 'Read-only advisor: empty command.', command)

    bad = sorted({t for t in tokens if t in DENY_OPERATORS})
    if bad:
        emit(tool, 'deny', f'Read-only advisor: shell operators {" ".join(bad)} are not allowed.', command)

    segments: list[list[str]] = [[]]
    for token in tokens:
        if token == '|':
            segments.append([])
        else:
            segments[-1].append(token)

    for segment in segments:
        if not segment:
            emit(tool, 'deny', 'Read-only advisor: empty pipe segment.', command)
        head = os.path.basename(segment[0])
        rest = segment[1:]

        if head in SHELL_DENY:
            emit(tool, 'deny', f'Read-only advisor: `{head}` can modify things and is not allowed.', command)
        if head not in SHELL_ALLOW:
            emit(tool, 'deny', f'Read-only advisor: `{head}` is not on the read-only command allowlist.', command)
        if head == 'git':
            sub = git_subcommand(rest)
            if sub not in GIT_ALLOW:
                emit(tool, 'deny', f'Read-only advisor: `git {sub}` is not a read-only git subcommand.', command)
            if sub == 'config' and not any(t in ('--get', '--list', '-l', '--get-all') for t in rest):
                emit(tool, 'deny', 'Read-only advisor: `git config` is only allowed for reading.', command)
            if sub == 'worktree' and 'list' not in rest:
                emit(tool, 'deny', 'Read-only advisor: `git worktree` is only allowed for listing.', command)
        if head == 'sed' and any(t.startswith('-i') for t in rest):
            emit(tool, 'deny', 'Read-only advisor: `sed -i` edits in place.', command)
        if head == 'sed' and not any(t.startswith('-n') for t in rest):
            emit(tool, 'deny', 'Read-only advisor: `sed` is only allowed in `-n` print mode.', command)
        if head == 'find' and any(t in ('-exec', '-execdir', '-delete', '-ok') for t in rest):
            emit(tool, 'deny', 'Read-only advisor: `find` may not execute or delete.', command)

    emit(tool, 'allow', '')


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        emit('<unparseable>', 'deny', 'Read-only advisor: hook input could not be parsed.', raw[:300])

    call = payload.get('toolCall') or {}
    tool = str(call.get('name') or '<unknown>').lower()
    args = call.get('args') if isinstance(call.get('args'), dict) else {}

    # Before anything else, and also when writing is allowed: what is read goes to the model.
    if os.environ.get('AGY_ALLOW_SECRET_READ') != '1':
        if tool in SHELL_TOOLS:
            command = next((args[key].strip() for key in COMMAND_KEYS if isinstance(args.get(key), str) and args[key].strip()), '')
            why = secret_in_command(command, args) if command else ''
        else:
            why = secret_in_arguments(args)
        if why:
            emit(tool, 'deny', f'Read-only advisor: {why}. Secrets are not read, by any tool. '
                               'If the question needs what is in there, say so in your answer instead.', json.dumps(args)[:300])

    if os.environ.get('AGY_ALLOW_WRITE') == '1':
        if tool in ('delete_directory', 'move') and os.environ.get('AGY_ALLOW_DELETE') != '1':
            emit(tool, 'deny', 'Write is permitted for this call, but delete/move is not. Ask for --allow-delete.', '')
        emit(tool, 'allow', 'AGY_ALLOW_WRITE=1')

    if tool in READ_TOOLS or tool in BOOKKEEPING:
        emit(tool, 'allow', '')

    if mcp_read_only(tool, args):
        emit(tool, 'allow', 'Blender/Godot MCP read')

    if looks_read_only(tool):
        emit(tool, 'allow', 'read-shaped name')

    if tool in SHELL_TOOLS:
        check_shell(tool, args)

    emit(
        tool,
        'deny',
        f'Read-only advisor: the `{tool}` tool can change files or state and is blocked. '
        'You are an advisor here — describe the change you would make instead of making it.',
        json.dumps(args)[:300],
    )


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:  # fail closed
        log('<crash>', 'deny', type(exc).__name__, str(exc))
        sys.stdout.write(json.dumps({'decision': 'deny', 'reason': 'Read-only advisor gate crashed; denying.'}))
        sys.exit(0)
