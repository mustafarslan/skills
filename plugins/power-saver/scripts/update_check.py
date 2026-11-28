"""SessionStart hook: tell the user when a newer version of this plugin is out. Installs nothing.

Reads the installed version from ${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json, fetches the same file from the
marketplace repo's default branch at most once a day (cached in ${CLAUDE_PLUGIN_DATA}), and prints one hook JSON
`systemMessage` (shown to the user, not added to the model's context) when the published version is newer.

Any error (offline, timeout, bad JSON, missing file) prints nothing and exits 0. Standard library only.
Opt out with MUSTAFARSLAN_SKILLS_UPDATE_CHECK=0. Every plugin of this marketplace carries an identical copy.
"""
import json
import os
import re
import sys
import time
import urllib.request

REPO = "mustafarslan/skills"          # MUSTAFARSLAN_SKILLS_UPDATE_REPO overrides it
BRANCH = "master"
MARKETPLACE = "mustafarslan-skills"   # `name` in .claude-plugin/marketplace.json
INTERVAL = 24 * 3600
TIMEOUT = 3.0
CACHE_NAME = "update-check.json"
OFF_VALUES = {"0", "false", "off", "no"}


def parse_version(text):
    """'0.10.1' -> ((0, 10, 1), 1); '1.0.0-rc1' -> ((1, 0, 0), 0). None when it is not a version."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)([-+].*)?", str(text).strip())
    if not m:
        return None
    nums = tuple(int(p) for p in m.group(1).split("."))
    while len(nums) > 1 and nums[-1] == 0:
        nums = nums[:-1]
    pre = 0 if (m.group(2) or "").startswith("-") else 1
    return nums, pre


def is_newer(latest, installed):
    a, b = parse_version(latest), parse_version(installed)
    return a is not None and b is not None and a > b


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_version(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "mustafarslan-skills-update-check"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read(1 << 20).decode("utf-8"))
    version = data.get("version")
    return version if isinstance(version, str) and parse_version(version) else None


def latest_version(name, data_dir, now):
    """The published version: from the cache when it is under a day old, else fetched (and cached)."""
    cache_path = os.path.join(data_dir, CACHE_NAME) if data_dir else None
    cache = {}
    if cache_path:
        try:
            cache = read_json(cache_path)
            if not isinstance(cache, dict):
                cache = {}
        except Exception:
            cache = {}
        checked = cache.get("checked_at")
        if isinstance(checked, (int, float)) and 0 <= now - checked < INTERVAL:
            return cache.get("latest")
    else:
        return None  # nowhere to remember the time: skip the check rather than fetch every session
    repo = os.environ.get("MUSTAFARSLAN_SKILLS_UPDATE_REPO") or REPO
    url = os.environ.get("MUSTAFARSLAN_SKILLS_UPDATE_URL") or (
        "https://raw.githubusercontent.com/%s/%s/plugins/%s/.claude-plugin/plugin.json" % (repo, BRANCH, name))
    try:
        timeout = float(os.environ.get("MUSTAFARSLAN_SKILLS_UPDATE_TIMEOUT") or TIMEOUT)
    except ValueError:
        timeout = TIMEOUT
    latest = cache.get("latest")
    try:
        latest = fetch_version(url, timeout) or latest
    except Exception:
        pass  # keep the last known version; the failed try still counts, so an offline PC is not retried each session
    try:
        os.makedirs(data_dir, exist_ok=True)
        tmp = cache_path + ".tmp%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"checked_at": now, "latest": latest}, f)
        os.replace(tmp, cache_path)
    except Exception:
        pass
    return latest


def notice(name, latest, installed):
    return ("%s %s is out (you have %s). Update: claude plugin marketplace update %s && "
            "claude plugin update %s@%s (then restart), or turn on auto-update in /plugin \u2192 Marketplaces."
            % (name, latest, installed, MARKETPLACE, name, MARKETPLACE))


def main():
    if (os.environ.get("MUSTAFARSLAN_SKILLS_UPDATE_CHECK") or "").strip().lower() in OFF_VALUES:
        return
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not root:
        return
    meta = read_json(os.path.join(root, ".claude-plugin", "plugin.json"))
    name, installed = meta["name"], meta["version"]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or not parse_version(installed):
        return
    latest = latest_version(name, os.environ.get("CLAUDE_PLUGIN_DATA"), time.time())
    if latest and is_newer(latest, installed):
        print(json.dumps({"systemMessage": notice(name, latest, installed)}))


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        pass
    sys.exit(0)
