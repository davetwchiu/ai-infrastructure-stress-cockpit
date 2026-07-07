#!/usr/bin/env python3
"""Build data/latest.json and data/history.csv from public CSV sources."""

from __future__ import annotations

import argparse
import csv
import json
import math
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
SERIES = {
    "sofr": "SOFR",
    "dgs2": "DGS2",
    "dgs10": "DGS10",
    "ig_oas": "BAMLC0A0CM",
    "hy_oas": "BAMLH0A0HYM2",
    "nasdaq100": "NASDAQ100",
}


def fetch_series(series_id: str) -> dict[str, float]:
    with urllib.request.urlopen(FRED.format(series_id), timeout=30) as res:
        rows = csv.DictReader(line.decode() for line in res.readlines())
        out = {}
        for row in rows:
            raw = row.get(series_id, ".")
            if raw and raw != ".":
                out[row["observation_date"]] = float(raw)
        return out


def change(values: list[float], days: int) -> float:
    if len(values) <= days or not math.isfinite(values[-days - 1]):
        return 0.0
    return values[-1] - values[-days - 1]


def pct_change(values: list[float], days: int) -> float:
    if len(values) <= days or not values[-days - 1]:
        return 0.0
    return (values[-1] / values[-days - 1] - 1) * 100


def clamp(value: float) -> int:
    return round(max(0, min(100, value)))


def status(score: int) -> str:
    if score >= 75:
        return "Stress"
    if score >= 55:
        return "Elevated"
    if score >= 40:
        return "Watch"
    return "Normal"


def build_rows(series: dict[str, dict[str, float]]) -> list[dict[str, float | str]]:
    dates = sorted(set.intersection(*(set(v) for v in series.values())))[-80:]
    rows = []
    for i, date in enumerate(dates):
        window = {key: [series[key][d] for d in dates[: i + 1]] for key in series}
        sofr, dgs2, dgs10 = window["sofr"][-1], window["dgs2"][-1], window["dgs10"][-1]
        ig, hy, ndx = window["ig_oas"][-1], window["hy_oas"][-1], window["nasdaq100"][-1]
        rates = clamp((sofr - 3.25) * 18 + max(change(window["dgs2"], 20), 0) * 80 + max(change(window["dgs10"], 20), 0) * 60 + 25)
        credit = clamp((hy - 3.2) * 13 + (ig - 1.1) * 25 + max(change(window["hy_oas"], 20), 0) * 25 + 24)
        equity = clamp(46 - pct_change(window["nasdaq100"], 20) * 2.3 - pct_change(window["nasdaq100"], 5))
        compute = 40
        stress = clamp(rates * .35 + credit * .35 + equity * .20 + compute * .10)
        rows.append({
            "date": date,
            "sofr": sofr,
            "dgs2": dgs2,
            "dgs10": dgs10,
            "ig_oas": ig,
            "hy_oas": hy,
            "nasdaq100": ndx,
            "rates_score": rates,
            "credit_score": credit,
            "equity_score": equity,
            "compute_score": compute,
            "stress_score": stress,
        })
    return rows


def fmt_rate(value: float) -> str:
    return f"{value:.2f}%"


def fmt_bps(value: float) -> str:
    return f"{round(value * 100)} bps"


def signed(value: float, digits: int = 2, suffix: str = "") -> str:
    return f"{value:+.{digits}f}{suffix}"


def build_latest(rows: list[dict[str, float | str]], manual: dict) -> dict:
    row = rows[-1]
    cols = {key: [float(r[key]) for r in rows] for key in SERIES}
    stress_score = int(row["stress_score"])
    rates_score = int(row["rates_score"])
    credit_score = int(row["credit_score"])
    equity_score = int(row["equity_score"])
    compute_score = int(row["compute_score"])
    credit_stable = change(cols["hy_oas"], 5) <= .08 and change(cols["ig_oas"], 5) <= .04
    ndx_20 = pct_change(cols["nasdaq100"], 20)
    judgment = (
        "Red flag confirmed: credit spreads and equity trend are both deteriorating."
        if credit_score >= 65 and equity_score >= 60
        else "Not a red flag yet. Rates remain high, but credit spreads have not confirmed deterioration."
    )
    latest = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "updated_label": f"{row['date']} close",
        "stress": {
            "score": stress_score,
            "status": status(stress_score),
            "regime": "Rates high, credit stable" if credit_stable else "Credit pressure rising",
            "confidence": "High for macro / Medium overall",
            "judgment": judgment,
        },
        "drivers": [
            {"key": "rates", "title": "Rates Pressure", "score": rates_score, "status": status(rates_score), "bullets": ["SOFR high", "2Y Treasury high"]},
            {"key": "credit", "title": "Credit Pressure", "score": credit_score, "status": status(credit_score), "bullets": ["HY OAS stable" if credit_stable else "HY OAS widening", "IG OAS stable" if change(cols["ig_oas"], 5) <= .04 else "IG OAS widening"]},
            {"key": "equity", "title": "Equity Confirmation", "score": equity_score, "status": status(equity_score), "bullets": ["Nasdaq 100 lagging" if ndx_20 < 0 else "Nasdaq 100 holding", "AI beta proxy ok" if ndx_20 > -5 else "AI beta proxy weak"]},
            {"key": "compute", "title": "AI Financing / Compute", "score": compute_score, "status": status(compute_score), "bullets": [f"GPU proxy {manual.get('gpu_proxy_status', 'unknown').replace('_', ' ')}", "No bad filing" if manual.get("financing_headline_status") == "no_bad_filing" else "Financing headline flagged"]},
        ],
        "triggers": {
            "positive": ["HY OAS unchanged over 5d" if credit_stable else "Credit data still observable", "Hyperscaler capex guidance still intact" if manual.get("capex_guidance_status") == "intact" else "Capex guidance flagged", "Nasdaq 100 not in stress break" if ndx_20 > -8 else "Equity weakness visible"],
            "warning": ["SOFR remains above stress threshold", "2Y Treasury rising over 20d" if change(cols["dgs2"], 20) > 0 else "2Y Treasury still elevated", "Nasdaq 100 trend negative over 20d" if ndx_20 < 0 else "Equity confirmation not negative"],
            "negative": ["No confirmed negative financing event" if manual.get("financing_headline_status") == "no_bad_filing" else "Negative financing event flagged", "No major capex cut" if manual.get("capex_guidance_status") == "intact" else "Capex cut flagged", "No major GPU rental collapse confirmed" if manual.get("gpu_proxy_status") != "collapse" else "GPU rental collapse flagged"],
        },
        "hard_data": [
            metric("sofr", "SOFR", row["sofr"], fmt_rate, cols["sofr"]),
            metric("dgs2", "2Y Treasury", row["dgs2"], fmt_rate, cols["dgs2"]),
            metric("dgs10", "10Y Treasury", row["dgs10"], fmt_rate, cols["dgs10"]),
            metric("ig_oas", "IG OAS", row["ig_oas"], fmt_bps, cols["ig_oas"]),
            metric("hy_oas", "HY OAS", row["hy_oas"], fmt_bps, cols["hy_oas"]),
            metric("nasdaq100", "Nasdaq 100", row["nasdaq100"], lambda v: f"{v:,.0f}", cols["nasdaq100"], percent=True),
        ],
        "action": {
            "status": status(stress_score).upper(),
            "meaning": "Rate pressure remains, but credit markets have not confirmed deterioration. This looks more like valuation/rate pressure than an AI credit event." if stress_score < 65 else "Stress is broad enough to reduce risk until credit and equity confirmation improve.",
            "portfolio_read_through": ["No need to panic on one or two down days in AI stocks", "Avoid aggressive leverage or chasing neocloud exposure", "Core NVDA / hyperscaler exposure can be maintained", "Upgrade to STRESS only if HY OAS widens + equities lag + GPU rental proxy weakens"],
        },
        "sources": ["FRED public CSV", "config/manual_signals.json"],
    }
    return latest


def metric(key: str, label: str, value: float, value_fmt, values: list[float], percent: bool = False) -> dict:
    c5 = pct_change(values, 5) if percent else change(values, 5)
    c20 = pct_change(values, 20) if percent else change(values, 20)
    suffix = "%" if percent else ""
    return {
        "key": key,
        "label": label,
        "value": value,
        "value_label": value_fmt(float(value)),
        "change_5d": round(c5, 4),
        "change_20d": round(c20, 4),
        "change_5d_label": signed(c5, 1 if percent else 2, suffix),
        "change_20d_label": signed(c20, 1 if percent else 2, suffix),
    }


def write_outputs(rows: list[dict[str, float | str]], latest: dict) -> None:
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    with (data_dir / "history.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (data_dir / "latest.json").write_text(json.dumps(latest, indent=2) + "\n")


def self_test() -> None:
    assert status(39) == "Normal"
    assert status(40) == "Watch"
    assert status(75) == "Stress"
    assert round(pct_change([100, 110], 1), 2) == 10


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    series = {key: fetch_series(series_id) for key, series_id in SERIES.items()}
    manual = json.loads((ROOT / "config/manual_signals.json").read_text())
    rows = build_rows(series)
    write_outputs(rows, build_latest(rows, manual))


if __name__ == "__main__":
    main()
