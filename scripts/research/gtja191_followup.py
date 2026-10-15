#!/usr/bin/env python3
"""Follow-up to the GTJA191 IC scan: (1) how many of the 24 Holm survivors are really independent, (2) do they survive turnover and costs.

Fixed before looking at results:
  factors   the Holm rejections of the pre-registered scan (report_compact.json), oriented by the sign of their main-window rank-IC
  universe  the 95 symbols of the confirmation universe (complete bars in both windows); factor inputs RAW bars (as in the scan),
            returns from the back-adjusted (qfq) series so ex-dividend drops are not counted as losses
  clusters  average-linkage on 1 - |mean daily cross-sectional rank correlation|, cut at |rho| >= 0.5; effective N = (sum eig)^2 / sum eig^2
  portfolio each rebalance day t (every 5 sessions) long the top fifth (19 names) of the oriented factor, equal weight, entered at the
            open of t+1, held 5 sessions, exit at the open of t+6; benchmark = equal weight of the same universe over the same dates.
            Names that cannot be bought are skipped: no volume on the entry day, or opening at the +10% limit.
  costs     reported at 0 / 10 / 20 / 30 bp per unit of one-way turnover (commission+stamp+slippage are roughly 15-20 bp round trip)
  windows   main 2023-01-03..2025-12-31 (where the factors were selected) and confirmation 2026-01-05..2026-09-30 (the honest one)
Not modelled: capacity, ST 5% limits, limit-down exits, financing, any real execution engine. This is a screening step, not a backtest.

    python scripts/research/gtja191_followup.py --data-root /Volumes/Lexar/niuniu-data --scan artifacts/_gtja191_ic_2026-10-15 \
        --universe artifacts/_gtja191_confirm_2026-10-15/universe.json --output artifacts/_gtja191_followup_2026-10-15
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from quantlab.factors.gtja import gtja_pack  # noqa: E402

WARMUP = "2022-12-01"  # after the last suspended (null-volume) bar of these symbols (2022-11-25); the scan itself had no warm-up either
WINDOWS = {"main": ("2023-01-03", "2025-12-31"), "confirm": ("2026-01-05", "2026-09-30")}
HOLD, QUANTILE, COSTS_BP = 5, 0.2, (0, 10, 20, 30)
RHO_CUT = 0.5
TZ = ZoneInfo("Asia/Shanghai")


def load(root: Path, symbols: list[str], end: str):
    raw_dir = root / "lake/bronze/provider=baostock/stock_kline_daily"
    qfq_dir = root / "lake/silver/qfq_kline_daily"
    raws, adjs = [], []
    for symbol in symbols:
        name = symbol.replace(".", "_") + ".parquet"
        lo, hi = datetime.fromisoformat(WARMUP).date(), datetime.fromisoformat(end).date()
        r = pl.read_parquet(raw_dir / name).filter(pl.col("date").is_between(lo, hi))
        q = pl.read_parquet(qfq_dir / name).filter(pl.col("date").is_between(lo, hi)).select("date", pl.col("open").alias("qopen"), pl.col("close").alias("qclose"))
        raws.append(r.select("date", pl.lit(symbol).alias("symbol"), "open", "high", "low", "close", "volume", "amount"))
        adjs.append(q.with_columns(pl.lit(symbol).alias("symbol")))
    raw, adj = pl.concat(raws), pl.concat(adjs)
    return raw, adj


def panel(frame: pl.DataFrame, column: str, dates, symbols):
    wide = frame.pivot(on="symbol", index="date", values=column).sort("date")
    wide = wide.join(pl.DataFrame({"date": dates}), on="date", how="right").sort("date")
    return wide.select(["date"] + symbols).drop("date").to_numpy().astype(float)


def rank_rows(x):
    """Cross-sectional ranks per row, NaN preserved, average ties not needed (continuous)."""
    out = np.full(x.shape, np.nan)
    for i, row in enumerate(x):
        ok = np.isfinite(row)
        if ok.sum() > 2:
            order = row[ok].argsort().argsort().astype(float)
            out[i, ok] = (order - order.mean()) / (order.std() or 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--scan", required=True, type=Path)
    ap.add_argument("--universe", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--ledger", type=Path, help="optional trial-ledger folder: record each (factor, window) top-fifth excess series as a trial (does not change any result)")
    args = ap.parse_args()
    symbols = json.loads(args.universe.read_text())["symbols"]
    report = json.loads((args.scan / "report_compact/report_compact.json").read_text())
    chosen = sorted({t["factor"] for t in report["tests"] if t["reject_holm"]})
    raw, adj = load(args.data_root, symbols, WINDOWS["confirm"][1])
    dates = sorted(raw["date"].unique().to_list())
    wide = {c: panel(raw, c, dates, symbols) for c in ("open", "high", "low", "close", "volume")}
    qopen = panel(adj, "qopen", dates, symbols)

    # factor values
    bars = raw.with_columns(
        pl.col("symbol"), pl.col("date").map_elements(lambda d: datetime.combine(d, time(15), tzinfo=TZ), return_dtype=pl.Datetime("us", "Asia/Shanghai")).alias("datetime"),
        pl.col("amount").alias("turnover"), pl.lit(1.0).alias("adj_factor")).with_columns(pl.col("datetime").alias("available_at"), pl.lit("1d").alias("timeframe"),
        pl.col("volume").cast(pl.Float64))
    lookup = {f.definition.factor_id: f for f in gtja_pack().factors}
    values = {}
    for fid in chosen:
        out = lookup[fid].compute(bars, {}).with_columns(pl.col("datetime").dt.date().alias("date"))
        values[fid] = panel(out.select("date", "symbol", "value"), "value", dates, symbols)
    di = {d: i for i, d in enumerate(dates)}
    idx = {w: [i for i, d in enumerate(dates) if lo <= str(d) <= hi] for w, (lo, hi) in WINDOWS.items()}

    # forward return: open(t+1) -> open(t+1+HOLD), back-adjusted
    fwd = np.full(qopen.shape, np.nan)
    fwd[: -(1 + HOLD)] = qopen[1 + HOLD:] / qopen[1:-HOLD] - 1
    entry_ok = np.full(qopen.shape, False)
    prev_close = np.vstack([np.full((1, len(symbols)), np.nan), wide["close"][:-1]])
    nxt_open, nxt_vol, nxt_prev = (np.vstack([a[1:], np.full((1, len(symbols)), np.nan)]) for a in (wide["open"], wide["volume"], wide["close"]))
    entry_ok = (nxt_vol > 0) & (nxt_open < np.round(wide["close"] * 1.1, 2) - 1e-9)

    ranks = {f: rank_rows(v) for f, v in values.items()}
    # orientation + rank-IC per window
    result = {"factors": {}, "design": __doc__}
    sign = {}
    for f in chosen:
        ics = {}
        for w, ii in idx.items():
            xs = []
            for i in ii:
                a, b = ranks[f][i], rank_rows(fwd[i:i + 1])[0]
                ok = np.isfinite(a) & np.isfinite(b)
                if ok.sum() > 10:
                    xs.append(np.corrcoef(a[ok], b[ok])[0, 1])
            ics[w] = float(np.mean(xs))
        sign[f] = 1.0 if ics["main"] >= 0 else -1.0
        result["factors"][f] = {"sign": sign[f], "mean_rank_ic": ics}

    # clustering on mean daily cross-sectional rank correlation (oriented, main window)
    n = len(chosen)
    corr = np.eye(n)
    for a in range(n):
        for b in range(a + 1, n):
            xs = []
            for i in idx["main"]:
                x, y = ranks[chosen[a]][i], ranks[chosen[b]][i]
                ok = np.isfinite(x) & np.isfinite(y)
                if ok.sum() > 10:
                    xs.append(np.corrcoef(x[ok], y[ok])[0, 1])
            corr[a, b] = corr[b, a] = np.mean(xs) * sign[chosen[a]] * sign[chosen[b]]
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    dist = 1 - np.abs(corr)
    np.fill_diagonal(dist, 0)
    labels = fcluster(linkage(squareform(dist, checks=False), "average"), 1 - RHO_CUT, "distance")
    eig = np.clip(np.linalg.eigvalsh(np.abs(corr)), 0, None)
    result["clustering"] = {"n_factors": n, "n_clusters_at_abs_rho_0.5": int(labels.max()), "effective_n_participation_ratio": float(eig.sum() ** 2 / (eig ** 2).sum()),
                            "mean_abs_pairwise_corr": float(np.abs(corr[np.triu_indices(n, 1)]).mean()),
                            "clusters": {int(c): [chosen[i] for i in range(n) if labels[i] == c] for c in sorted(set(labels))},
                            "corr_matrix_oriented": {"order": chosen, "values": np.round(corr, 3).tolist()}}
    for i, f in enumerate(chosen):
        result["factors"][f]["cluster"] = int(labels[i])

    # long top-fifth portfolio with turnover and costs
    for f in chosen:
        for w, ii in idx.items():
            rebal = ii[::HOLD]
            rets, bench, turn, prev, low, stamps = [], [], [], None, [], []
            for i in rebal:
                if i + 1 + HOLD >= len(dates):
                    break
                score = ranks[f][i] * sign[f]
                ok = np.isfinite(score) & np.isfinite(fwd[i]) & entry_ok[i]
                if ok.sum() < 20:
                    continue
                k = max(1, int(round(QUANTILE * ok.sum())))
                names = np.where(ok)[0][np.argsort(-score[ok])[:k]]
                weight = np.zeros(len(symbols)); weight[names] = 1 / k
                turn.append(float(np.abs(weight - prev).sum() / 2) if prev is not None else 1.0)
                prev = weight
                rets.append(float(fwd[i][names].mean()))
                stamps.append(str(dates[i]))
                low.append(float(fwd[i][np.where(ok)[0][np.argsort(score[ok])[:k]]].mean()))
                bench.append(float(np.nanmean(fwd[i][np.isfinite(fwd[i])])))
            rets, bench, turn, low = map(np.array, (rets, bench, turn, low))
            excess = rets - bench
            if args.ledger:
                from quantlab.statistics import trial_ledger
                trial_ledger.record_trial(args.ledger, f"gtja191-followup-{w}", {"factor": f, "sign": sign[f], "portfolio": "top fifth, equal weight, 5-session hold"}, excess, dates=stamps,
                                          note="per-rebalance gross excess vs equal-weight universe (not daily); one of the 24 Holm survivors of the pre-registered scan")
            periods = 252 / HOLD
            row = {"n_rebalances": int(len(rets)), "gross_return_per_period": float(rets.mean()), "benchmark_per_period": float(bench.mean()),
                   "excess_per_period": float(excess.mean()), "excess_annualised": float(excess.mean() * periods),
                   "excess_t": float(excess.mean() / (excess.std(ddof=1) / np.sqrt(len(excess)))) if len(excess) > 2 and excess.std() > 0 else None,
                   "bottom_fifth_excess_annualised": float((low - bench).mean() * (252 / HOLD)), "top_minus_bottom_annualised": float((rets - low).mean() * (252 / HOLD)), "one_way_turnover_per_rebalance": float(turn[1:].mean()) if len(turn) > 1 else None, "net_excess_annualised_by_cost_bp": {}}
            for bp in COSTS_BP:
                net = excess - turn * 2 * bp / 1e4  # buy and sell sides: turnover is the sold fraction (= bought fraction)
                row["net_excess_annualised_by_cost_bp"][str(bp)] = float(net.mean() * periods)
            result["factors"][f].setdefault("portfolio", {})[w] = row

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "followup.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    c = result["clustering"]
    lines = ["# GTJA191 跟进：聚类与换手/成本", "",
             f"24 个 Holm 显著因子 → |ρ|≥0.5 聚成 {c['n_clusters_at_abs_rho_0.5']} 簇；有效独立个数（特征值参与比）≈ {c['effective_n_participation_ratio']:.1f}；平均两两 |ρ| = {c['mean_abs_pairwise_corr']:.2f}。", "",
             "| 因子 | 簇 | 方向 | 主窗 rank-IC | 确认窗 rank-IC | 主窗超额年化(多头) | 主窗最低五分位超额 | 主窗换手/次 | 确认窗超额年化(0bp) | 确认窗净超额(20bp) | 确认窗 t |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for f in sorted(chosen, key=lambda k: result["factors"][k]["cluster"]):
        r = result["factors"][f]
        pm, pc = r["portfolio"]["main"], r["portfolio"]["confirm"]
        lines.append(f"| {f.split('.')[1]} | {r['cluster']} | {r['sign']:+.0f} | {r['mean_rank_ic']['main']:.4f} | {r['mean_rank_ic']['confirm']:.4f} | {pm['excess_annualised']:.1%} | {pm['bottom_fifth_excess_annualised']:.1%} | "
                     f"{(pm['one_way_turnover_per_rebalance'] or 0):.0%} | {pc['excess_annualised']:.1%} | {pc['net_excess_annualised_by_cost_bp']['20']:.1%} | {pc['excess_t'] if pc['excess_t'] is None else round(pc['excess_t'], 2)} |")
    (args.output / "followup.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
