#!/usr/bin/env python3
"""Pre-registered test: does dropping the worst fifth by the GTJA191 survivors beat holding everything? (written 2026-10-15, BEFORE it was run)

Question   The follow-up screen found the IC of the 24 Holm survivors lives mostly in the worst fifth. Used as an exclusion filter
           on an equal-weight book of the universe, does it add return after costs, beyond what removing a random fifth would?
Rule       one representative per cluster = the factor with the largest |main-window rank-IC| in its cluster (clusters, signs and IC
           from artifacts/_gtja191_followup_2026-10-15/followup.json; the rule does not look at the confirmation window or at portfolios);
           composite score of a stock on a rebalance day = mean of the oriented cross-sectional rank scores of the representatives that
           are available (needs >= 10 of 14); PRIMARY filter A: drop the lowest 20% of composite among eligible names, hold the rest equal weight.
           Secondary B (reported, not for decision): each representative alone, same drop rule.
Execution  same as gtja191_followup.py: rebalance every 5 sessions, enter at next open, exit at the open of t+6, back-adjusted returns,
           skip names with no volume or opening at the +10% limit; benchmark = equal weight of all eligible names. Costs 0/10/20/30 bp per
           unit of one-way turnover, charged to BOTH the filtered book and the benchmark (net excess = net filtered - net benchmark).
Null       2000 random drops of the same size per rebalance (fixed seed); p = share of random filters whose gross mean excess >= observed.
Decision   The filter is called WORKING only if, in the CONFIRMATION window, all hold: net excess at 20 bp > 0, null p <= 0.10, and the
           main-window gross excess is also > 0. Otherwise it is called NOT SUPPORTED. The main window is where the factors were selected,
           so it cannot support the claim by itself. Nothing is tuned after seeing results; if a change is wanted, start a new output.

    python scripts/research/gtja191_filter.py --data-root /Volumes/Lexar/niuniu-data --followup artifacts/_gtja191_followup_2026-10-15/followup.json \
        --universe artifacts/_gtja191_confirm_2026-10-15/universe.json --output /tmp/gtja191_filter
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, time
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import gtja191_followup as base  # noqa: E402
from quantlab.factors.gtja import gtja_pack  # noqa: E402

DROP, DRAWS, MIN_REPS, SEED = 0.2, 2000, 10, 20261015


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--followup", required=True, type=Path)
    ap.add_argument("--universe", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--ledger", type=Path, help="optional trial-ledger folder: record the composite filter and each single-factor filter as trials (does not change any result)")
    args = ap.parse_args()
    follow = json.loads(args.followup.read_text())
    clusters: dict[int, list[str]] = {}
    for f, v in follow["factors"].items():
        clusters.setdefault(v["cluster"], []).append(f)
    reps = {c: max(fs, key=lambda f: abs(follow["factors"][f]["mean_rank_ic"]["main"])) for c, fs in sorted(clusters.items())}
    sign = {f: follow["factors"][f]["sign"] for f in reps.values()}
    symbols = json.loads(args.universe.read_text())["symbols"]

    raw, adj = base.load(args.data_root, symbols, base.WINDOWS["confirm"][1])
    dates = sorted(raw["date"].unique().to_list())
    wide = {c: base.panel(raw, c, dates, symbols) for c in ("open", "close", "volume")}
    qopen = base.panel(adj, "qopen", dates, symbols)
    bars = raw.with_columns(
        pl.col("date").map_elements(lambda d: datetime.combine(d, time(15), tzinfo=base.TZ), return_dtype=pl.Datetime("us", "Asia/Shanghai")).alias("datetime"),
        pl.col("amount").alias("turnover"), pl.lit(1.0).alias("adj_factor")).with_columns(
        pl.col("datetime").alias("available_at"), pl.lit("1d").alias("timeframe"), pl.col("volume").cast(pl.Float64))
    lookup = {f.definition.factor_id: f for f in gtja_pack().factors}
    scores = {}
    for f in reps.values():
        out = lookup[f].compute(bars, {}).with_columns(pl.col("datetime").dt.date().alias("date"))
        scores[f] = base.rank_rows(base.panel(out.select("date", "symbol", "value"), "value", dates, symbols)) * sign[f]

    hold = base.HOLD
    fwd = np.full(qopen.shape, np.nan)
    fwd[:-(1 + hold)] = qopen[1 + hold:] / qopen[1:-hold] - 1
    nxt_open = np.vstack([wide["open"][1:], np.full((1, len(symbols)), np.nan)])
    nxt_vol = np.vstack([wide["volume"][1:], np.full((1, len(symbols)), np.nan)])
    entry_ok = (nxt_vol > 0) & (nxt_open < np.round(wide["close"] * 1.1, 2) - 1e-9)
    composite = np.nanmean(np.stack([scores[f] for f in reps.values()]), axis=0)
    count = np.sum(np.stack([np.isfinite(scores[f]) for f in reps.values()]), axis=0)
    composite[count < MIN_REPS] = np.nan
    rng = np.random.default_rng(SEED)
    result = {"design": __doc__, "representatives": {int(c): f for c, f in reps.items()}, "signs": sign, "windows": {}}

    def run(score_matrix, window_idx):
        rebal = window_idx[::hold]
        rows = []
        for i in rebal:
            if i + 1 + hold >= len(dates):
                break
            ok = np.isfinite(score_matrix[i]) & np.isfinite(fwd[i]) & entry_ok[i]
            if ok.sum() < 20:
                continue
            names_all = np.where(ok)[0]
            k_drop = max(1, int(round(DROP * len(names_all))))
            order = names_all[np.argsort(score_matrix[i][names_all])]  # ascending: worst first
            kept = order[k_drop:]
            rows.append((names_all, kept, k_drop, i))
        return rows

    def summarise(rows, family=None, config=None):
        n = len(symbols)
        prev_f = prev_b = None
        fr, br, tf, tb = [], [], [], []
        for names_all, kept, _, i in rows:
            wf, wb = np.zeros(n), np.zeros(n)
            wf[kept] = 1 / len(kept)
            wb[names_all] = 1 / len(names_all)
            tf.append(np.abs(wf - prev_f).sum() / 2 if prev_f is not None else 1.0)
            tb.append(np.abs(wb - prev_b).sum() / 2 if prev_b is not None else 1.0)
            prev_f, prev_b = wf, wb
            fr.append(float(fwd[i][kept].mean()))
            br.append(float(fwd[i][names_all].mean()))
        fr, br, tf, tb = map(np.array, (fr, br, tf, tb))
        gross = fr - br
        if args.ledger and family:
            from quantlab.statistics import trial_ledger
            trial_ledger.record_trial(args.ledger, family, config, gross, dates=[str(dates[r[3]]) for r in rows[:len(gross)]],
                                      note="per-rebalance gross excess of the filtered book over the equal-weight universe (not daily)")
        periods = 252 / hold
        out = {"n_rebalances": int(len(fr)), "benchmark_annualised": float(br.mean() * periods),
               "gross_excess_annualised": float(gross.mean() * periods),
               "gross_excess_t": float(gross.mean() / (gross.std(ddof=1) / np.sqrt(len(gross)))) if len(gross) > 2 and gross.std() > 0 else None,
               "share_of_periods_positive": float((gross > 0).mean()),
               "one_way_turnover_filtered": float(tf[1:].mean()), "one_way_turnover_benchmark": float(tb[1:].mean()), "net_excess_annualised_by_cost_bp": {}}
        for bp in base.COSTS_BP:
            net = (fr - tf * 2 * bp / 1e4) - (br - tb * 2 * bp / 1e4)
            out["net_excess_annualised_by_cost_bp"][str(bp)] = float(net.mean() * periods)
        # random-drop null on the same eligible sets and drop sizes
        null = np.zeros(DRAWS)
        for names_all, kept, k_drop, i in rows:
            values = fwd[i][names_all]
            m = len(names_all)
            picks = np.argsort(rng.random((DRAWS, m)), axis=1)[:, k_drop:]
            null += (values[picks].mean(axis=1) - values.mean())
        null = null / len(rows) * periods
        out["null_p_gross"] = float((np.sum(null >= out["gross_excess_annualised"]) + 1) / (DRAWS + 1))
        out["null_mean_std"] = [float(null.mean()), float(null.std())]
        return out

    for window, (lo, hi) in base.WINDOWS.items():
        idx = [i for i, d in enumerate(dates) if lo <= str(d) <= hi]
        res = {"A_composite": summarise(run(composite, idx), f"gtja191-filter-{window}", {"variant": "A_composite"}), "B_single": {}}
        for f in reps.values():
            res["B_single"][f] = summarise(run(scores[f], idx), f"gtja191-filter-{window}", {"variant": "B_single", "factor": f})
        result["windows"][window] = res

    c, m = result["windows"]["confirm"]["A_composite"], result["windows"]["main"]["A_composite"]
    verdict = (c["net_excess_annualised_by_cost_bp"]["20"] > 0 and c["null_p_gross"] <= 0.10 and m["gross_excess_annualised"] > 0)
    result["verdict"] = "WORKING" if verdict else "NOT SUPPORTED"
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "filter.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    lines = [f"# GTJA191 过滤器检验（剔除综合分最差 1/5）— 判定：{result['verdict']}", "",
             "代表因子：" + "、".join(f.split("_")[1] for f in reps.values()), "",
             "| 窗口 | 基准年化 | 毛超额 | 毛超额 t | 正超额期占比 | 随机剔除 p | 过滤组合换手 | 基准换手 | 净超额 0bp | 10bp | 20bp | 30bp |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for w in ("main", "confirm"):
        a = result["windows"][w]["A_composite"]
        n = a["net_excess_annualised_by_cost_bp"]
        lines.append(f"| {w} | {a['benchmark_annualised']:.1%} | {a['gross_excess_annualised']:.1%} | {a['gross_excess_t']:.2f} | {a['share_of_periods_positive']:.0%} | {a['null_p_gross']:.3f} | "
                     f"{a['one_way_turnover_filtered']:.0%} | {a['one_way_turnover_benchmark']:.0%} | {n['0']:.1%} | {n['10']:.1%} | {n['20']:.1%} | {n['30']:.1%} |")
    lines += ["", "## 次要：各代表因子单独（不用于判定）", "", "| 因子 | 主窗毛超额 | 确认窗毛超额 | 确认窗随机 p |", "|---|---:|---:|---:|"]
    for f in reps.values():
        mb, cb = result["windows"]["main"]["B_single"][f], result["windows"]["confirm"]["B_single"][f]
        lines.append(f"| {f.split('_')[1]} | {mb['gross_excess_annualised']:.1%} | {cb['gross_excess_annualised']:.1%} | {cb['null_p_gross']:.3f} |")
    (args.output / "filter.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
