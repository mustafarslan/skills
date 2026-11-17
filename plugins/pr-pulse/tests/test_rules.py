"""Rule tests: every gate is proven in both directions (rejects AND accepts)."""
import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PR_PULSE_HOME", tempfile.mkdtemp(prefix="pr-pulse-test-"))
sys.path.insert(0, str(ROOT / "scripts"))
import rules  # noqa: E402

ME = "me-dev"
CFG = {"feedback_rounds": 2}


def review(who, state, sha, t):
    return {"author": {"login": who}, "state": state, "commit": {"oid": sha}, "submittedAt": t}


def good_pr():
    """An open, approved-at-head, green PR: the merge gate's happy path."""
    return {
        "url": "https://github.com/o/r/pull/1", "number": 1, "state": "OPEN", "isDraft": False,
        "author": {"login": ME}, "headRefOid": "h" * 40, "reviewDecision": "APPROVED",
        "reviews": [review("alice", "APPROVED", "h" * 40, "2026-11-09T10:00:00Z")],
        "comments": [], "statusCheckRollup": [{"conclusion": "SUCCESS"}],
    }


def row_for(pr, **kw):
    a = rules.activity(pr, ME)
    r = {"reviews_seen": a["human_reviews"], "comments_seen": a["human_comments"],
         "bots_seen": a["bots"], "feedback_rounds": 0, "bot_rounds": 0, "merge_ok_sha": ""}
    r.update(kw)
    return r


class MergeGateTest(unittest.TestCase):
    def test_accepts_happy_path(self):
        action, why = rules.merge_gate(good_pr(), ME, 0)
        self.assertEqual(action, "merge", why)

    def test_each_condition_alone_blocks(self):
        cases = {
            "draft": lambda p: p.update(isDraft=True),
            "not approved": lambda p: p.update(reviewDecision="REVIEW_REQUIRED"),
            "CI red": lambda p: p.update(statusCheckRollup=[{"conclusion": "FAILURE"}]),
            "CI pending": lambda p: p.update(statusCheckRollup=[{"state": "PENDING"}]),
            "CI none": lambda p: p.update(statusCheckRollup=[]),
            "changes requested": lambda p: p["reviews"].append(
                review("bob", "CHANGES_REQUESTED", "h" * 40, "2026-11-09T11:00:00Z")),
            "no approval by others": lambda p: p.update(
                reviews=[review(ME, "APPROVED", "h" * 40, "2026-11-09T10:00:00Z")]),
        }
        for name, mutate in cases.items():
            pr = good_pr()
            mutate(pr)
            action, why = rules.merge_gate(pr, ME, 0)
            self.assertIsNone(action, f"{name} should block, got {action}: {why}")
        action, _ = rules.merge_gate(good_pr(), ME, 1)
        self.assertIsNone(action, "a pending draft should block")

    def test_later_approval_clears_changes_requested(self):
        pr = good_pr()
        pr["reviews"] = [review("bob", "CHANGES_REQUESTED", "a" * 40, "2026-11-09T09:00:00Z"),
                         review("bob", "APPROVED", "h" * 40, "2026-11-09T10:00:00Z")]
        self.assertEqual(rules.merge_gate(pr, ME, 0)[0], "merge")

    def test_moved_head_asks_owner_not_merge(self):
        pr = good_pr()
        pr["headRefOid"] = "n" * 40
        action, why = rules.merge_gate(pr, ME, 0)
        self.assertEqual(action, "merge-check", why)
        self.assertIn("hhhhhhhhh..nnnnnnnnn", why)

    def test_moved_head_merges_only_at_the_okd_head(self):
        pr = good_pr()
        pr["headRefOid"] = "n" * 40
        self.assertEqual(rules.merge_gate(pr, ME, 0, merge_ok_sha="n" * 40)[0], "merge")
        # OK was for another head: ask again
        self.assertEqual(rules.merge_gate(pr, ME, 0, merge_ok_sha="x" * 40)[0], "merge-check")


class OwnPrActionTest(unittest.TestCase):
    def test_first_sight_never_acts(self):
        action, _, seen = rules.own_pr_action(good_pr(), None, ME, CFG, False, 0)
        self.assertIsNone(action)
        self.assertEqual(seen, (0, 0, 0))   # an empty approval is nothing to address

    def test_new_review_queues_feedback(self):
        pr = good_pr()
        row = row_for(pr)
        pr["reviews"].append(review("bob", "COMMENTED", "h" * 40, "2026-11-09T12:00:00Z"))
        action, note, seen = rules.own_pr_action(pr, row, ME, CFG, False, 0)
        self.assertEqual(action, "feedback", note)
        self.assertEqual(seen, (1, 0, 0))

    def test_my_own_and_ignored_bot_activity_do_not_trigger(self):
        pr = good_pr()
        row = row_for(pr)
        pr["reviews"].append(review(ME, "COMMENTED", "h" * 40, "2026-11-09T12:00:00Z"))
        pr["comments"].append({"author": {"login": "linear"}})
        pr["comments"].append({"author": {"login": "github-actions[bot]"}})
        action, _, _ = rules.own_pr_action(pr, row, ME, CFG, False, 0)
        self.assertEqual(action, "merge")   # no feedback; still mergeable


class ReviewBotsWaitForHumansTest(unittest.TestCase):
    """Owner rule: wait for a human review, then handle bots + humans in one round."""

    def fresh_pr(self):
        pr = good_pr()
        pr.update(reviewDecision="REVIEW_REQUIRED", reviews=[], comments=[])
        return pr

    def test_coderabbit_alone_waits_and_is_not_marked_handled(self):
        pr = self.fresh_pr()
        row = row_for(pr)
        pr["reviews"].append(review("coderabbitai", "COMMENTED", "h" * 40, "t1"))
        pr["comments"].append({"author": {"login": "claude"}})
        action, note, seen = rules.own_pr_action(pr, row, ME, CFG, False, 0)
        self.assertIsNone(action, note)
        self.assertIn("waiting for a human review", note)
        self.assertEqual(seen[2], 0)        # bots stay pending

    def test_first_human_review_takes_the_bots_along(self):
        pr = self.fresh_pr()
        row = row_for(pr)
        pr["reviews"].append(review("coderabbitai", "COMMENTED", "h" * 40, "t1"))
        pr["reviews"].append(review("bob", "COMMENTED", "h" * 40, "t2"))
        action, note, seen = rules.own_pr_action(pr, row, ME, CFG, False, 0)
        self.assertEqual(action, "feedback")
        self.assertIn("plus 1 from review bots", note)
        self.assertEqual(seen, (1, 0, 1))

    def test_empty_approval_starts_no_round_unless_bots_wait(self):
        pr = self.fresh_pr()
        row = row_for(pr)
        pr["reviews"].append(review("bob", "APPROVED", "h" * 40, "t2"))
        pr["reviewDecision"] = "APPROVED"
        self.assertEqual(rules.own_pr_action(pr, row, ME, CFG, False, 0)[0], "merge")
        pr["reviews"].insert(0, review("coderabbitai", "COMMENTED", "h" * 40, "t1"))
        self.assertEqual(rules.own_pr_action(pr, row, ME, CFG, False, 0)[0], "feedback-bots")

    def test_bot_rounds_after_a_human_are_capped_without_hold(self):
        pr = good_pr()                      # alice approved: a human has reviewed
        row = row_for(pr, bot_rounds=0)
        pr["reviews"].append(review("coderabbitai", "COMMENTED", "h" * 40, "t9"))
        self.assertEqual(rules.own_pr_action(pr, row, ME, CFG, False, 0)[0], "feedback-bots")
        row = row_for(good_pr(), bot_rounds=2)
        action, _, seen = rules.own_pr_action(pr, row, ME, CFG, False, 0)
        self.assertEqual(action, "merge")   # cap reached: stop chasing the bot, no hold
        self.assertEqual(seen[2], 1)

    def test_bot_changes_requested_does_not_block_merge(self):
        pr = good_pr()
        pr["reviews"].append(review("coderabbitai", "CHANGES_REQUESTED", "h" * 40, "2026-11-09T11:00:00Z"))
        self.assertEqual(rules.merge_gate(pr, ME, 0)[0], "merge")
        pr["reviews"].append(review("bob", "CHANGES_REQUESTED", "h" * 40, "2026-11-09T12:00:00Z"))
        self.assertIsNone(rules.merge_gate(pr, ME, 0)[0])

    def test_bot_approval_is_not_an_approval(self):
        pr = good_pr()
        pr["reviews"] = [review("coderabbitai", "APPROVED", "h" * 40, "t1")]
        self.assertIsNone(rules.merge_gate(pr, ME, 0)[0])


class OwnPrActionMore(unittest.TestCase):
    def test_round_cap_asks_instead(self):
        pr = good_pr()
        row = row_for(pr, feedback_rounds=2)
        pr["comments"].append({"author": {"login": "bob"}})
        self.assertEqual(rules.own_pr_action(pr, row, ME, CFG, False, 0)[0], "ask")
        row = row_for(pr, feedback_rounds=1)
        row["comments_seen"] = 0
        self.assertEqual(rules.own_pr_action(pr, row, ME, CFG, False, 0)[0], "feedback")

    def test_active_job_or_draft_or_closed_blocks(self):
        pr = good_pr()
        row = row_for(pr)
        self.assertIsNone(rules.own_pr_action(pr, row, ME, CFG, True, 0)[0])
        pr2 = dict(pr, isDraft=True)
        self.assertIsNone(rules.own_pr_action(pr2, row, ME, CFG, False, 0)[0])
        pr3 = dict(pr, state="MERGED")
        self.assertIsNone(rules.own_pr_action(pr3, row, ME, CFG, False, 0)[0])


class HoldTest(unittest.TestCase):
    """agy finding 1: after the round cap says 'ask', nothing may auto-merge."""

    def test_hold_blocks_merge_and_release_allows_it(self):
        pr = good_pr()
        row = row_for(pr, hold=1)
        action, why, _ = rules.own_pr_action(pr, row, ME, CFG, False, 0)
        self.assertIsNone(action, why)
        row = row_for(pr, hold=0)
        self.assertEqual(rules.own_pr_action(pr, row, ME, CFG, False, 0)[0], "merge")


class ReviewSkipTest(unittest.TestCase):
    def pr(self, **kw):
        p = {"author": {"login": "alice"}, "state": "OPEN", "isDraft": False, "reviewDecision": "",
             "headRefOid": "h" * 40, "reviews": []}
        p.update(kw)
        return p

    def test_go_and_each_skip(self):
        mapped = {"o/r"}
        self.assertEqual(rules.review_skip_reason(self.pr(), ME, mapped, "o/r"), "")
        self.assertEqual(rules.review_skip_reason(self.pr(), ME, mapped, "x/y"), "repo not mapped")
        self.assertEqual(rules.review_skip_reason(self.pr(author={"login": ME}), ME, mapped, "o/r"), "own PR")
        self.assertEqual(rules.review_skip_reason(self.pr(state="MERGED"), ME, mapped, "o/r"), "closed or merged")
        self.assertEqual(rules.review_skip_reason(self.pr(isDraft=True), ME, mapped, "o/r"), "draft")
        self.assertEqual(rules.review_skip_reason(self.pr(reviewDecision="APPROVED"), ME, mapped, "o/r"),
                         "already approved")
        done = self.pr(reviews=[review(ME, "COMMENTED", "h" * 40, "t")])
        self.assertEqual(rules.review_skip_reason(done, ME, mapped, "o/r"), "already reviewed at head")
        older = self.pr(reviews=[review(ME, "COMMENTED", "o" * 40, "t")])
        self.assertEqual(rules.review_skip_reason(older, ME, mapped, "o/r"), "")


class ThreadReplyTest(unittest.TestCase):
    URL = "https://github.com/o/r/pull/12"
    PARENT = {"user": "UALICE", "ts": "100.0", "text": f"Fixes the importer <{URL}|o/r#12>"}

    def test_author_tags_me_in_the_thread(self):
        r = {"user": "UALICE", "ts": "101.0", "text": "<@UME> fixed both points, please take another look"}
        self.assertEqual(rules.classify_reply(r, self.PARENT, "UME", "UBOT"), ("re-review", [self.URL]))

    def test_link_in_the_reply_wins(self):
        other = "https://github.com/o/r/pull/13"
        r = {"user": "UALICE", "ts": "101.0", "text": f"<@UME> moved it to {other}"}
        self.assertEqual(rules.classify_reply(r, self.PARENT, "UME", "UBOT"), ("re-review", [other]))

    def test_not_a_request(self):
        untagged = {"user": "UALICE", "ts": "101.0", "text": "fixed both points"}
        self.assertEqual(rules.classify_reply(untagged, self.PARENT, "UME", "UBOT"), ("ignore", "not tagged"))
        other_tag = {"user": "UALICE", "ts": "101.0", "text": "<@UBOB> fixed it"}
        self.assertEqual(rules.classify_reply(other_tag, self.PARENT, "UME", "UBOT")[0], "ignore")
        mine = {"user": "UME", "ts": "101.0", "text": "<@UME> note to self"}
        self.assertEqual(rules.classify_reply(mine, self.PARENT, "UME", "UBOT"), ("ignore", "my own reply"))
        bot = {"user": "UBOT", "ts": "101.0", "text": "Alex's review: approved <@UME>"}
        self.assertEqual(rules.classify_reply(bot, self.PARENT, "UME", "UBOT"), ("ignore", "own bot"))
        no_link = {"user": "UALICE", "ts": "100.0", "text": "lunch?"}
        r = {"user": "UALICE", "ts": "101.0", "text": "<@UME> coming?"}
        self.assertEqual(rules.classify_reply(r, no_link, "UME", "UBOT")[0], "ignore")
        self.assertEqual(rules.classify_reply(r, self.PARENT, "", "UBOT")[0], "ignore")


class SlackTest(unittest.TestCase):
    URL = "https://github.com/o/r/pull/12"

    def test_untagged_share_goes_to_pool(self):
        m = {"user": "UALICE", "text": f"Fixes the importer <{self.URL}|o/r#12>"}
        self.assertEqual(rules.classify_slack(m, "UME", "UBOT"), ("pool", [self.URL]))

    def test_tag_means_re_review(self):
        m = {"user": "UALICE", "text": f"<@UME> addressed your comments {self.URL}"}
        self.assertEqual(rules.classify_slack(m, "UME", "UBOT"), ("re-review", [self.URL]))

    def test_tag_of_someone_else_is_still_pool(self):
        m = {"user": "UALICE", "text": f"<@UBOB> please look {self.URL}"}
        self.assertEqual(rules.classify_slack(m, "UME", "UBOT")[0], "pool")

    def test_ignored(self):
        self.assertEqual(rules.classify_slack({"user": "UA", "text": "no link"}, "UME", "UBOT")[0], "ignore")
        own_bot = {"user": "UBOT", "text": f"Alex's review: approved <@UME> {self.URL}"}
        self.assertEqual(rules.classify_slack(own_bot, "UME", "UBOT"), ("ignore", "own bot"))
        by_bot_id = {"bot_id": "B1", "text": f"<@UME> {self.URL}"}
        self.assertEqual(rules.classify_slack(by_bot_id, "UME", "UBOT", "B1"), ("ignore", "own bot"))
        mine = {"user": "UME", "text": f"my PR {self.URL}"}
        self.assertEqual(rules.classify_slack(mine, "UME", "UBOT"), ("ignore", "my own share"))

    def test_dedupes_urls(self):
        m = {"user": "UA", "text": f"{self.URL} and again <{self.URL}|link>"}
        self.assertEqual(rules.classify_slack(m, "UME", "UBOT"), ("pool", [self.URL]))

    def test_verdicts(self):
        self.assertEqual(rules.verdict_for("APPROVED", 0), "approved")
        self.assertEqual(rules.verdict_for("APPROVED", 3), "lgtm with comments")
        self.assertEqual(rules.verdict_for("CHANGES_REQUESTED", 2), "request changes")
        self.assertEqual(rules.verdict_for("COMMENTED", 1), "comments added")
        self.assertIsNone(rules.verdict_for("PENDING", 0))
        self.assertEqual(rules.verdict_text("Alex", "approved", "UA", self.URL, "o/r#12"),
                         f"Alex's review: approved <@UA> · <{self.URL}|o/r#12>")
        self.assertNotIn("<@", rules.verdict_text("Alex", "approved", "", self.URL, "o/r#12"))

    def test_verdict_reply_carries_the_reviewers_lines(self):
        txt = rules.verdict_text("Ada", "comments added", "UA", self.URL, "o/r#12",
                                 "Solid change.\nOne open question below.")
        self.assertEqual(txt, f"Ada's review: comments added <@UA> · <{self.URL}|o/r#12>\n"
                              "> Solid change. One open question below.")

    def test_sharer_match_is_conservative(self):
        self.assertTrue(rules.sharer_matches("alice", "Alice Smith", {"real_name": "Alice Smith"}))
        self.assertTrue(rules.sharer_matches("alice", "", {"display_name": "alice"}))
        self.assertFalse(rules.sharer_matches("alice", "Alice Smith", {"real_name": "Bob Jones"}))
        self.assertFalse(rules.sharer_matches("alice", "", {}))
        # first-name match (the sharer is the author): GitHub "Jane Doering" vs Slack "Jane"
        self.assertTrue(rules.sharer_matches("jdoering", "Jane Doering", {"real_name": "Jane", "display_name": "Jane"}))
        self.assertFalse(rules.sharer_matches("jdoering", "Jane Doering", {"real_name": "Janet"}))
        self.assertFalse(rules.sharer_matches("jdoering", "", {"real_name": "Jane"}))


if __name__ == "__main__":
    unittest.main()
