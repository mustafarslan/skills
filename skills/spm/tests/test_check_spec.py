"""Tests for spm's checker and trigger hook. Run: python3 -m unittest discover -s tests"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, 'scripts', 'check_spec.py')
TRIGGER = os.path.join(ROOT, 'hooks', 'spm-trigger.py')
MARK = '<!-- spm:draft — engineering to promote -->\n'

WORLD = MARK + """# Approvals — world

## Personas
| ID | Name | Tenant | Business role | Email |
|---|---|---|---|---|
| U-ANA-02 | Ayşe Yılmaz | T-ANA | Approver | ayse@anadolu.example |

## Values
| Name | Value | Meaning | Source |
|---|---|---|---|
| Level-1 limit | 50.000,00 TRY | Highest level-1 amount, inclusive | PM 2026-10-08 |
| Decision time limit | 72 hours | How long an approval request can still be answered | PM 2026-10-08 |
| Reminder time | 09:00 | Working-day reminder | PM 2026-10-08 |

## Outside systems
| Name | What it is |
|---|---|
| Customer ERP | The customer's accounting system |

## Glossary
| Term | Meaning |
|---|---|
| Approver | Person who decides on an invoice |

## Accepted terms
- e-Fatura — Turkish e-invoice; customers call it this (PM, 2026-10-08)
"""

CLEAN_INTENT = MARK + """# Approvals — epic

## Problem
Approvers rarely sign in, so invoices wait days for a decision.

## Why now, and for whom
Finance teams lose early-payment discounts while invoices wait.

## Hypothesis
If approvers can decide where they already are, invoices stop waiting for them.

## Success measures
| ID | Measure | Target | How we will know |
|---|---|---|---|
| M-1 | Median wait for a decision | under one day | Finance sees it in the monthly report |

## Constraints
| Constraint | Why | Source |
|---|---|---|
| email | Approvers do not sign in; they read email every day | PM, 2026-10-08 |

## Out of scope
- Deciding by phone.

## Open questions
| # | Question | Owner | Blocks |
|---|---|---|---|
| 1 | Should a reply in English count? | Product | no |
"""

CLEAN_STORIES = MARK + """# Approvals — stories

### US-01 — Decide from email
**US-01 (P0)** As an Approver, I want to decide on an invoice from my email without signing in, so that invoices do not wait for me.
**AC-01.1** When an invoice above the Level-1 limit is waiting, the level-2 approver receives an email asking for a decision.
**AC-01.2** When the Decision time limit (72 hours) has passed, the approver cannot decide from that email and is told how to ask again.
**AC-01.3** Approvers receive reminders at 09:00 on working days.
**AC-01.4** Nobody can decide on an invoice from an email that was not sent to them.
**AC-01.5** Approvers see the e-invoice number of e-Fatura invoices in the email.
**Done when:** AC-01.1 to AC-01.5 hold, example EA-01 passes, and M-1 moves.
"""

CLEAN_SCENARIOS = MARK + """# Approvals — scenarios

## Group: decide from email

### EA-01 — Approve by reply
Priority: P0 · MVP · Covers: US-01

**Given** invoice INV-0042 of 48.750,00 TRY waits for Ayşe (U-ANA-02)
**When** Ayşe answers the email with "YES"
**Then** Ayşe sees INV-0042 as approved

| Who | Observes | Expected |
|---|---|---|
| Ayşe | Invoice INV-0042 | Approved by her, from email |

**Must not:**
- Mehmet receives a second request for INV-0042
"""

CLEAN_DESIGN = MARK + """# Approvals — design input

### D-01 — Decision email
Source: UI/UX designer, 2026-10-07, mock "approval email v2"
The email shows two buttons, Approve and Reject, under the invoice summary. Clicking one opens a confirmation page.
"""

LEAKY_STORIES = MARK + """# Approvals — stories

### US-01 — Leaks
**US-01 (P0)** As an Approver, I want an approve button, so that I can approve.
**AC-01.1** When `approval_status` changes, emit ROUTE_COMPUTED and write a row to the record_events table.
**AC-01.2** GET /a/<token>/confirm returns HTTP 410 when expired; the token is base64.
**AC-01.3** Use TransitionRule so effective_from <= service_date.
**AC-01.4** Escalate after 7 days or 250.000 TRY.
**AC-01.5** The Customer ERP receives the export at 06:00.
**Done when:** all hold.

```python
def route(inv): return 2
```
"""

PACK = {'intent.md': CLEAN_INTENT, 'world.md': WORLD, 'stories.md': CLEAN_STORIES,
        'scenarios.md': CLEAN_SCENARIOS}


def run(args, stdin=None, cwd=None):
    return subprocess.run([sys.executable, CHECK] + args, input=stdin, capture_output=True,
                          text=True, cwd=cwd)


class Base(unittest.TestCase):
    def pack(self, **files):
        d = tempfile.mkdtemp()
        for name, text in files.items():
            with open(os.path.join(d, name), 'w', encoding='utf-8') as fh:
                fh.write(text)
        return d

    def findings(self, d, cwd=None):
        p = run([d, '--json'], cwd=cwd or tempfile.gettempdir())
        self.assertIn(p.returncode, (0, 1), p.stderr)
        return json.loads(p.stdout)


class PackTests(Base):
    def test_clean_pack_has_no_findings(self):
        d = self.pack(**PACK, **{'design-input.md': CLEAN_DESIGN})
        self.assertEqual(self.findings(d), [])

    def test_leaky_stories_flag_every_leak(self):
        d = self.pack(**{'stories.md': LEAKY_STORIES, 'world.md': WORLD, 'intent.md': CLEAN_INTENT})
        f = self.findings(d)
        texts = {x['text'] for x in f}
        kinds = {x['kind'] for x in f}
        for t in ('approval_status', 'ROUTE_COMPUTED', 'record_events', 'table', 'TransitionRule',
                  'GET', '<=', 'base64', 'token', '250.000', '06:00', 'button'):
            self.assertTrue(any(t in x for x in texts), f'{t} not flagged: {sorted(texts)}')
        self.assertIn('code-block', kinds)
        self.assertIn('url-path', kinds)
        self.assertFalse(any(x['text'] == '7' for x in f), 'single-digit counts are not constants')

    def test_duplicate_constant_with_different_value(self):
        world = WORLD.replace('## Outside systems', '| Level-1 limit | 50.000,01 TRY | x | y |\n\n## Outside systems', 1)
        d = self.pack(**{'world.md': world})
        self.assertTrue(any(x['kind'] == 'contradiction' for x in self.findings(d)))

    def test_incomplete_and_duplicate_scenarios(self):
        bad = CLEAN_SCENARIOS + '\n### EA-01 — Again\n**Given** x **When** y\n'
        d = self.pack(**{'scenarios.md': bad, 'world.md': WORLD})
        f = self.findings(d)
        self.assertTrue(any(x['kind'] == 'duplicate-id' for x in f))
        self.assertTrue(any(x['kind'] == 'incomplete' and 'Then' in x['message'] for x in f))

    def test_repo_identifier_cross_check(self):
        repo = tempfile.mkdtemp()
        subprocess.run(['git', 'init', '-q', repo], check=True)
        with open(os.path.join(repo, 'router.py'), 'w') as fh:
            fh.write('class LookupMatchField:\n    pass\n')
        subprocess.run(['git', '-C', repo, 'add', '.'], check=True)
        d = self.pack(**{'intent.md': CLEAN_INTENT + 'Today LookupMatchField picks the wrong row.\n',
                         'world.md': WORLD})
        f = self.findings(d, cwd=repo)
        self.assertTrue(any('NAMES CODE' in x['message'] and x['text'] == 'LookupMatchField' for x in f))


    def test_repo_cross_check_falls_back_to_the_packs_repo(self):
        """Installed globally, Claude may run from a folder that is not a repo while the pack
        sits inside the product repo: the cross-check must still run, against that repo."""
        repo = tempfile.mkdtemp()
        subprocess.run(['git', 'init', '-q', repo], check=True)
        with open(os.path.join(repo, 'router.py'), 'w') as fh:
            fh.write('class LookupMatchField:\n    pass\n')
        subprocess.run(['git', '-C', repo, 'add', '.'], check=True)
        d = os.path.join(repo, 'specs', 'approvals')
        os.makedirs(d)
        for name, text in {'intent.md': CLEAN_INTENT + 'Today LookupMatchField picks the wrong row.\n',
                           'world.md': WORLD}.items():
            with open(os.path.join(d, name), 'w', encoding='utf-8') as fh:
                fh.write(text)
        f = self.findings(d, cwd=tempfile.gettempdir())
        self.assertTrue(any('NAMES CODE' in x['message'] and x['text'] == 'LookupMatchField' for x in f))

class ActorVerbAndMechanismTests(Base):
    def kinds_for(self, stories, intent=CLEAN_INTENT):
        d = self.pack(**{'stories.md': MARK + stories, 'world.md': WORLD, 'intent.md': intent})
        return [(x['kind'], x['text']) for x in self.findings(d)]

    def test_system_as_actor_is_flagged(self):
        k = self.kinds_for('**AC-01.1** The system stores each version separately.\n')
        self.assertIn('actor', [x[0] for x in k])
        self.assertIn('mechanism', [x[0] for x in k])

    def test_then_without_actor_is_flagged(self):
        d = self.pack(**{'scenarios.md': CLEAN_SCENARIOS.replace(
            '**Then** Ayşe sees INV-0042 as approved', '**Then** INV-0042 is approved'), 'world.md': WORLD})
        self.assertIn('actor', [x['kind'] for x in self.findings(d)])

    def test_declared_actors_pass(self):
        for line in ('**AC-01.1** When the Decision time limit has passed, Ayşe is told she can no longer decide.',
                     '**AC-01.2** The Customer ERP receives one line per approved invoice.',
                     '**AC-01.3** U-ANA-02 cannot approve her own invoices.'):
            self.assertEqual(self.kinds_for(line + '\n'), [], line)

    def test_plain_word_mechanisms_are_flagged(self):
        for line in ('Each price list gets its own list and screen.',
                     'A nightly run recalculates the balances.',
                     'Versions are stored separately per supplier.',
                     'A dedicated page lists the contracts.',
                     'Prices sync with the ERP.'):
            self.assertIn('mechanism', [x[0] for x in self.kinds_for(line + '\n')], line)

    def test_number_reading_does_not_widen_constants(self):
        k = self.kinds_for('**AC-01.1** Approvers see invoices above 50 TRY.\n')
        self.assertIn(('constant', '50'), k)

    def test_ui_design_is_flagged_outside_design_input(self):
        for line in ('**AC-01.1** Ayşe clicks the Approve button.',
                     '**AC-01.2** When the time limit passes, Ayşe sees a page explaining why.',
                     '**AC-01.3** Ayşe can open the link in the email.',
                     '**AC-01.4** Ayşe can select the reason from a dropdown.'):
            self.assertIn('ui', [x[0] for x in self.kinds_for(line + '\n')], line)

    def test_exact_ui_copy_in_criteria_is_flagged(self):
        k = self.kinds_for('**AC-01.1** Ayşe sees "Approved by Ayşe via email reply" on the invoice.\n')
        self.assertIn('ui-copy', [x[0] for x in k])

    def test_short_literal_is_data_not_copy(self):
        k = self.kinds_for('**AC-01.1** When Ayşe answers the email with "YES", Ayşe sees the invoice as approved.\n')
        self.assertEqual(k, [])

    def test_channel_word_needs_a_constraint(self):
        no_constraint = CLEAN_INTENT.replace('| email | Approvers do not sign in; they read email every day | PM, 2026-10-08 |\n', '')
        k = self.kinds_for('**AC-01.1** Ayşe receives an email asking for a decision.\n', intent=no_constraint)
        self.assertIn(('channel', 'email'), k)
        self.assertEqual(self.kinds_for('**AC-01.1** Ayşe receives an email asking for a decision.\n'), [])

    def test_constraint_without_a_reason_does_not_count(self):
        for why in ('', 'open: Q-01', 'TBD'):
            intent = CLEAN_INTENT.replace('Approvers do not sign in; they read email every day', why)
            k = self.kinds_for('**AC-01.1** Ayşe receives an email asking for a decision.\n', intent=intent)
            self.assertIn(('channel', 'email'), k, why)
            self.assertIn('constraint', [x[0] for x in k], why)

    def test_input_file_names_are_not_channels(self):
        no_constraint = CLEAN_INTENT.replace('| email | Approvers do not sign in; they read email every day | PM, 2026-10-08 |\n', '')
        d = self.pack(**{'scenarios.md': CLEAN_SCENARIOS.replace('Covers: US-01', 'Covers: US-01 · Inputs: inputs/EA-01_waiting.csv, inputs/EA-01_reply.eml').replace('answers the email with', 'answers with').replace('from email', 'from the message'),
                         'world.md': WORLD, 'intent.md': no_constraint})
        self.assertEqual([x for x in self.findings(d) if x['kind'] == 'channel'], [])

    def test_persona_named_like_a_verb(self):
        world = WORLD.replace('| U-ANA-02 | Ayşe Yılmaz | T-ANA | Approver | ayse@anadolu.example |',
                              '| U-ANA-02 | Ayşe Yılmaz | T-ANA | Approver | ayse@anadolu.example |\n| U-ANA-03 | Can Demir | T-ANA | Clerk | can@anadolu.example |')
        d = self.pack(**{'stories.md': MARK + '**AC-01.1** Can sees the invoice as approved.\n',
                         'world.md': world, 'intent.md': CLEAN_INTENT})
        self.assertEqual(self.findings(d), [])
        d = self.pack(**{'stories.md': MARK + '**AC-01.1** Can can approve INV-0042.\n',
                         'world.md': world, 'intent.md': CLEAN_INTENT})
        self.assertEqual(self.findings(d), [])

    def test_story_line_shape_and_persona(self):
        k = self.kinds_for('### US-02 — Reminders\n**US-02 (P1)** Approvers want reminders.\n'
                           '**AC-02.1** Approvers receive reminders at 09:00.\n**Done when:** AC-02.1 holds.\n')
        self.assertIn('story', [x[0] for x in k])
        k = self.kinds_for('### US-02 — Reminders\n**US-02 (P1)** As a Wizard, I want reminders, so that I act.\n'
                           '**AC-02.1** Approvers receive reminders at 09:00.\n**Done when:** AC-02.1 holds.\n')
        self.assertIn('story', [x[0] for x in k])

    def test_story_needs_criteria_and_done(self):
        d = self.pack(**{'stories.md': MARK + '### US-03 — Bare\n**US-03 (P2)** As an Approver, I want x, so that y.\n',
                         'world.md': WORLD, 'intent.md': CLEAN_INTENT})
        msgs = ' '.join(x['message'] for x in self.findings(d) if x['kind'] == 'incomplete')
        self.assertIn('acceptance criteria', msgs)
        self.assertIn('Done when', msgs)

    def test_design_input_needs_designer_source(self):
        bad = CLEAN_DESIGN.replace('Source: UI/UX designer, 2026-10-07, mock "approval email v2"\n', '')
        d = self.pack(**PACK, **{'design-input.md': bad})
        self.assertIn('design-source', [x['kind'] for x in self.findings(d)])

    def test_notes_for_engineering_is_no_longer_exempt(self):
        k = self.kinds_for('## Notes for engineering (non-binding)\nMaybe reuse the `response_token` thing.\n')
        self.assertTrue(k)

    def test_unmarked_pack_file_is_still_checked_by_hook(self):
        d = tempfile.mkdtemp()
        p = run(['--hook'], stdin=json.dumps({'tool_name': 'Write', 'tool_input': {
            'file_path': os.path.join(d, 'intent.md'), 'content': 'Write to the audit_log table.'}}),
            cwd=tempfile.gettempdir())
        self.assertIn('deny', p.stdout)


class ApproveTests(Base):
    def full_pack(self):
        return self.pack(**PACK)

    def pack_hash(self, d):
        p = run(['--pack-hash', d])
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def write(self, d, name, text):
        with open(os.path.join(d, name), 'w', encoding='utf-8') as fh:
            fh.write(text)

    def approved(self, d):
        h = self.pack_hash(d)
        self.write(d, 'redteam-1.md', f'<!-- spm:redteam pack={h} -->\nRT1-01 intent.md:5 "x" (2)\n')
        self.write(d, 'redteam-2.md', f'<!-- spm:redteam pack={h} -->\nno findings\n')
        self.write(d, 'decisions.md', '# Decisions\n\n| Pack | Finding | Where | Words | Decision | Reason | Date |\n'
                   f'|---|---|---|---|---|---|---|\n| {h} | RT1-01 | intent.md:5 | x | keep | customers say it | 2026-10-08 |\n'
                   '\n## Approval\nApproved by Product, 2026-10-08\n')

    def test_approve_passes_on_complete_pack(self):
        d = self.full_pack(); self.approved(d)
        p = run(['--approve', d], cwd=tempfile.gettempdir())
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_approve_fails_without_red_team(self):
        d = self.full_pack()
        self.assertEqual(run(['--approve', d], cwd=tempfile.gettempdir()).returncode, 1)

    def test_approve_fails_when_pack_changed_after_red_team(self):
        d = self.full_pack(); self.approved(d)
        self.write(d, 'intent.md', CLEAN_INTENT + '\n<!-- edited -->\n')
        p = run(['--approve', d], cwd=tempfile.gettempdir())
        self.assertEqual(p.returncode, 1); self.assertIn('red team', p.stdout)

    def test_approve_fails_on_undecided_red_team_finding(self):
        d = self.full_pack(); self.approved(d)
        h = self.pack_hash(d)
        self.write(d, 'redteam-2.md', f'<!-- spm:redteam pack={h} -->\nRT2-01 intent.md:7 "y" (1)\n')
        p = run(['--approve', d], cwd=tempfile.gettempdir())
        self.assertEqual(p.returncode, 1); self.assertIn('RT2-01', p.stdout)

    def test_old_round_decision_does_not_cover_new_round(self):
        d = self.full_pack(); self.approved(d)
        old = self.pack_hash(d)
        self.write(d, 'decisions.md', '| Pack | Finding | Where | Words | Decision | Reason | Date |\n|---|---|---|---|---|---|---|\n'
                   f'| {old} | RT1-01 | a | b | keep | c | d |\n| {old} | RT2-01 | a | b | keep | c | d |\n'
                   '\n## Approval\nApproved by Product, 2026-10-08\n')
        self.write(d, 'stories.md', CLEAN_STORIES + '**AC-01.6** Approvers see the supplier name.\n')
        h = self.pack_hash(d)
        for n in (1, 2):
            self.write(d, f'redteam-{n}.md', f'<!-- spm:redteam pack={h} -->\nRT{n}-01 intent.md:30 "new words" (1)\n')
        p = run(['--approve', d], cwd=tempfile.gettempdir())
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('RT1-01', p.stdout)

    def test_rewrite_in_final_round_is_not_a_resolution(self):
        d = self.full_pack(); self.approved(d)
        dp = os.path.join(d, 'decisions.md')
        with open(dp) as fh:
            text = fh.read()
        self.write(d, 'decisions.md', text.replace('| keep |', '| rewrite |'))
        p = run(['--approve', d], cwd=tempfile.gettempdir())
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn('RT1-01', p.stdout)

    def test_approve_says_when_repo_check_was_skipped(self):
        d = self.full_pack(); self.approved(d)
        p = run(['--approve', d], cwd=tempfile.gettempdir())
        self.assertIn('not inside a git repo', p.stdout)

    def test_approve_requires_stories(self):
        d = self.full_pack(); os.remove(os.path.join(d, 'stories.md')); self.approved(d)
        self.assertIn('stories.md is missing', run(['--approve', d], cwd=tempfile.gettempdir()).stdout)

    def test_approve_fails_without_marker_or_approval(self):
        d = self.full_pack(); self.approved(d)
        self.write(d, 'world.md', WORLD.replace(MARK, ''))
        self.approved(d)
        self.assertIn('marker', run(['--approve', d], cwd=tempfile.gettempdir()).stdout)
        d2 = self.full_pack(); self.approved(d2)
        self.write(d2, 'decisions.md', '# Decisions\n| Pack | Finding | Where | Words | Decision | Reason | Date |\n|---|---|---|---|---|---|---|\n| x | RT1-01 | a | b | keep | c | d |\n')
        self.assertIn('approval', run(['--approve', d2], cwd=tempfile.gettempdir()).stdout.lower())


class HookTests(unittest.TestCase):
    def hook(self, payload):
        return run(['--hook'], stdin=json.dumps(payload), cwd=tempfile.gettempdir())

    def test_unmarked_file_is_allowed(self):
        p = self.hook({'tool_name': 'Write', 'tool_input': {
            'file_path': '/tmp/notes.md', 'content': 'GET /api/x returns 403'}})
        self.assertEqual((p.returncode, p.stdout), (0, ''))

    def test_marked_leaky_write_is_denied(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, 'world.md'), 'w') as fh:
            fh.write(WORLD)
        p = self.hook({'tool_name': 'Write', 'tool_input': {
            'file_path': os.path.join(d, 'stories.md'), 'content': LEAKY_STORIES}})
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)['hookSpecificOutput']
        self.assertEqual(out['permissionDecision'], 'deny')
        self.assertIn('ROUTE_COMPUTED', out['permissionDecisionReason'])

    def test_marked_clean_write_is_allowed(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, 'world.md'), 'w') as fh:
            fh.write(WORLD)
        p = self.hook({'tool_name': 'Write', 'tool_input': {
            'file_path': os.path.join(d, 'intent.md'), 'content': CLEAN_INTENT}})
        self.assertEqual((p.returncode, p.stdout), (0, ''), p.stderr)

    def test_edit_applies_change_before_checking(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, 'stories.md')
        with open(path, 'w') as fh:
            fh.write(CLEAN_STORIES)
        with open(os.path.join(d, 'intent.md'), 'w') as fh:
            fh.write(CLEAN_INTENT)
        with open(os.path.join(d, 'world.md'), 'w') as fh:
            fh.write(WORLD)
        p = self.hook({'tool_name': 'Edit', 'tool_input': {
            'file_path': path, 'old_string': 'asking for a decision.',
            'new_string': 'asking for a decision; write to the audit_log table.'}})
        self.assertIn('deny', p.stdout)

    def test_accepted_terms_edit_is_not_blocked(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, 'world.md')
        with open(path, 'w') as fh:
            fh.write(WORLD)
        p = self.hook({'tool_name': 'Edit', 'tool_input': {
            'file_path': path, 'old_string': '- e-Fatura',
            'new_string': '- token — what customers call the reference code in the email (PM)\n- e-Fatura'}})
        self.assertEqual((p.returncode, p.stdout), (0, ''), p.stderr)

    def test_stories_hook_reads_constraints_from_intent(self):
        d = tempfile.mkdtemp()
        for n, t in (('world.md', WORLD), ('intent.md', CLEAN_INTENT)):
            with open(os.path.join(d, n), 'w') as fh:
                fh.write(t)
        p = self.hook({'tool_name': 'Write', 'tool_input': {
            'file_path': os.path.join(d, 'stories.md'), 'content': CLEAN_STORIES}})
        self.assertEqual((p.returncode, p.stdout), (0, ''), p.stdout + p.stderr)

    def test_ideas_file_is_never_checked(self):
        p = self.hook({'tool_name': 'Write', 'tool_input': {
            'file_path': '/tmp/x/ideas-for-engineering.md', 'content': 'Use a confirm page and a GET /a/<t> link.'}})
        self.assertEqual((p.returncode, p.stdout), (0, ''))

    def test_fails_closed_on_marked_file_error(self):
        d = tempfile.mkdtemp()
        os.mkdir(os.path.join(d, 'world.md'))  # unreadable as a file -> checker error
        p = self.hook({'tool_name': 'Write', 'tool_input': {
            'file_path': os.path.join(d, 'intent.md'), 'content': CLEAN_INTENT}})
        self.assertEqual(p.returncode, 2)

    def test_bash_writes_to_pack_files_are_denied(self):
        for cmd in ('cat > /x/intent.md <<EOF\nhi\nEOF', 'echo hi >> world.md', 'sed -i "" s/a/b/ scenarios.md',
                    'tee /p/decisions.md < x', 'mv /tmp/a.md /p/intent.md', 'cp a.md scenarios.md'):
            p = self.hook({'tool_name': 'Bash', 'tool_input': {'command': cmd}})
            self.assertIn('deny', p.stdout, cmd)
        for cmd in ('cat /x/intent.md', 'python3 check_spec.py /x', 'ls /x', 'grep -n Then scenarios.md'):
            p = self.hook({'tool_name': 'Bash', 'tool_input': {'command': cmd}})
            self.assertEqual((p.returncode, p.stdout), (0, ''), cmd)

    def test_garbage_stdin_fails_closed(self):
        p = run(['--hook'], stdin='not json')
        self.assertEqual(p.returncode, 2)



class GlobalUseAndReviewTests(Base):
    """Installed once and used from any project, plus the gaps an outside review (agy) found."""

    def hook(self, payload):
        return run(['--hook'], stdin=json.dumps(payload), cwd=tempfile.gettempdir())

    def write_files(self, d, **files):
        for name, text in files.items():
            with open(os.path.join(d, name), 'w', encoding='utf-8') as fh:
                fh.write(text)

    def test_existing_unmarked_file_outside_a_pack_is_allowed(self):
        d = tempfile.mkdtemp()  # some other repo's docs folder, after spm loaded in this session
        self.write_files(d, **{'stories.md': '# Team stories\nnotes\n'})
        p = self.hook({'tool_name': 'Write', 'tool_input': {
            'file_path': os.path.join(d, 'stories.md'), 'content': 'Write to the audit_log table.'}})
        self.assertEqual((p.returncode, p.stdout), (0, ''), p.stdout)

    def test_existing_unmarked_file_next_to_a_marked_pack_is_checked(self):
        d = tempfile.mkdtemp()
        self.write_files(d, **{'world.md': WORLD, 'stories.md': '# stories\n'})
        p = self.hook({'tool_name': 'Write', 'tool_input': {
            'file_path': os.path.join(d, 'stories.md'), 'content': 'Write to the audit_log table.'}})
        self.assertIn('deny', p.stdout)

    def test_bash_gate_allows_unrelated_commands(self):
        for cmd in ('cp a.md docs/user_stories.md', 'mv notes.md hello-world.md',
                    'python3 -c "print(open(\'world.md\').read())"', 'rm -rf dist && git diff -- decisions.md'):
            p = self.hook({'tool_name': 'Bash', 'tool_input': {'command': cmd}})
            if cmd.startswith('rm -rf dist'):
                continue  # mixed clause: still denied on purpose (one regex, no shell parsing)
            self.assertEqual((p.returncode, p.stdout), (0, ''), cmd)

    def test_bash_gate_still_denies_pack_writes(self):
        for cmd in ('echo x > stories.md', 'printf x >> /p/redteam-1.md',
                    'python3 -c "open(\'stories.md\', \'w\').write(\'x\')"',
                    'python3 -c "import json; json.dump({}, open(\'decisions.md\', \'w\'))"',
                    'cp /tmp/x.md /p/world.md'):
            p = self.hook({'tool_name': 'Bash', 'tool_input': {'command': cmd}})
            self.assertIn('deny', p.stdout, cmd)

    def test_text_fence_outside_scenarios_is_still_checked(self):
        k = [x['kind'] for x in self.findings(self.pack(**{
            'stories.md': CLEAN_STORIES + '\n```text\nWrite a row to the audit_log table.\n```\n',
            'world.md': WORLD, 'intent.md': CLEAN_INTENT}))]
        self.assertIn('snake_case', k)

    def test_raw_input_fence_in_scenarios_is_data(self):
        sc = CLEAN_SCENARIOS + '\n```eml\nX-Mailer: Outlook\nSubject: approval_status\n```\n'
        self.assertEqual(self.findings(self.pack(**PACK | {'scenarios.md': sc})), [])

    def test_accepted_terms_heading_only_counts_in_world(self):
        k = [x['kind'] for x in self.findings(self.pack(**{
            'stories.md': CLEAN_STORIES + '\n## Accepted terms\n- write to the audit_log table\n',
            'world.md': WORLD, 'intent.md': CLEAN_INTENT}))]
        self.assertIn('snake_case', k)

    def test_bulleted_criteria_are_checked(self):
        k = self.findings(self.pack(**{
            'stories.md': CLEAN_STORIES + '- **AC-01.9** Approvals are fast.\n',
            'world.md': WORLD, 'intent.md': CLEAN_INTENT}))
        self.assertIn('actor', [x['kind'] for x in k])

    def test_scenario_needs_a_bold_then(self):
        sc = CLEAN_SCENARIOS.replace('**Then** Ayşe sees', 'Then Ayşe sees')
        msgs = [x['message'] for x in self.findings(self.pack(**PACK | {'scenarios.md': sc}))
                if x['kind'] == 'incomplete']
        self.assertTrue(any('Then' in m for m in msgs), msgs)

    def test_design_prose_outside_a_sourced_item_is_checked(self):
        bad = CLEAN_DESIGN.replace('### D-01', 'Clicking the button opens a page.\n\n### D-01')
        k = self.findings(self.pack(**PACK, **{'design-input.md': bad}))
        self.assertTrue(any(x['kind'] == 'ui' and x['line'] == 4 for x in k), k)
        self.assertFalse(any(x['kind'] == 'ui' and x['line'] > 5 for x in k), k)

    def test_acronym_identifiers_and_calls_with_arguments(self):
        intent = CLEAN_INTENT + 'Authenticate with OAuthClient using customerID and validate(input).\n'
        texts = {x['text'] for x in self.findings(self.pack(**{'intent.md': intent, 'world.md': WORLD}))}
        for t in ('OAuthClient', 'customerID', 'validate(input)'):
            self.assertIn(t, texts)

    def test_plural_words_in_prose_are_not_calls(self):
        intent = CLEAN_INTENT + 'Each approver(s) list stays with the tenant.\n'
        k = self.findings(self.pack(**{'intent.md': intent, 'world.md': WORLD}))
        self.assertFalse(any(x['kind'] == 'call' for x in k), k)

    def test_plural_tech_words_and_table_next_to_this_table(self):
        intent = (CLEAN_INTENT + 'The microservices send webhooks when feature flags change.\n'
                  'Rows go to the audit table, as shown in this table.\n')
        k = self.findings(self.pack(**{'intent.md': intent, 'world.md': WORLD}))
        texts = {x['text'].lower() for x in k if x['kind'] == 'tech-word'}
        for t in ('microservices', 'webhooks', 'feature flags', 'table'):
            self.assertIn(t, texts)

    def test_system_with_a_modal_verb_is_a_mechanism(self):
        k = self.findings(self.pack(**{
            'stories.md': CLEAN_STORIES + '**AC-01.8** For Ayşe, the system will store the decision.\n',
            'world.md': WORLD, 'intent.md': CLEAN_INTENT}))
        self.assertIn('mechanism', [x['kind'] for x in k])

class TriggerTests(unittest.TestCase):
    def trig(self, prompt):
        return subprocess.run([sys.executable, TRIGGER], input=json.dumps({'prompt': prompt}),
                              capture_output=True, text=True).stdout

    def test_trigger_words(self):
        for p in ('spm: approvals by email', 'use SuperPM here', 'super-project-manager please'):
            self.assertIn('spm', self.trig(p), p)

    def test_no_false_trigger(self):
        for p in ('the spmx file', 'rpm build', '/spm', 'spam'):
            self.assertEqual(self.trig(p), '', p)


if __name__ == '__main__':
    unittest.main()
