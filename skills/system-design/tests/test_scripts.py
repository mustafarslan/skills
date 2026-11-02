"""Tests for capacity_calc.py and check_design.py (stdlib unittest).

Run from the repo root:  python3 -I -m unittest discover -s skills/system-design/tests
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
sys.path.insert(0, SCRIPTS)

import capacity_calc  # noqa: E402
import check_design  # noqa: E402


def calc(*argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        capacity_calc.main(list(argv))
    return json.loads(buf.getvalue())


class CapacityCalcTests(unittest.TestCase):
    def test_traffic_hand_worked(self):
        out = calc("--dau", "1e8", "--reads-per-user", "20", "--writes-per-user", "2")
        t = out["traffic"]
        self.assertAlmostEqual(t["avg_read_qps"], 23148.15, places=2)   # 2e9 / 86400
        self.assertAlmostEqual(t["avg_write_qps"], 2314.81, places=2)
        self.assertAlmostEqual(t["peak_read_qps"], 69444.44, places=2)  # x3 default
        self.assertEqual(t["read_write_ratio"], 10.0)

    def test_storage_hand_worked(self):
        out = calc("--dau", "1e8", "--writes-per-user", "2", "--write-bytes", "1024",
                   "--years", "3", "--replication", "3")
        s = out["storage"]
        # 2e8 writes x 1 KiB = 190.735 GiB/day; x 365 x 3 = 203.96 TiB; x3 replicas
        self.assertAlmostEqual(s["logical_per_day_gib"], 190.735, places=3)
        self.assertAlmostEqual(s["logical_total_tib"], 203.96, places=2)
        self.assertAlmostEqual(s["replicated_total_tib"], 611.879, places=2)

    def test_growth_compounds(self):
        flat = calc("--dau", "1e6", "--write-bytes", "1000", "--years", "2")["storage"]
        grow = calc("--dau", "1e6", "--write-bytes", "1000", "--years", "2",
                    "--yearly-growth", "1")["storage"]
        # year 1 x1 + year 2 x2 = 3 years' worth vs 2
        self.assertAlmostEqual(grow["logical_total_tib"] / flat["logical_total_tib"], 1.5, places=2)

    def test_partial_year(self):
        half = calc("--dau", "1e6", "--write-bytes", "1000", "--years", "0.5")["storage"]
        full = calc("--dau", "1e6", "--write-bytes", "1000", "--years", "1")["storage"]
        self.assertAlmostEqual(half["logical_total_tib"] * 2, full["logical_total_tib"], places=3)

    def test_triggers_fire_and_carry_basis(self):
        out = calc("--dau", "1e8", "--reads-per-user", "20", "--writes-per-user", "2")
        rules = {t["rule"]: t for t in out["triggers"]}
        self.assertIn("single_node_read_qps", rules)        # 69k > 20k
        self.assertNotIn("single_primary_write_qps", rules)  # 6.9k < 10k
        self.assertTrue(rules["single_node_read_qps"]["basis"])

    def test_small_system_fires_nothing(self):
        out = calc("--dau", "1e4", "--write-bytes", "500", "--read-bytes", "2000", "--db-ms", "5")
        self.assertEqual(out["triggers"], [])

    def test_littles_law(self):
        out = calc("--dau", "8.64e6", "--reads-per-user", "1", "--writes-per-user", "0",
                   "--peak", "1", "--db-ms", "10", "--service-ms", "50")
        c = out["concurrency"]
        self.assertEqual(c["busy_db_connections_at_peak"], 1.0)   # 100 qps x 0.01 s
        self.assertEqual(c["in_flight_requests_at_peak"], 5.0)    # 100 qps x 0.05 s

    def test_availability(self):
        out = calc("--serial", "0.999,99.9%", "--parallel", "0.99,0.99")
        av = out["availability"]
        self.assertAlmostEqual(av["serial_chain"]["availability"], 0.998001, places=6)
        self.assertAlmostEqual(av["parallel_group"]["availability"], 0.9999, places=6)
        self.assertAlmostEqual(av["combined"]["availability"], 0.998001 * 0.9999, places=6)
        self.assertGreater(av["combined"]["downtime"]["per_month_minutes"], 0)

    def test_vectors_formula(self):
        v = calc("--vectors", "1e7", "--dim", "768", "--hnsw-m", "16", "--pq-bytes", "64")["vectors"]
        gib = 1024 ** 3
        self.assertAlmostEqual(v["hnsw_fp32_gib"], round(1e7 * (768 * 4 + 16 * 16) * 1.2 / gib, 2))
        self.assertAlmostEqual(v["hnsw_int8_gib"], round(1e7 * (768 + 256) * 1.2 / gib, 2))
        self.assertAlmostEqual(v["ivf_pq_gib"], round(1e7 * 72 / gib, 2))

    def test_sensitivity_band(self):
        out = calc("--dau", "1e8", "--reads-per-user", "20", "--writes-per-user", "2",
                   "--assumed", "dau")
        band = out["sensitivity"]["ranges"]["traffic.peak_write_qps"]
        self.assertAlmostEqual(band[0], 6944.44 / 2, places=1)
        self.assertAlmostEqual(band[1], 6944.44 * 2, places=1)
        # writes cross 10k only at the high end: the decision rests on the guess
        self.assertIn("single_primary_write_qps", out["sensitivity"]["triggers_only_at_high"])

    def test_peak_band_never_below_one(self):
        out = calc("--dau", "1e6", "--peak", "1.2", "--assumed", "peak", "--band", "0.1,2")
        lo = out["sensitivity"]["ranges"]["traffic.peak_read_qps"][0]
        self.assertGreaterEqual(lo, out["traffic"]["avg_read_qps"])

    def test_burst_mode(self):
        out = calc("--peak-read-qps", "166667", "--peak-write-qps", "33333",
                   "--db-ms", "3", "--db-read-fraction", "0.01")
        self.assertEqual(out["traffic"]["peak_db_read_qps"], 1666.67)
        rules = {t["rule"] for t in out["triggers"]}
        self.assertIn("single_primary_write_qps", rules)
        self.assertIn("redis_single_instance_ops", rules)
        self.assertNotIn("single_node_read_qps", rules)   # the cache absorbs 99%
        self.assertNotIn("storage", out)

    def test_db_read_trigger_respects_cache(self):
        hit = calc("--dau", "1e8", "--reads-per-user", "20", "--db-read-fraction", "0.1")
        self.assertNotIn("single_node_read_qps", {t["rule"] for t in hit["triggers"]})

    def test_redis_trigger_without_read_bytes(self):
        out = calc("--dau", "1e9", "--reads-per-user", "20")
        self.assertIn("redis_single_instance_ops", {t["rule"] for t in out["triggers"]})

    def test_burst_and_dau_conflict(self):
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            capacity_calc.main(["--dau", "1e6", "--peak-read-qps", "100"])

    def test_errors(self):
        for argv in ([], ["--dau", "-1"], ["--dau", "1e6", "--assumed", "replication"],
                     ["--dau", "1e6", "--band", "2,3"], ["--serial", "1.5x"],
                     ["--dau", "1e6", "--hot-fraction", "2"], ["--dau", "1e6", "--peak", "0.5"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()):
                    capacity_calc.main(argv)

    def test_cli_runs_isolated(self):
        r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "capacity_calc.py"),
                            "--dau", "1e6"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("traffic", json.loads(r.stdout))


GOOD = """# Shop - design

## Summary
A shop.

## Requirements
### Functional requirements
- buyers reserve stock
### Non-functional requirements
- checkout p99 < 300 ms at peak (given)
- 99.95% availability monthly (assumed)
### Non-goals
- no marketplace sellers in v1

## Estimation
Peak writes 1,200/s; 3-year storage 4 TiB.

## Consistency and failure modes
Cache flush -> DB pool exhaustion -> shed load.

## Trade-offs
| Decision | Solves | Worsens | Change it when |
|---|---|---|---|
| Postgres primary | ACID | one writer | peak writes > 8k/s for 15 min |
| Redis cache | read load | staleness | hit ratio < 80% |
| Sub-counters | hot SKU | audits | buy rate drops below 50/s |

## Evolution
At 10x, shard orders by tenant_id.

## Review log
Reviewer: 2 findings accepted.
"""

ADR = """# 0001. Use Postgres

## Context
1,200 writes/s.

## Decision
Postgres.

## Consequences
One writer.

Change it when: peak writes exceed 8k/s.
"""


class CheckDesignTests(unittest.TestCase):
    def run_check(self, text, kind="design"):
        return check_design.check(text, kind)[0]

    def test_good_design_passes(self):
        self.assertEqual(self.run_check(GOOD), [])

    def test_review_log_required_unless_draft(self):
        text = GOOD.replace("## Review log\nReviewer: 2 findings accepted.\n", "")
        self.assertTrue(any("review log" in p for p in self.run_check(text)))
        self.assertEqual(check_design.check(text, "design", draft=True)[0], [])

    def test_good_adr_passes(self):
        self.assertEqual(self.run_check(ADR, "adr"), [])

    def test_missing_sections(self):
        text = GOOD.replace("### Non-goals", "### Other").replace("## Evolution", "## Later")
        problems = " ".join(self.run_check(text))
        self.assertIn("non-goals", problems)
        self.assertIn("evolution", problems)

    def test_vague_trigger_fails(self):
        text = GOOD.replace("hit ratio < 80%", "when it gets slow")
        problems = self.run_check(text)
        self.assertTrue(any("Redis cache" in p for p in problems), problems)

    def test_number_without_comparison_fails(self):
        text = GOOD.replace("hit ratio < 80%", "v2")
        self.assertTrue(any("Redis cache" in p for p in self.run_check(text)))

    def test_too_few_rows(self):
        text = GOOD.replace("| Sub-counters | hot SKU | audits | buy rate drops below 50/s |\n", "")
        self.assertTrue(any("2 row" in p for p in self.run_check(text)))

    def test_nfr_needs_numbers(self):
        text = GOOD.replace("checkout p99 < 300 ms at peak (given)", "fast checkout") \
                   .replace("99.95% availability monthly (assumed)", "highly available")
        self.assertTrue(any("numeric target" in p for p in self.run_check(text)))

    def test_placeholders_fail(self):
        text = GOOD.replace("A shop.", "TODO write summary")
        self.assertTrue(any("placeholder" in p for p in self.run_check(text)))

    def test_code_is_not_a_placeholder(self):
        text = GOOD.replace("A shop.", "Queues are named `dedicated-<tenant>`.\n\n"
                            "```sql\nUPDATE t SET x = 1 WHERE <condition>;\n```\n")
        self.assertEqual(self.run_check(text), [])

    def test_subheadings_stay_in_parent_section(self):
        text = GOOD.replace("## Estimation\nPeak writes 1,200/s; 3-year storage 4 TiB.\n",
                            "## Estimation\n### Traffic\nPeak writes 1,200/s.\n### Storage\n4 TiB.\n")
        text = text.replace("### Non-functional requirements\n",
                            "### Non-functional requirements\n#### Latency\n")
        self.assertEqual(self.run_check(text), [])

    def test_trigger_column_in_other_tables_is_not_tradeoff(self):
        text = GOOD + "\n| Scale | Change | Trigger example |\n|---|---|---|\n| Today | monolith | - |\n"
        self.assertEqual(self.run_check(text), [])

    def test_html_tags_are_not_placeholders(self):
        text = GOOD.replace("A shop.", "A shop.<br>Two lines. <details><summary>More</summary>x</details>")
        self.assertEqual(self.run_check(text), [])

    def test_headings_inside_code_fences_ignored(self):
        text = GOOD.replace("## Evolution\nAt 10x, shard orders by tenant_id.\n",
                            "```\n## Evolution\n```\n")
        self.assertTrue(any("evolution" in p for p in self.run_check(text)))

    def test_adr_without_numeric_trigger_fails(self):
        text = ADR.replace("Change it when: peak writes exceed 8k/s.", "Revisit later.")
        self.assertTrue(any("trigger" in p for p in self.run_check(text, "adr")))

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            good, bad = os.path.join(d, "good.md"), os.path.join(d, "bad.md")
            with open(good, "w") as fh:
                fh.write(GOOD)
            with open(bad, "w") as fh:
                fh.write("# nothing\n")
            script = os.path.join(SCRIPTS, "check_design.py")
            ok = subprocess.run([sys.executable, "-I", script, good], capture_output=True, text=True)
            ko = subprocess.run([sys.executable, "-I", script, bad, "--json"], capture_output=True, text=True)
            missing = subprocess.run([sys.executable, "-I", script, os.path.join(d, "nope.md")],
                                     capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertIn("DESIGN_OK", ok.stdout)
        self.assertEqual(ko.returncode, 1)
        self.assertFalse(json.loads(ko.stdout)["ok"])
        self.assertEqual(missing.returncode, 2)


if __name__ == "__main__":
    unittest.main()
