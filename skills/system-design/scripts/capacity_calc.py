#!/usr/bin/env python3
"""Back-of-the-envelope capacity calculator for system design (stdlib only).

Every section is optional; give the inputs for the sections you need and the
JSON on stdout holds only those. Numbers are estimates from stated
assumptions: the "assumptions" block echoes every input and default used, so
the design can quote them.

Sections
  traffic       --dau with --reads-per-user / --writes-per-user, or daily totals as
                --writes-per-day / --reads-per-day, or a burst given directly as
                --peak-read-qps / --peak-write-qps
  storage       traffic inputs plus --write-bytes, --replication, --years
  cache         traffic inputs plus --read-bytes and --hot-fraction
  concurrency   traffic inputs plus --service-ms and/or --db-ms
  availability  --serial and/or --parallel (comma-separated availabilities)
  vectors       --vectors with --dim (HNSW, int8 and PQ memory)
  restore       --restore-mbps (+ --data-tib or the storage inputs, --rto-min, --shards)
  llm           --llm-rps with token counts; prices, --decode-tps and model shape for
                cost, concurrency and KV cache (+ --gpu-mem-gib to check the fit)
  streams       --events-per-sec with --partition-mbps and/or --consumer-ms (+ --partitions)
  cost          --price-storage-gb-month / --price-egress-gb / --price-instance-hour
  --scale 10,100  re-runs everything at each load factor: what fires, and when

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
        "verified": "2026-11",
    },
    "single_node_read_qps": {
        "value": 20_000,
        "basis": "heuristic: 'a well-tuned database server handles tens of thousands of queries "
                 "per second' (hellointerview.com core concepts); plan replicas and a cache "
                 "before reads reach that range",
        "verified": "2026-11",
    },
    "redis_single_instance_ops": {
        "value": 100_000,
        "basis": "conservative: Redis's own benchmark shows ~180k SET/s on one instance without "
                 "pipelining (redis.io/docs .../optimization/benchmarks)",
        "verified": "2026-11",
    },
    "storage_tib_single_node": {
        "value": 10,
        "basis": "heuristic, not a hard limit: past ~10 TiB on one node, backup, restore and "
                 "replica rebuild times start to threaten RTO; compute restore time explicitly",
        "verified": "2026-11",
    },
    "db_connections_per_node": {
        "value": 100,
        "basis": "PostgreSQL's default max_connections is typically 100 "
                 "(postgresql.org/docs runtime-config-connection); beyond it put a pooler "
                 "(e.g. PgBouncer) in front, sized from cores (often cores x 2 + 1), not clients",
        "verified": "2026-11",
    },
    "hnsw_ram_gib_single_node": {
        "value": 128,
        "basis": "sizing choice: an in-memory HNSW index past one large host's RAM needs "
                 "quantization, sharding, or a disk-based ANN index",
        "verified": "2026-11",
    },
    # Thresholds below come from the design's own inputs (its RTO, its GPUs, its partitions),
    # so "value" is set per run.
    "restore_exceeds_rto": {
        "value": None,
        "basis": "the RTO given with --rto-min: a restore that takes longer cannot meet it",
        "verified": "2026-11",
    },
    "kv_cache_exceeds_gpu": {
        "value": None,
        "basis": "the GPU memory given (--gpus x (--gpu-mem-gib - --weights-gib)); KV cache past it "
                 "means smaller batches or context, more GPUs, or a sharded model",
        "verified": "2026-11",
    },
    "consumer_lag_risk": {
        "value": None,
        "basis": "Little's law with the --consumer-ms given: one consumer per partition handles "
                 "1000 / consumer_ms events/s",
        "verified": "2026-11",
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

    def trigger(key, observed, message, threshold=None):
        t = THRESHOLDS[key]
        out["triggers"].append({
            "rule": key, "observed": r(observed, 1),
            "threshold": r(threshold, 2) if threshold is not None else t["value"],
            "message": message, "basis": t["basis"], "verified": t["verified"],
        })

    per_day = args.writes_per_day is not None or args.reads_per_day is not None
    if args.dau is not None and per_day:
        raise SystemExit("capacity_calc: give either --dau (with per-user rates) or "
                         "--writes-per-day/--reads-per-day, not both")
    daily = args.dau is not None or per_day
    burst = args.peak_read_qps is not None or args.peak_write_qps is not None
    if daily and burst:
        raise SystemExit("capacity_calc: give either daily traffic (--dau or --writes-per-day/"
                         "--reads-per-day) or --peak-read-qps/--peak-write-qps (a burst), not both; "
                         "run twice to compare")
    have_traffic = daily or burst
    reads_day_bytes = 0.0
    if have_traffic:
        reads = writes = None
        if daily and per_day:
            reads = positive("reads-per-day", args.reads_per_day or 0.0)
            writes = positive("writes-per-day", args.writes_per_day or 0.0)
            a.update({"reads_per_day": reads, "writes_per_day": writes, "peak_multiplier": args.peak})
        elif daily:
            positive("dau", args.dau)
            a.update({
                "dau": args.dau, "reads_per_user_per_day": args.reads_per_user,
                "writes_per_user_per_day": args.writes_per_user, "peak_multiplier": args.peak,
            })
            reads = args.dau * args.reads_per_user
            writes = args.dau * args.writes_per_user
        if daily:
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
                "note": "burst given as peak rates; storage and cache need daily volumes "
                        "(--dau or --writes-per-day/--reads-per-day)",
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
            day_bytes = logical_day
            for _ in range(int(math.ceil(args.years))):
                total_logical += day_bytes * 365
                day_bytes *= 1 + args.yearly_growth
            if args.years != int(args.years):  # trim the last partial year proportionally
                frac = args.years - int(args.years)
                total_logical -= (day_bytes / (1 + args.yearly_growth)) * 365 * (1 - frac)
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
                reads_day_bytes = reads * args.read_bytes
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

    # restore time vs RTO: one copy of the data, restored in parallel across shards
    if args.restore_mbps is not None:
        positive("restore-mbps", args.restore_mbps)
        if args.data_tib is not None:
            data_tib = positive("data-tib", args.data_tib)
        elif "storage" in out:
            data_tib = out["storage"]["logical_total_tib"]
        else:
            raise SystemExit("capacity_calc: --restore-mbps needs --data-tib or the storage inputs "
                             "(--dau with --write-bytes)")
        if args.shards < 1:
            raise SystemExit("capacity_calc: --shards must be >= 1")
        a.update({"restore_mbps": args.restore_mbps, "shards": args.shards})
        hours = data_tib * TIB / (args.restore_mbps * 1e6) / 3600 / args.shards
        out["restore"] = {"data_tib": r(data_tib, 3), "restore_hours": r(hours, 2),
                          "note": "one full copy restored at the given MB/s per shard, shards in "
                                  "parallel; add log replay and verification time"}
        if args.rto_min is not None:
            a["rto_min"] = args.rto_min
            out["restore"]["rto_hours"] = r(args.rto_min / 60, 2)
            if hours * 60 > args.rto_min:
                trigger("restore_exceeds_rto", hours * 60,
                        "a full restore takes longer than the RTO: smaller shards, a warm replica "
                        "or standby, faster restore media, or tier cold data out", args.rto_min)

    # LLM serving: tokens, cost, concurrency and KV cache
    if args.llm_rps is not None:
        positive("llm-rps", args.llm_rps)
        pt, ot = args.prompt_tokens, args.output_tokens
        a.update({"llm_rps_avg": args.llm_rps, "prompt_tokens": pt, "output_tokens": ot,
                  "peak_multiplier": args.peak})
        peak_rps = args.llm_rps * args.peak
        llm = {"input_tokens_per_sec_avg": r(args.llm_rps * pt), "output_tokens_per_sec_avg": r(args.llm_rps * ot)}
        if args.price_in is not None or args.price_out is not None:
            per_req = (pt * (args.price_in or 0) + ot * (args.price_out or 0)) / 1e6
            a.update({"price_in_per_mtok": args.price_in, "price_out_per_mtok": args.price_out})
            llm.update({"cost_per_request_usd": round(per_req, 6),
                        "cost_per_day_usd": r(per_req * args.llm_rps * SECONDS_PER_DAY),
                        "cost_per_month_usd": r(per_req * args.llm_rps * SECONDS_PER_DAY * 30)})
        if args.decode_tps is not None:
            gen_s = ot / positive("decode-tps", args.decode_tps)
            a["decode_tps"] = args.decode_tps
            llm.update({"generation_seconds": r(gen_s, 3),
                        "concurrent_streams_at_peak": r(peak_rps * gen_s, 1)})
            if args.layers is not None:
                per_tok = int(2 * args.layers * args.kv_heads * args.head_dim * args.kv_bytes)
                per_seq = per_tok * args.context
                total = per_seq * peak_rps * gen_s
                a.update({"layers": args.layers, "kv_heads": args.kv_heads, "head_dim": args.head_dim,
                          "kv_bytes": args.kv_bytes, "context": args.context})
                llm.update({"kv_bytes_per_token": per_tok, "kv_gib_per_sequence": r(per_seq / GIB, 3),
                            "kv_gib_at_peak": r(total / GIB, 1),
                            "kv_formula": "2 x layers x kv_heads x head_dim x bytes, x context per "
                                          "sequence, x concurrent streams (Little's law)"})
                if args.gpu_mem_gib is not None:
                    room = args.gpus * (args.gpu_mem_gib - (args.weights_gib or 0))
                    a.update({"gpus": args.gpus, "gpu_mem_gib": args.gpu_mem_gib, "weights_gib": args.weights_gib})
                    llm["kv_room_gib"] = r(room, 1)
                    if total / GIB > room:
                        trigger("kv_cache_exceeds_gpu", total / GIB,
                                "KV cache at peak does not fit the GPUs: cap batch or context, "
                                "add GPUs or replicas, quantize the KV cache, or shard the model", room)
        out["llm"] = llm

    # streams: partitions for throughput vs for consumer parallelism
    if args.events_per_sec is not None:
        eps = positive("events-per-sec", args.events_per_sec)
        a.update({"events_per_sec": eps, "event_bytes": args.event_bytes})
        st = {"ingress_mb_per_sec": r(eps * args.event_bytes / 1e6, 2)}
        need = []
        if args.partition_mbps is not None:
            st["partitions_for_throughput"] = max(1, math.ceil(eps * args.event_bytes / 1e6 / args.partition_mbps))
            need.append(("throughput", st["partitions_for_throughput"]))
            a["partition_mbps"] = args.partition_mbps
        if args.consumer_ms is not None:
            st["partitions_for_consumers"] = max(1, math.ceil(eps * args.consumer_ms / 1000))
            need.append(("consumers", st["partitions_for_consumers"]))
            a["consumer_ms"] = args.consumer_ms
        if need:
            bound, n = max(need, key=lambda x: x[1])
            st.update({"bound_by": bound, "partitions_recommended": math.ceil(n * 1.5),
                       "note": "recommended = the larger need x 1.5 headroom; partition count is "
                               "hard to raise later without reshuffling keys"})
        if args.partitions is not None and args.consumer_ms is not None:
            per_part = eps / args.partitions
            capacity = 1000 / args.consumer_ms
            st.update({"events_per_partition": r(per_part, 1), "consumer_capacity_per_partition": r(capacity, 1)})
            if per_part > capacity:
                trigger("consumer_lag_risk", per_part,
                        "one consumer per partition cannot keep up at peak: add partitions, speed "
                        "up processing, or batch", capacity)
        out["streams"] = st

    # cost at today's numbers; with --scale, at each factor
    priced = [args.price_storage_gb_month, args.price_egress_gb, args.price_instance_hour,
              args.price_in, args.price_out]
    if any(v is not None for v in priced):
        lines = {}
        if args.price_storage_gb_month is not None and "storage" in out:
            lines["storage"] = out["storage"]["replicated_total_tib"] * TIB / 1e9 * args.price_storage_gb_month
        if args.price_egress_gb is not None and reads_day_bytes:
            lines["egress"] = reads_day_bytes * 30 / 1e9 * args.price_egress_gb
        if args.price_instance_hour is not None:
            lines["compute"] = args.instances * args.price_instance_hour * 730
        if "llm" in out and "cost_per_month_usd" in out["llm"]:
            lines["llm"] = out["llm"]["cost_per_month_usd"]
        if lines:
            cost = {f"{k}_month_usd": r(v) for k, v in lines.items()}
            cost["total_month_usd"] = r(sum(lines.values()))
            cost["largest_line"] = max(lines, key=lines.get)
            cost["note"] = ("storage priced at the end of the retention horizon, replicated; "
                            "egress = daily read volume x 30; compute = instances x 730 h; "
                            "GB = 1e9 bytes; prices are your inputs, never defaults")
            out["cost"] = cost

    if len(out) == 2 and not out["assumptions"]:
        raise SystemExit("capacity_calc: nothing to compute; give --dau, --peak-read-qps/--peak-write-qps, "
                         "--serial/--parallel, --vectors, --llm-rps, --events-per-sec or --restore-mbps "
                         "(see --help)")
    return out


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], allow_abbrev=False,
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("\n\n", 1)[1])
    t = p.add_argument_group("traffic")
    t.add_argument("--dau", type=float, help="daily active users")
    t.add_argument("--reads-per-user", type=float, default=10.0, help="reads per user per day (default 10)")
    t.add_argument("--writes-per-user", type=float, default=1.0, help="writes per user per day (default 1)")
    t.add_argument("--writes-per-day", type=float, help="writes/day in total, when the brief gives volumes, not users (instead of --dau)")
    t.add_argument("--reads-per-day", type=float, help="reads/day in total (instead of --dau)")
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
    d = p.add_argument_group("restore vs RTO")
    d.add_argument("--restore-mbps", type=float, help="restore throughput per shard, MB/s (measured or vendor figure); needs --data-tib or the storage inputs")
    d.add_argument("--data-tib", type=float, help="data to restore, TiB (default: the storage estimate)")
    d.add_argument("--rto-min", type=float, help="recovery time objective, minutes")
    d.add_argument("--shards", type=int, default=1, help="shards restored in parallel (default 1)")
    g = p.add_argument_group("LLM serving")
    g.add_argument("--llm-rps", type=float, help="average LLM requests/s (peak = x --peak)")
    g.add_argument("--prompt-tokens", type=float, default=1000.0, help="input tokens per request (default 1000)")
    g.add_argument("--output-tokens", type=float, default=300.0, help="output tokens per request (default 300)")
    g.add_argument("--price-in", type=float, help="USD per 1M input tokens (your provider's price)")
    g.add_argument("--price-out", type=float, help="USD per 1M output tokens (your provider's price)")
    g.add_argument("--decode-tps", type=float, help="output tokens/s per stream")
    g.add_argument("--layers", type=int, help="model layers (for KV cache)")
    g.add_argument("--kv-heads", type=int, default=8, help="KV heads (default 8)")
    g.add_argument("--head-dim", type=int, default=128, help="head dimension (default 128)")
    g.add_argument("--kv-bytes", type=float, default=2.0, help="bytes per KV value, 2 = fp16 (default 2)")
    g.add_argument("--context", type=int, default=8192, help="context tokens per sequence (default 8192)")
    g.add_argument("--gpu-mem-gib", type=float, help="memory per GPU, GiB")
    g.add_argument("--weights-gib", type=float, help="model weights per GPU, GiB")
    g.add_argument("--gpus", type=int, default=1, help="GPUs serving the model (default 1)")
    q = p.add_argument_group("streams")
    q.add_argument("--events-per-sec", type=float, help="peak events/s into the stream")
    q.add_argument("--event-bytes", type=float, default=1000.0, help="bytes per event (default 1000)")
    q.add_argument("--partition-mbps", type=float, help="throughput one partition sustains, MB/s (your broker's figure)")
    q.add_argument("--consumer-ms", type=float, help="processing time per event in one consumer, ms")
    q.add_argument("--partitions", type=int, help="partition count planned (checks consumer lag)")
    m = p.add_argument_group("cost (all prices are your inputs)")
    m.add_argument("--price-storage-gb-month", type=float, help="USD per GB-month of storage")
    m.add_argument("--price-egress-gb", type=float, help="USD per GB of egress")
    m.add_argument("--price-instance-hour", type=float, help="USD per instance-hour")
    m.add_argument("--instances", type=float, default=1.0, help="instances running (default 1)")
    return p


SCALABLE = {  # inputs a sensitivity band may scale, and the bounds that keep them valid
    "dau": (0, None), "reads_per_user": (0, None), "writes_per_user": (0, None),
    "peak": (1, None), "write_bytes": (0, None), "read_bytes": (0, None),
    "yearly_growth": (0, None), "hot_fraction": (0, 1), "service_ms": (0, None),
    "db_ms": (0, None), "db_read_fraction": (0, 1), "vectors": (0, None), "dim": (1, None),
    "peak_read_qps": (0, None), "peak_write_qps": (0, None),
    "writes_per_day": (0, None), "reads_per_day": (0, None), "llm_rps": (0, None), "prompt_tokens": (0, None), "output_tokens": (0, None),
    "events_per_sec": (0, None), "event_bytes": (0, None), "consumer_ms": (0, None),
    "data_tib": (0, None), "restore_mbps": (0, None), "decode_tps": (0, None),
    "partition_mbps": (0, None), "price_in": (0, None), "price_out": (0, None),
    "price_storage_gb_month": (0, None), "price_egress_gb": (0, None),
    "price_instance_hour": (0, None), "instances": (0, None),
}

HEADLINES = [
    ("traffic", "peak_read_qps"), ("traffic", "peak_write_qps"),
    ("storage", "replicated_total_tib"), ("cache", "hot_set_upper_bound_gib"),
    ("bandwidth", "peak_egress_mbps"), ("concurrency", "busy_db_connections_at_peak"),
    ("vectors", "hnsw_fp32_gib"), ("restore", "restore_hours"), ("llm", "kv_gib_at_peak"),
    ("llm", "cost_per_month_usd"), ("streams", "partitions_recommended"), ("cost", "total_month_usd"),
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


def scale_path(args, factors):
    """Re-run with the load inputs multiplied by each factor (10x, 100x): what fires, and when."""
    out = {}
    for f in factors:
        scaled = argparse.Namespace(**vars(args))
        # load inputs scale with the factor; so does the instance count (assumes compute grows
        # linearly with load - say so if the design scales differently)
        for name in ("dau", "writes_per_day", "reads_per_day", "peak_read_qps", "peak_write_qps",
                     "vectors", "llm_rps", "events_per_sec", "instances"):
            if getattr(scaled, name) is not None:
                setattr(scaled, name, getattr(scaled, name) * f)
        res = calc(scaled)
        out[f"{f:g}x"] = {
            "headlines": {f"{sec}.{key}": res[sec][key] for sec, key in HEADLINES
                          if sec in res and key in res[sec]},
            "triggers": [t["rule"] for t in res["triggers"]],
        }
    return out


def main(argv=None):
    parser = build_parser()
    parser.add_argument("--assumed", default="",
                        help="comma-separated inputs that are guesses rather than given "
                             "(e.g. dau,peak,write-bytes); adds a sensitivity band")
    parser.add_argument("--scale", default="",
                        help="comma-separated load multipliers for the evolution path, e.g. 10,100; "
                             "re-runs with dau/peak/vectors scaled and lists what fires at each")
    parser.add_argument("--out", help="also write the JSON to this file (e.g. docs/design/<slug>.calc.json) "
                                      "for the gate's --calc check; avoids a shell redirect")
    parser.add_argument("--band", default="0.5,2",
                        help="low,high factors for the sensitivity band (default 0.5,2)")
    args = parser.parse_args(argv)
    for name in ("hot_fraction", "db_read_fraction"):
        v = getattr(args, name)
        if not 0 <= v <= 1:
            raise SystemExit(f"capacity_calc: --{name.replace('_', '-')} must be between 0 and 1")
    if args.peak < 1:
        raise SystemExit("capacity_calc: --peak must be >= 1")
    if args.replication < 1:
        raise SystemExit("capacity_calc: --replication must be >= 1")
    if args.years <= 0:
        raise SystemExit("capacity_calc: --years must be > 0")
    if args.yearly_growth <= -1:
        raise SystemExit("capacity_calc: --yearly-growth must be > -1 (-0.5 = halving each year)")
    if args.index_overhead < 0:
        raise SystemExit("capacity_calc: --index-overhead must not be negative")
    # inputs used as divisors or counts must be positive when given
    for name in ("restore_mbps", "decode_tps", "partition_mbps", "consumer_ms", "data_tib",
                 "gpu_mem_gib", "event_bytes", "context", "layers"):
        v = getattr(args, name)
        if v is not None and v <= 0:
            raise SystemExit(f"capacity_calc: --{name.replace('_', '-')} must be > 0")
    for name in ("partitions", "shards", "gpus"):
        v = getattr(args, name)
        if v is not None and v < 1:
            raise SystemExit(f"capacity_calc: --{name} must be >= 1")
    if args.instances is not None and args.instances < 0:
        raise SystemExit("capacity_calc: --instances must not be negative")
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
    if args.scale:
        try:
            factors = [float(x) for x in args.scale.split(",") if x.strip()]
        except ValueError:
            raise SystemExit("capacity_calc: --scale takes numbers, e.g. 10,100")
        if any(f <= 0 for f in factors):
            raise SystemExit("capacity_calc: --scale factors must be > 0")
        out["scale_path"] = scale_path(args, factors)
    if assumed:
        out["sensitivity"] = sensitivity(args, assumed, low, high)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(out, fh, indent=2)
                fh.write("\n")
        except OSError as e:
            raise SystemExit(f"capacity_calc: cannot write --out {args.out}: {e}")
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
