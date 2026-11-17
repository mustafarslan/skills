"""Per-repo PR rules (config.json "repo_rules"), set with /pr-pulse:rules.

    "repo_rules": {
      "owner/name": {
        "settings": {"auto_review": "off", "merge": "ask", "feedback_rounds": 1,
                     "bot_rounds": 1, "review_bots": ["coderabbitai"], "ignore_authors": ["linear"]},
        "rules": ["Run the bank-rule tests before approving.", "Never merge on Fridays."]
      }
    }

Settings are enforced by pr-pulse itself and override the global value for that repo only.
Rules are plain language: every job for that repo gets them in its instructions.
Repo names match case-insensitively. A bad entry is reported and that repo falls back to the
global settings: it never half-applies.
"""
import copy

SETTINGS = {
    "auto_review": ("on", "off"),          # off: never review others' PRs in this repo
    "merge": ("auto", "ask", "never"),     # auto: today's merge rules; ask: ask before merging
    "feedback_rounds": int,
    "bot_rounds": int,
    "review_bots": list,
    "ignore_authors": list,
}
DEFAULTS = {"auto_review": "on", "merge": "auto"}
MAX_RULES, MAX_RULE_LEN = 20, 300


def check_setting(key, value):
    """The cleaned value, or raises ValueError with a message for the user."""
    kind = SETTINGS.get(key)
    if kind is None:
        raise ValueError(f"unknown setting {key!r}; known: {', '.join(SETTINGS)}")
    if isinstance(kind, tuple):
        v = str(value).strip().lower()
        if v not in kind:
            raise ValueError(f"{key} must be one of {', '.join(kind)}")
        return v
    if kind is int:
        if isinstance(value, bool):
            raise ValueError(f"{key} must be a whole number from 0 to 10")
        try:
            v = int(str(value).strip())
        except ValueError:
            raise ValueError(f"{key} must be a whole number from 0 to 10")
        if not 0 <= v <= 10 or str(value).strip() not in (str(v), f"+{v}"):
            raise ValueError(f"{key} must be a whole number from 0 to 10")
        return v
    if isinstance(value, str):
        value = [x.strip() for x in value.split(",")]
    if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
        raise ValueError(f"{key} must be a list of logins (comma-separated)")
    return [x.strip().lower() for x in value]


def validate(raw):
    """(clean, errors): clean = {slug_lower: {"slug", "settings", "rules"}} for valid repos only."""
    clean, errors = {}, []
    if raw in (None, {}):
        return clean, errors
    if not isinstance(raw, dict):
        return clean, ["repo_rules must be an object of {\"owner/name\": {...}}"]
    for slug, entry in raw.items():
        key = str(slug).strip().lower()
        try:
            if "/" not in key or key.count("/") != 1:
                raise ValueError("use owner/name")
            if key in clean:
                raise ValueError("listed twice (names match case-insensitively)")
            if not isinstance(entry, dict) or set(entry) - {"settings", "rules"}:
                raise ValueError('needs only "settings" and/or "rules"')
            settings = {k: check_setting(k, v) for k, v in (entry.get("settings") or {}).items()}
            rules = entry.get("rules") or []
            if not isinstance(rules, list) or not all(isinstance(r, str) and r.strip() for r in rules):
                raise ValueError("rules must be a list of sentences")
            if len(rules) > MAX_RULES or any(len(r) > MAX_RULE_LEN for r in rules):
                raise ValueError(f"at most {MAX_RULES} rules of {MAX_RULE_LEN} characters")
            clean[key] = {"slug": str(slug).strip(), "settings": settings, "rules": [r.strip() for r in rules]}
        except ValueError as e:
            errors.append(f"repo_rules {slug}: {e}; that repo uses the global settings")
    return clean, errors


def for_repo(cfg, slug):
    """The config one repo sees: global settings with its overrides, plus its rules."""
    clean, _ = validate(cfg.get("repo_rules"))
    entry = clean.get((slug or "").lower(), {})
    out = copy.copy(cfg)
    out.update(DEFAULTS)
    out.update(entry.get("settings", {}))
    out["repo_rules_text"] = entry.get("rules", [])
    return out


def describe(cfg, slug):
    """Human-readable rules for one repo (for /pr-pulse:rules)."""
    clean, errors = validate(cfg.get("repo_rules"))
    entry = clean.get((slug or "").lower())
    lines = [f"PR rules for {slug}:"]
    s = (entry or {}).get("settings", {})
    lines.append("  settings (pr-pulse enforces):")
    for k in SETTINGS:
        if k in s:
            v = ", ".join(s[k]) if isinstance(s[k], list) else s[k]
            lines.append(f"    {k:<16} {v}")
        else:
            g = DEFAULTS.get(k, cfg.get(k))
            g = ", ".join(g) if isinstance(g, list) else g
            lines.append(f"    {k:<16} {g}   (global)")
    rules = (entry or {}).get("rules", [])
    lines.append("  rules (every job for this repo follows):")
    lines += [f"    {i}. {r}" for i, r in enumerate(rules, 1)] or ["    none"]
    for e in errors:
        if e.startswith(f"repo_rules {slug}".lower()) or slug.lower() in e.lower():
            lines.append(f"  PROBLEM: {e}")
    return "\n".join(lines)
