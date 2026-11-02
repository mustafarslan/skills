#!/usr/bin/env python3
"""Back-of-the-envelope capacity calculator for system design (stdlib only).

Every section is optional; give the inputs for the sections you need and the
JSON on stdout holds only those. Numbers are estimates from stated
assumptions: the "assumptions" block echoes every input and default used, so
the design can quote them.

Sections
  traffic       --dau with --reads-per-user / --writes-per-user, or a burst given
                directly as --peak-read-qps / --peak-write-qps
  storage       traffic inputs plus --write-bytes, --replication, --years
  cache         traffic inputs plus --read-bytes and --hot-fraction
  concurrency   traffic inputs plus --service-ms and/or --db-ms
  availability  --serial and/or --parallel (comma-separated availabilities)
  vectors       --vectors with --dim (HNSW, int8 and PQ memory)

Triggers are rules of thumb, not limits: each carries the basis it came from,
and the design must still check the real engine, hardware and workload.

Examples
  capacity_calc.py --dau 1e8 --reads-per-user 20 --writes-per-user 2 --write-bytes 1024
  capacity_calc.py --serial 0.9995,0.999 --parallel 0.99,0.99
  capacity_calc.py --vectors 5e7 --dim 1024 --hnsw-m 16
"""
import argparse
import json
import math
import sys

SECONDS_PER_DAY = 86_400
GIB = 1024 ** 3
TIB = 1024 ** 4
MINUTES_PER_YEAR = 365.25 * 24 * 60
MINUTES_PER_MONTH = MINUTES_PER_YEAR / 12

# Rules of thumb that turn numbers into design pressure. Each is a prompt to
# look closer, never a hard limit; "basis" says where the figure comes from.
THRESHOLDS = {
    "single_primary_write_qps": {
        "value": 10_000,
        "basis": "heuristic from interview-prep sources: ~10k writes/s on one primary does not "
                 "yet need sharding; tens of thousands does (hellointerview.com core concepts). "
                 "fsync/synchronous_commit settings move this 3-4x, so measure",
    },
    "single_node_read_qps": {
        "value": 20_000,
        "basis": "heuristic: 'a well-tuned database server handles tens of thousands of queries "
                 "per second' (hellointerview.com core concepts); plan replicas and a cache "
                 "before reads reach that range",
    },
    "redis_single_instance_ops": {
        "value": 100_000,
        "basis": "conservative: Redis's own benchmark shows ~180k SET/s on one instance without "
                 "pipelining (redis.io/docs .../optimization/benchmarks)",
    },
    "storage_tib_single_node": {
        "value": 10,
        "basis": "heuristic, not a hard limit: past ~10 TiB on one node, backup, restore and "
                 "replica rebuild times start to threaten RTO; compute restore time explicitly",
    },
    "db_connections_per_node": {
        "value": 100,
        "basis": "PostgreSQL's default max_connections is typically 100 "
                 "(postgresql.org/docs runtime-config-connection); beyond it put a pooler "
                 "(e.g. PgBouncer) in front, sized from cores (often cores x 2 + 1), not clients",
    },
    "hnsw_ram_gib_single_node": {
        "value": 128,
        "basis": "sizing choice: an in-memory HNSW index past one large host's RAM needs "
                 "quantization, sharding, or a disk-based ANN index",
    },
}


def positive(name, value):
    if value is not None and value < 0:
        raise SystemExit(f"capacity_calc: --{name} must not be negative (got {value})")
    return value


def parse_avail_list(text, flag):
    if not text:
        return []
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = float(part.rstrip("%"))
        except ValueError:
            raise SystemExit(f"capacity_calc: {flag}: '{part}' is not a number")
        if part.endswith("%") or value > 1:
            value /= 100.0
        if not 0 < value <= 1:
            raise SystemExit(f"capacity_calc: {flag}: availability must be in (0, 1] or (0, 100]%")
        out.append(value)
    return out


def nines(a):
    if a >= 1:
        return float("inf")
    return round(-math.log10(1 - a), 2)


def downtime(a):
    return {
        "per_year_minutes": round((1 - a) * MINUTES_PER_YEAR, 1),
        "per_month_minutes": round((1 - a) * MINUTES_PER_MONTH, 1),
    }


def r(x, n=2):
    return round(x, n)


def calc(args):
    out = {"assumptions": {}, "triggers": []}
    a = out["assumptions"]

    def trigger(key, observed, message):
        t = THRESHOLDS[key]
        out["triggers"].append({
            "rule": key, "observed": r(observed, 1), "threshold": t["value"],
            "message": message, "basis": t["basis"],
        })

    daily = args.dau is not None
    burst = args.peak_read_qps is not None or args.peak_write_qps is not None
    if daily and burst:
        raise SystemExit("capacity_calc: give either --dau (daily traffic) or --peak-read-qps/"
                         "--peak-write-qps (a burst), not both; run twice to compare")
    have_traffic = daily or burst
    if have_traffic:
        reads = writes = None
        if daily:
            positive("dau", args.dau)
            a.update({
                "dau": args.dau, "reads_per_user_per_day": args.reads_per_user,
                "writes_per_user_per_day": args.writes_per_user, "peak_multiplier": args.peak,
            })
            reads = args.dau * args.reads_per_user
            writes = args.dau * args.writes_per_user
            avg_r, avg_w = reads / SECONDS_PER_DAY, writes / SECONDS_PER_DAY
            peak_r, peak_w = avg_r * args.peak, avg_w * args.peak
            out["traffic"] = {
                "reads_per_day": r(reads, 0), "writes_per_day": r(writes, 0),
                "avg_read_qps": r(avg_r), "avg_write_qps": r(avg_w),
                "peak_read_qps": r(peak_r), "peak_write_qps": r(peak_w),
                "read_write_ratio": r(reads / writes, 1) if writes else None,
            }
        else:
            peak_r = positive("peak-read-qps", args.peak_read_qps or 0.0)
            peak_w = positive("peak-write-qps", args.peak_write_qps or 0.0)
            a.update({"peak_read_qps": peak_r, "peak_write_qps": peak_w})
            out["traffic"] = {
                "peak_read_qps": r(peak_r), "peak_write_qps": r(peak_w),
                "note": "burst given as peak rates; storage and cache need --dau (daily volume)",
            }
        db_reads = peak_r * args.db_read_fraction
        out["traffic"]["peak_db_read_qps"] = r(db_reads)
        if peak_w > THRESHOLDS["single_primary_write_qps"]["value"]:
            trigger("single_primary_write_qps", peak_w,
                    "peak writes exceed one primary's comfortable range: consider partitioning "
                    "the write path, batching/queueing writes, or an LSM-based store")
        if db_reads > THRESHOLDS["single_node_read_qps"]["value"]:
            trigger("single_node_read_qps", db_reads,
                    "peak reads reaching the database exceed one node's comfortable range: read "
                    "replicas, a cache tier (then pass --db-read-fraction), and/or a CDN")
        if peak_r > THRESHOLDS["redis_single_instance_ops"]["value"]:
            trigger("redis_single_instance_ops", peak_r,
                    "peak reads exceed what one cache instance serves: shard the cache, "
                    "pipeline, or add a local (in-process) tier for the hottest keys")

        if args.write_bytes is not None and daily:
            positive("write-bytes", args.write_bytes)
            a.update({"write_bytes": args.write_bytes, "replication_factor": args.replication,
                      "years": args.years, "yearly_growth": args.yearly_growth,
                      "index_overhead": args.index_overhead})
            logical_day = writes * args.write_bytes * (1 + args.index_overhead)
            # total over N years with compound growth of the daily write volume
            total_logical = 0.0
            daily = logical_day
            for _ in range(int(math.ceil(args.years))):
                total_logical += daily * 365
                daily *= 1 + args.yearly_growth
            if args.years != int(args.years):  # trim the last partial year proportionally
                frac = args.years - int(args.years)
                total_logical -= (daily / (1 + args.yearly_growth)) * 365 * (1 - frac)
            out["storage"] = {
                "logical_per_day_gib": r(logical_day / GIB, 3),
                "logical_total_tib": r(total_logical / TIB, 3),
                "replicated_total_tib": r(total_logical * args.replication / TIB, 3),
                "peak_ingress_mbps": r(peak_w * args.write_bytes * 8 / 1e6),
            }
            if total_logical / TIB > THRESHOLDS["storage_tib_single_node"]["value"]:
                trigger("storage_tib_single_node", total_logical / TIB,
                        "logical data outgrows one node: choose a partition key, a retention "
                        "or tiering policy, and check backup/restore time against RTO")

        if args.read_bytes is not None:
            positive("read-bytes", args.read_bytes)
            a["read_bytes"] = args.read_bytes
            out.setdefault("bandwidth", {})["peak_egress_mbps"] = r(peak_r * args.read_bytes * 8 / 1e6)
            if daily:
                a["hot_fraction"] = args.hot_fraction
                out["cache"] = {
                    "daily_read_volume_gib": r(reads * args.read_bytes / GIB, 3),
                    "hot_set_upper_bound_gib": r(reads * args.read_bytes * args.hot_fraction / GIB, 3),
                    "note": "upper bound: assumes every read is a distinct object; "
                            "real hot sets are smaller when reads repeat",
                }

        if args.service_ms is not None or args.db_ms is not None:
            conc = {}
            if args.service_ms is not None:
                a["service_ms"] = args.service_ms
                conc["in_flight_requests_at_peak"] = r((peak_r + peak_w) * args.service_ms / 1000, 0)
            if args.db_ms is not None:
                a["db_ms"] = args.db_ms
                busy = (db_reads + peak_w) * args.db_ms / 1000
                a["db_read_fraction"] = args.db_read_fraction
                conc["busy_db_connections_at_peak"] = r(busy, 0)
                if busy > THRESHOLDS["db_connections_per_node"]["value"]:
                    trigger("db_connections_per_node", busy,
                            "busy DB connections at peak exceed what one node handles well: "
                            "pool, cache reads, shorten queries, or partition")
            conc["method"] = "Little's law: concurrency = arrival rate x time in system"
            out["concurrency"] = conc

    serial = parse_avail_list(args.serial, "--serial")
    parallel = parse_avail_list(args.parallel, "--parallel")
    if serial or parallel:
        av = {}
        total = 1.0
        if serial:
            s = math.prod(serial)
            av["serial_chain"] = {"inputs": serial, "availability": round(s, 6), "nines": nines(s)}
            total *= s
        if parallel:
            p = 1 - math.prod(1 - x for x in parallel)
            av["parallel_group"] = {
                "inputs": parallel, "availability": round(p, 8), "nines": nines(p),
                "note": "assumes independent failures; shared dependencies (region, DNS, "
                        "deploys, config) make the real figure lower",
            }
            total *= p
        av["combined"] = {"availability": round(total, 6), "nines": nines(total), "downtime": downtime(total)}
        out["availability"] = av

    if args.vectors is not None:
        positive("vectors", args.vectors)
        n, d, m = args.vectors, args.dim, args.hnsw_m
        a.update({"vectors": n, "dim": d, "hnsw_m": m, "pq_bytes": args.pq_bytes})
        raw = n * d * 4
        graph = m * 16  # bytes of neighbour links per vector
        headroom = 1.2
        hnsw_fp32 = n * (d * 4 + graph) * headroom
        hnsw_int8 = n * (d * 1 + graph) * headroom
        pq = n * (args.pq_bytes + 8)  # PQ code + 8-byte id
        out["vectors"] = {
            "raw_fp32_gib": r(raw / GIB),
            "hnsw_fp32_gib": r(hnsw_fp32 / GIB),
            "hnsw_int8_gib": r(hnsw_int8 / GIB),
            "ivf_pq_gib": r(pq / GIB),
            "formula": "HNSW ~ N x (d x bytes_per_dim + M x 16) x 1.2 headroom "
                       "(ScyllaDB vector-search sizing); IVF-PQ ~ N x (code_bytes + 8) "
                       "(FAISS wiki); pgvector stores 4 x d + 8 bytes per vector before the index",
        }
        if hnsw_fp32 / GIB > THRESHOLDS["hnsw_ram_gib_single_node"]["value"]:
            trigger("hnsw_ram_gib_single_node", hnsw_fp32 / GIB,
                    "an fp32 HNSW index outgrows one host: quantize (int8/PQ), shard the "
                    "index, or use a disk-based ANN index")

    if len(out) == 2 and not out["assumptions"]:
        raise SystemExit("capacity_calc: nothing to compute; give --dau, --peak-read-qps/--peak-write-qps, "
                         "--serial/--parallel or --vectors "
                         "(see --help)")
    return out


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("\n\n", 1)[1])
    t = p.add_argument_group("traffic")
    t.add_argument("--dau", type=float, help="daily active users")
    t.add_argument("--reads-per-user", type=float, default=10.0, help="reads per user per day (default 10)")
    t.add_argument("--writes-per-user", type=float, default=1.0, help="writes per user per day (default 1)")
    t.add_argument("--peak", type=float, default=3.0, help="peak-to-average multiplier (default 3)")
    t.add_argument("--peak-read-qps", type=float, help="a burst given directly as peak reads/s (instead of --dau)")
    t.add_argument("--peak-write-qps", type=float, help="a burst given directly as peak writes/s (instead of --dau)")
    s = p.add_argument_group("storage")
    s.add_argument("--write-bytes", type=float, help="bytes stored per write")
    s.add_argument("--replication", type=int, default=3, help="replication factor (default 3)")
    s.add_argument("--years", type=float, default=3.0, help="retention horizon in years (default 3)")
    s.add_argument("--yearly-growth", type=float, default=0.0, help="yearly growth of write volume, 0.5 = +50%% (default 0)")
    s.add_argument("--index-overhead", type=float, default=0.0, help="extra bytes for indexes as a fraction, 0.3 = +30%% (default 0)")
    c = p.add_argument_group("cache and bandwidth")
    c.add_argument("--read-bytes", type=float, help="bytes returned per read")
    c.add_argument("--hot-fraction", type=float, default=0.2, help="share of daily read volume to cache (default 0.2)")
    k = p.add_argument_group("concurrency")
    k.add_argument("--service-ms", type=float, help="mean time a request spends in the service")
    k.add_argument("--db-ms", type=float, help="mean DB time per query")
    k.add_argument("--db-read-fraction", type=float, default=1.0, help="share of reads that reach the DB, e.g. 0.1 behind a 90%% cache (default 1)")
    v = p.add_argument_group("availability")
    v.add_argument("--serial", help="availabilities of components in series, e.g. 0.999,99.95%%")
    v.add_argument("--parallel", help="availabilities of redundant replicas, e.g. 0.99,0.99")
    x = p.add_argument_group("vector index")
    x.add_argument("--vectors", type=float, help="number of vectors")
    x.add_argument("--dim", type=int, default=1536, help="dimensions (default 1536)")
    x.add_argument("--hnsw-m", type=int, default=16, help="HNSW M (default 16)")
    x.add_argument("--pq-bytes", type=int, default=64, help="PQ code bytes per vector (default 64)")
    return p


SCALABLE = {  # inputs a sensitivity band may scale, and the bounds that keep them valid
    "dau": (0, None), "reads_per_user": (0, None), "writes_per_user": (0, None),
    "peak": (1, None), "write_bytes": (0, None), "read_bytes": (0, None),
    "yearly_growth": (0, None), "hot_fraction": (0, 1), "service_ms": (0, None),
    "db_ms": (0, None), "db_read_fraction": (0, 1), "vectors": (0, None), "dim": (1, None),
    "peak_read_qps": (0, None), "peak_write_qps": (0, None),
}

HEADLINES = [
    ("traffic", "peak_read_qps"), ("traffic", "peak_write_qps"),
    ("storage", "replicated_total_tib"), ("cache", "hot_set_upper_bound_gib"),
    ("bandwidth", "peak_egress_mbps"), ("concurrency", "busy_db_connections_at_peak"),
    ("vectors", "hnsw_fp32_gib"),
]


def sensitivity(args, assumed, low, high):
    """Re-run with every guessed input scaled by `low` and by `high` together."""
    def run(factor):
        scaled = argparse.Namespace(**vars(args))
        for name in assumed:
            value = getattr(scaled, name)
            if value is None:
                continue
            lo, hi = SCALABLE[name]
            value = value * factor
            if name == "peak":  # scale the excess over average, never below 1
                value = 1 + (getattr(args, name) - 1) * factor
            value = max(lo, value)
            if hi is not None:
                value = min(hi, value)
            setattr(scaled, name, int(round(value)) if name == "dim" else value)
        return calc(scaled)

    lo_out, hi_out = run(low), run(high)
    band = {}
    for section, key in HEADLINES:
        if section in lo_out and key in lo_out[section]:
            band[f"{section}.{key}"] = [lo_out[section][key], hi_out[section][key]]
    lo_rules = {t["rule"] for t in lo_out["triggers"]}
    hi_rules = {t["rule"] for t in hi_out["triggers"]}
    return {
        "guessed_inputs": sorted(n.replace("_", "-") for n in assumed),
        "factors": [low, high],
        "ranges": band,
        "triggers_only_at_high": sorted(hi_rules - lo_rules),
        "note": "all guessed inputs move together (the worst case), so a product of k guesses "
                "spans factor^k; a trigger that appears only at the high end means a design "
                "decision depends on a guess - confirm that input first",
    }


def main(argv=None):
    parser = build_parser()
    parser.add_argument("--assumed", default="",
                        help="comma-separated inputs that are guesses rather than given "
                             "(e.g. dau,peak,write-bytes); adds a sensitivity band")
    parser.add_argument("--band", default="0.5,2",
                        help="low,high factors for the sensitivity band (default 0.5,2)")
    args = parser.parse_args(argv)
    for name in ("hot_fraction", "db_read_fraction"):
        v = getattr(args, name)
        if not 0 <= v <= 1:
            raise SystemExit(f"capacity_calc: --{name.replace('_', '-')} must be between 0 and 1")
    if args.peak < 1:
        raise SystemExit("capacity_calc: --peak must be >= 1")
    assumed = [x.strip().replace("-", "_") for x in args.assumed.split(",") if x.strip()]
    unknown = [x for x in assumed if x not in SCALABLE]
    if unknown:
        raise SystemExit(f"capacity_calc: --assumed: cannot vary {', '.join(unknown)}; "
                         f"choose from {', '.join(sorted(k.replace('_', '-') for k in SCALABLE))}")
    try:
        low, high = (float(x) for x in args.band.split(","))
    except ValueError:
        raise SystemExit("capacity_calc: --band takes two numbers, e.g. 0.5,2")
    if not 0 < low <= 1 <= high:
        raise SystemExit("capacity_calc: --band needs 0 < low <= 1 <= high")
    out = calc(args)
    if assumed:
        out["sensitivity"] = sensitivity(args, assumed, low, high)
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
