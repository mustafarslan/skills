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
    def test_cache_survives_zero_writes(self):
        out = calc("--dau", "1e6", "--writes-per-user", "0", "--write-bytes", "100", "--read-bytes", "1000")
        self.assertIn("cache", out)

    def test_scale_path_shows_what_fires_at_10x_and_100x(self):
        out = calc("--dau", "1e6", "--reads-per-user", "20", "--writes-per-user", "2", "--scale", "10,100")
        sp = out["scale_path"]
        self.assertEqual(out["triggers"], [])                       # today: nothing fires
        self.assertAlmostEqual(sp["10x"]["headlines"]["traffic.peak_write_qps"],
                               out["traffic"]["peak_write_qps"] * 10, places=1)
        self.assertIn("single_node_read_qps", sp["100x"]["triggers"])      # reads, not writes, break first
        self.assertNotIn("single_primary_write_qps", sp["100x"]["triggers"])

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

    # --- C3c-f: restore time, LLM serving, streams, cost (hand-worked) -------------------
    def test_restore_time_vs_rto(self):
        out = calc("--data-tib", "10", "--restore-mbps", "500", "--rto-min", "60")
        # 10 x 1024^4 B / 5e8 B/s / 3600 = 6.108 h
        self.assertAlmostEqual(out["restore"]["restore_hours"], 6.11, places=2)
        self.assertIn("restore_exceeds_rto", {t["rule"] for t in out["triggers"]})
        sharded = calc("--data-tib", "10", "--restore-mbps", "500", "--rto-min", "60", "--shards", "8")
        self.assertAlmostEqual(sharded["restore"]["restore_hours"], 0.76, places=2)
        self.assertNotIn("restore_exceeds_rto", {t["rule"] for t in sharded["triggers"]})

    def test_restore_uses_storage_estimate(self):
        out = calc("--dau", "1e6", "--writes-per-user", "1", "--write-bytes", "1000", "--years", "1",
                   "--restore-mbps", "100")
        self.assertAlmostEqual(out["restore"]["data_tib"], out["storage"]["logical_total_tib"], places=3)

    def test_llm_serving_kv_cache_hand_worked(self):
        out = calc("--llm-rps", "10", "--prompt-tokens", "2000", "--output-tokens", "500",
                   "--decode-tps", "50", "--layers", "80", "--kv-heads", "8", "--head-dim", "128",
                   "--context", "8192", "--peak", "1")
        llm = out["llm"]
        self.assertEqual(llm["kv_bytes_per_token"], 327680)          # 2 x 80 x 8 x 128 x 2
        self.assertAlmostEqual(llm["kv_gib_per_sequence"], 2.5, places=3)
        self.assertAlmostEqual(llm["generation_seconds"], 10.0)        # 500 / 50
        self.assertAlmostEqual(llm["concurrent_streams_at_peak"], 100.0)  # 10 rps x 10 s
        self.assertAlmostEqual(llm["kv_gib_at_peak"], 250.0, places=1)

    def test_llm_cost_and_gpu_trigger(self):
        out = calc("--llm-rps", "10", "--prompt-tokens", "2000", "--output-tokens", "500",
                   "--price-in", "3", "--price-out", "15", "--decode-tps", "50", "--layers", "80",
                   "--kv-heads", "8", "--head-dim", "128", "--context", "8192", "--peak", "1",
                   "--gpu-mem-gib", "80", "--weights-gib", "40", "--gpus", "4")
        llm = out["llm"]
        self.assertAlmostEqual(llm["cost_per_request_usd"], 0.0135)     # (2000x3 + 500x15) / 1e6
        self.assertAlmostEqual(llm["cost_per_day_usd"], 0.0135 * 10 * 86400, places=2)
        # KV room = 4 x (80 - 40) = 160 GiB < 250 GiB needed
        self.assertIn("kv_cache_exceeds_gpu", {t["rule"] for t in out["triggers"]})

    def test_streams_partitions(self):
        out = calc("--events-per-sec", "20000", "--event-bytes", "1000", "--partition-mbps", "10",
                   "--consumer-ms", "5", "--partitions", "12")
        st = out["streams"]
        self.assertEqual(st["partitions_for_throughput"], 2)     # 20 MB/s / 10 MB/s
        self.assertEqual(st["partitions_for_consumers"], 100)    # 20,000/s x 0.005 s
        self.assertEqual(st["bound_by"], "consumers")
        self.assertIn("consumer_lag_risk", {t["rule"] for t in out["triggers"]})
        ok = calc("--events-per-sec", "20000", "--event-bytes", "1000", "--partition-mbps", "10",
                  "--consumer-ms", "5", "--partitions", "128")
        self.assertNotIn("consumer_lag_risk", {t["rule"] for t in ok["triggers"]})

    def test_cost_names_largest_line(self):
        out = calc("--dau", "1e6", "--reads-per-user", "10", "--writes-per-user", "1",
                   "--write-bytes", "1000", "--read-bytes", "100000", "--years", "1",
                   "--price-storage-gb-month", "0.023", "--price-egress-gb", "0.09",
                   "--price-instance-hour", "0.2", "--instances", "4")
        cost = out["cost"]
        self.assertAlmostEqual(cost["storage_month_usd"], 25.19, places=2)   # 1,095 GB x 0.023
        self.assertAlmostEqual(cost["egress_month_usd"], 2700.0, places=1)   # 30,000 GB x 0.09
        self.assertAlmostEqual(cost["compute_month_usd"], 584.0, places=1)   # 4 x 0.2 x 730
        self.assertEqual(cost["largest_line"], "egress")

    def test_cost_has_no_builtin_prices(self):
        out = calc("--dau", "1e6", "--write-bytes", "1000", "--read-bytes", "1000")
        self.assertNotIn("cost", out)

    def test_cost_scales(self):
        out = calc("--dau", "1e6", "--reads-per-user", "10", "--read-bytes", "100000",
                   "--price-egress-gb", "0.09", "--scale", "10")
        self.assertAlmostEqual(out["scale_path"]["10x"]["headlines"]["cost.total_month_usd"],
                               out["cost"]["total_month_usd"] * 10, places=0)

    def test_daily_volumes_without_dau(self):
        # "100M links a month, reads ~100x writes": no DAU in the brief
        out = calc("--writes-per-day", str(1e8 / 30), "--reads-per-day", str(1e10 / 30),
                   "--write-bytes", "500", "--years", "5", "--read-bytes", "500")
        self.assertAlmostEqual(out["traffic"]["avg_write_qps"], 38.58, places=2)
        self.assertAlmostEqual(out["traffic"]["avg_read_qps"], 3858.02, places=1)
        self.assertIn("storage", out)
        self.assertIn("cache", out)
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()):
            capacity_calc.main(["--dau", "1e6", "--writes-per-day", "100"])

    def test_out_writes_the_json_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.calc.json")
            printed = calc("--dau", "1e6", "--out", path)
            with open(path) as fh:
                self.assertEqual(json.load(fh), printed)

    def test_zero_divisors_are_rejected(self):
        for argv in (["--data-tib", "1", "--restore-mbps", "0"],
                     ["--llm-rps", "1", "--decode-tps", "0"],
                     ["--events-per-sec", "100", "--partition-mbps", "0"],
                     ["--events-per-sec", "100", "--consumer-ms", "0"],
                     ["--events-per-sec", "100", "--consumer-ms", "5", "--partitions", "0"],
                     ["--events-per-sec", "100", "--partition-mbps", "-10"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()):
                    capacity_calc.main(argv)

    def test_llm_prices_reach_the_cost_section(self):
        out = calc("--llm-rps", "10", "--prompt-tokens", "2000", "--output-tokens", "500",
                   "--price-in", "3", "--price-out", "15")
        self.assertEqual(out["cost"]["largest_line"], "llm")
        self.assertAlmostEqual(out["cost"]["llm_month_usd"], out["llm"]["cost_per_month_usd"], places=2)

    def test_scale_grows_compute_with_load(self):
        out = calc("--dau", "1e6", "--price-instance-hour", "0.2", "--instances", "4", "--scale", "10")
        self.assertAlmostEqual(out["scale_path"]["10x"]["headlines"]["cost.total_month_usd"],
                               out["cost"]["total_month_usd"] * 10, places=0)

    def test_new_inputs_can_be_marked_assumed(self):
        out = calc("--data-tib", "10", "--restore-mbps", "500", "--rto-min", "60",
                   "--assumed", "restore-mbps,data-tib")
        self.assertIn("restore.restore_hours", out["sensitivity"]["ranges"])

    def test_thresholds_have_basis_and_verified(self):
        for name, t in capacity_calc.THRESHOLDS.items():
            with self.subTest(name=name):
                self.assertTrue(t.get("basis"))
                self.assertRegex(t.get("verified", ""), r"^\d{4}-\d{2}$")

    def test_errors(self):
        for argv in ([], ["--dau", "-1"], ["--dau", "1e6", "--assumed", "replication"],
                     ["--dau", "1e6", "--band", "2,3"], ["--serial", "1.5x"],
                     ["--dau", "1e6", "--hot-fraction", "2"], ["--dau", "1e6", "--peak", "0.5"],
                     ["--dau", "1e6", "--write-bytes", "100", "--replication", "0"],
                     ["--dau", "1e6", "--write-bytes", "100", "--years", "0"],
                     ["--dau", "1e6", "--write-bytes", "100", "--yearly-growth", "-1"],
                     ["--dau", "1e6", "--write-bytes", "100", "--index-overhead", "-0.5"]):
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
From capacity_calc.py (DAU given, peak 3x assumed): peak writes 1,200/s; 3-year storage 4 TiB.

## Consistency and failure modes
Cache flush -> DB pool exhaustion -> shed load.
DR: warm standby, RPO 5 min, RTO 30 min (assumed).

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

    # --- added by change.md -------------------------------------------------
    def test_comparison_words_need_word_boundaries(self):
        text = GOOD.replace("hit ratio < 80%", "we revisit it in Q3 2027 overall")
        self.assertTrue(any("Redis cache" in p for p in self.run_check(text)))

    def test_trigger_needs_a_unit_not_just_a_digit(self):
        text = GOOD.replace("hit ratio < 80%", "the team grows beyond 2")
        self.assertTrue(any("Redis cache" in p for p in self.run_check(text)))

    def test_counted_triggers_from_real_designs_pass(self):
        # triggers written by the skill in earlier evals: units are nouns or currency
        for trig in ("more than 5 enterprise tenants ask for Ed25519 signatures",
                     "more than 2 teams (> 12 engineers) changing checkout weekly",
                     "monthly LLM spend > $80k for 2 months",
                     "sync defects exceed 3 per quarter",
                     "region incidents > 2 per year"):
            with self.subTest(trig=trig):
                self.assertEqual(self.run_check(GOOD.replace("hit ratio < 80%", trig)), [])

    # --- agy's review of change.md: false positives the patch introduced ----------------
    def test_good_design_passes_with_calc(self):
        # GOOD's "buy rate drops below 50/s" is a scale-down, per-SKU trigger: not a strawman
        calc_out = {"traffic": {"peak_read_qps": 3000, "peak_write_qps": 1200}}
        self.assertEqual(check_design.check(GOOD, "design", calc=calc_out)[0], [])

    def test_per_entity_rate_is_not_compared_with_system_peak(self):
        rows = [(["Endpoint pool", "", "", "one tenant > 300 req/s for 10 min"], 3)]
        self.assertEqual(check_design.strawman_triggers(rows, {"traffic": {"peak_read_qps": 5000}}), [])

    def test_weekly_and_monthly_rates_are_units(self):
        for trig in ("price complaints > 5/week", "more than 3 incidents/month"):
            with self.subTest(trig=trig):
                self.assertEqual(self.run_check(GOOD.replace("hit ratio < 80%", trig)), [])

    def test_staleness_check_skips_tables_and_review_log(self):
        text = GOOD.replace("Reviewer: 2 findings accepted.",
                            "Reviewer: 2 findings accepted; rejected DynamoDB for its eventual consistency.")
        text = text.replace("| Redis cache | read load | staleness |",
                            "| Redis cache | read load | eventual consistency on prices |")
        self.assertEqual(self.run_check(text), [])

    def test_rpo_rto_in_a_table_or_zero(self):
        text = GOOD.replace("DR: warm standby, RPO 5 min, RTO 30 min (assumed).",
                            "| Tier | RPO | RTO |\n|---|---|---|\n| ledger | 0 (sync replica) | 15 min |")
        self.assertEqual(self.run_check(text), [])
        text = GOOD.replace("RPO 5 min", "RPO: zero (synchronous replica)")
        self.assertEqual(self.run_check(text), [])

    # --- agy's review of the changes ------------------------------------------------------
    def test_rpo_rto_before_the_term_and_word_boundaries(self):
        ok = GOOD.replace("DR: warm standby, RPO 5 min, RTO 30 min (assumed).",
                          "We target a 5-minute RPO and a 30-minute RTO (assumed).")
        self.assertEqual(self.run_check(ok), [])
        bad = GOOD.replace("DR: warm standby, RPO 5 min, RTO 30 min (assumed).",
                           "For this purpose, 2 replicas. RTO is decided later.")
        probs = " ".join(self.run_check(bad))
        self.assertIn("numeric RPO", probs)
        self.assertIn("numeric RTO", probs)

    def test_strawman_checked_per_clause(self):
        rows = [(["Postgres", "", "", "peak writes > 900k/s, or replica lag > 2 s"], 3)]
        found = check_design.strawman_triggers(rows, {"traffic": {"peak_write_qps": 1200}})
        self.assertTrue(found and "strawman" in found[0])

    def test_mixed_read_write_cell_compares_each_clause(self):
        rows = [(["Postgres", "", "", "peak writes > 8k/s or peak reads > 60k/s"], 3)]
        calc_out = {"traffic": {"peak_read_qps": 50000, "peak_write_qps": 1200}}
        self.assertEqual(check_design.strawman_triggers(rows, calc_out), [])

    def test_events_per_second_is_a_rate_trigger(self):
        rows = [(["Kafka", "", "", "traffic > 50,000 events/s"], 3)]
        found = check_design.strawman_triggers(rows, {"traffic": {"peak_write_qps": 100}})
        self.assertTrue(found and "strawman" in found[0])

    def test_outgrows_is_a_comparison_and_vague_counts_are_not(self):
        self.assertEqual(self.run_check(GOOD.replace("hit ratio < 80%", "the index outgrows 128 GiB")), [])
        self.assertTrue(any("Redis cache" in p for p in
                            self.run_check(GOOD.replace("hit ratio < 80%", "the team grows beyond 2 soon"))))

    def test_adr_trigger_needs_a_counted_number(self):
        bad = ADR.replace("Change it when: peak writes exceed 8k/s.",
                          "Change it when: we revisit in 2027 more than once.")
        self.assertTrue(any("trigger" in p for p in self.run_check(bad, "adr")))

    def test_dates_are_not_trigger_numbers(self):
        text = GOOD.replace("hit ratio < 80%", "still slow after 2027")
        self.assertTrue(any("Redis cache" in p for p in self.run_check(text)))

    def test_rate_units_like_per_second_still_pass(self):
        self.assertEqual(self.run_check(GOOD), [])  # "drops below 50/s" must stay valid

    def test_eventual_consistency_needs_a_window(self):
        bad = GOOD.replace("A shop.", "Stock counts are eventually consistent.")
        self.assertTrue(any("staleness window" in p for p in self.run_check(bad)))
        ok = GOOD.replace("A shop.", "Stock counts are eventually consistent (p99 replica lag 2 s).")
        self.assertEqual(self.run_check(ok), [])

    def test_failure_section_needs_numeric_rpo_rto(self):
        text = GOOD.replace("DR: warm standby, RPO 5 min, RTO 30 min (assumed).\n", "")
        probs = self.run_check(text)
        self.assertTrue(any("RPO" in p for p in probs) and any("RTO" in p for p in probs))

    def test_strawman_and_already_fired_triggers_with_calc(self):
        rows = [(["Postgres primary", "", "", "peak writes > 8k/s"], 3)]
        self.assertEqual(check_design.strawman_triggers(rows, {"traffic": {"peak_write_qps": 1200}}), [])
        far = check_design.strawman_triggers(rows, {"traffic": {"peak_write_qps": 50}})
        self.assertTrue(far and "strawman" in far[0])
        fired = check_design.strawman_triggers(rows, {"traffic": {"peak_write_qps": 20000}})
        self.assertTrue(fired and "already below" in fired[0])

    def test_write_trigger_compared_with_writes_not_reads(self):
        rows = [(["Postgres primary", "", "", "peak writes > 8k/s"], 3)]
        calc_out = {"traffic": {"peak_read_qps": 50000, "peak_write_qps": 1200}}
        self.assertEqual(check_design.strawman_triggers(rows, calc_out), [])

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

    def test_estimation_must_label_inputs_and_cite_calculator(self):
        text = GOOD.replace("From capacity_calc.py (DAU given, peak 3x assumed): ", "")
        probs = " ".join(self.run_check(text))
        self.assertIn("given or assumed", probs)
        self.assertIn("calculator run", probs)
        ok = GOOD.replace("From capacity_calc.py", "From docs/design/shop.calc.json")
        self.assertEqual(self.run_check(ok), [])

    def test_empty_solves_or_worsens_fails(self):
        text = GOOD.replace("| Redis cache | read load | staleness |", "| Redis cache | read load | - |")
        self.assertTrue(any("'worsens' is empty" in p for p in self.run_check(text)))

    def test_review_log_needs_dispositions(self):
        text = GOOD.replace("Reviewer: 2 findings accepted.", "Reviewed.")
        self.assertTrue(any("dispositions" in p for p in self.run_check(text)))
        self.assertEqual(check_design.check(text, "design", draft=True)[0], [])

    def test_subheadings_stay_in_parent_section(self):
        text = GOOD.replace("## Estimation\nFrom capacity_calc.py (DAU given, peak 3x assumed): "
                            "peak writes 1,200/s; 3-year storage 4 TiB.\n",
                            "## Estimation\n### Traffic\ncapacity_calc.py, peak assumed: 1,200/s.\n"
                            "### Storage\n4 TiB.\n")
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
