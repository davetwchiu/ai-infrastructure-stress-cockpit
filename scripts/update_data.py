#!/usr/bin/env python3
"""Build data/latest.json and data/history.csv from public sources."""

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
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=6mo&interval=1d&events=history"
YAHOO_QUOTE = "https://query1.finance.yahoo.com/v7/finance/quote?symbols={}"
YAHOO_PREPOST_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}?interval=1m&range=1d&includePrePost=true"
FRED_SERIES = {
    "sofr": "SOFR",
    "dgs2": "DGS2",
    "dgs10": "DGS10",
    "ig_oas": "BAMLC0A0CM",
    "hy_oas": "BAMLH0A0HYM2",
}
PRICE_SERIES = {
    "soxx": "SOXX",
    "qqq": "QQQ",
    "nvda": "NVDA",
}
QUOTE_FIELDS = (
    "regularMarketPrice",
    "regularMarketChangePercent",
    "preMarketPrice",
    "preMarketChangePercent",
    "postMarketPrice",
    "postMarketChangePercent",
    "marketState",
)


def iso_from_timestamp(ts: int | float | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), timezone.utc).isoformat(timespec="seconds")


def fetch_series(series_id: str) -> dict[str, float]:
    with urllib.request.urlopen(FRED.format(series_id), timeout=30) as res:
        rows = csv.DictReader(line.decode() for line in res.readlines())
        out = {}
        for row in rows:
            raw = row.get(series_id, ".")
            if raw and raw != ".":
                out[row["observation_date"]] = float(raw)
        return out


def fetch_price_series(symbol: str) -> dict[str, float]:
    req = urllib.request.Request(YAHOO_CHART.format(symbol), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        result = json.load(res)["chart"]["result"][0]
    out = {}
    closes = (
        result["indicators"].get("adjclose", result["indicators"]["quote"])[0].get("adjclose")
        or result["indicators"]["quote"][0]["close"]
    )
    for ts, close in zip(result["timestamp"], closes):
        if close:
            out[datetime.fromtimestamp(ts, timezone.utc).date().isoformat()] = float(close)
    return out


def fetch_extended_quotes(symbols: dict[str, str]) -> dict[str, dict]:
    try:
        req = urllib.request.Request(
            YAHOO_QUOTE.format(",".join(symbols.values())),
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as res:
            results = json.load(res)["quoteResponse"]["result"]
        quotes = {item["symbol"]: item for item in results}
        return {
            key: {field: quotes.get(symbol, {}).get(field) for field in QUOTE_FIELDS}
            | {
                "symbol": symbol,
                "regularMarketTime": quotes.get(symbol, {}).get("regularMarketTime"),
                "preMarketTime": quotes.get(symbol, {}).get("preMarketTime"),
                "postMarketTime": quotes.get(symbol, {}).get("postMarketTime"),
            }
            for key, symbol in symbols.items()
        }
    except Exception:
        return {key: fetch_prepost_quote(symbol) for key, symbol in symbols.items()}


def fetch_prepost_quote(symbol: str) -> dict:
    req = urllib.request.Request(YAHOO_PREPOST_CHART.format(symbol), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        result = json.load(res)["chart"]["result"][0]
    meta = result["meta"]
    state = chart_market_state(meta)
    quote = {
        "symbol": symbol,
        "regularMarketPrice": meta.get("regularMarketPrice"),
        "regularMarketChangePercent": percent_from(meta.get("regularMarketPrice"), meta.get("previousClose")),
        "marketState": state,
        "regularMarketTime": meta.get("regularMarketTime"),
    }
    if state == "PRE":
        price, ts = last_period_close(result, "pre")
        quote |= {
            "preMarketPrice": price,
            "preMarketChangePercent": percent_from(price, meta.get("previousClose")),
            "preMarketTime": ts,
        }
    if state == "POST":
        price, ts = last_period_close(result, "post")
        quote |= {
            "postMarketPrice": price,
            "postMarketChangePercent": percent_from(price, meta.get("regularMarketPrice")),
            "postMarketTime": ts,
        }
    return quote


def chart_market_state(meta: dict) -> str:
    now = int(datetime.now(timezone.utc).timestamp())
    periods = meta.get("currentTradingPeriod", {})
    for name, state in (("pre", "PRE"), ("regular", "REGULAR"), ("post", "POST")):
        period = periods.get(name, {})
        if period.get("start", 0) <= now < period.get("end", 0):
            return state
    return "CLOSED"


def last_period_close(result: dict, period_name: str) -> tuple[float | None, int | None]:
    period = result["meta"].get("currentTradingPeriod", {}).get(period_name, {})
    start, end = period.get("start", 0), period.get("end", 0)
    closes = result["indicators"]["quote"][0].get("close", [])
    points = [
        (float(close), int(ts))
        for ts, close in zip(result.get("timestamp", []), closes)
        if close and start <= ts < end
    ]
    return points[-1] if points else (None, None)


def percent_from(price: float | None, reference: float | None) -> float | None:
    if not price or not reference:
        return None
    return (float(price) / float(reference) - 1) * 100


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
    if score >= 71:
        return "CREDIT STRESS CONFIRMED"
    if score >= 51:
        return "STRESS"
    if score >= 26:
        return "WATCH"
    return "NORMAL"


def build_rows(series: dict[str, dict[str, float]]) -> list[dict[str, float | str]]:
    dates = sorted(set.intersection(*(set(v) for v in series.values())))[-80:]
    rows = []
    for i, date in enumerate(dates):
        window = {key: [series[key][d] for d in dates[: i + 1]] for key in series}
        sofr, dgs2, dgs10 = window["sofr"][-1], window["dgs2"][-1], window["dgs10"][-1]
        ig, hy = window["ig_oas"][-1], window["hy_oas"][-1]
        soxx, qqq, nvda = window["soxx"][-1], window["qqq"][-1], window["nvda"][-1]
        soxx_qqq_rel = [s / q * 100 for s, q in zip(window["soxx"], window["qqq"])]
        nvda_soxx_rel = [n / s * 100 for n, s in zip(window["nvda"], window["soxx"])]
        rates = clamp((sofr - 3.25) * 18 + max(change(window["dgs2"], 20), 0) * 80 + max(change(window["dgs10"], 20), 0) * 60 + 25)
        credit = clamp((hy - 3.2) * 13 + (ig - 1.1) * 25 + max(change(window["hy_oas"], 20), 0) * 25 + 24)
        equity = clamp(
            46
            - pct_change(soxx_qqq_rel, 20) * 1.8
            - pct_change(soxx_qqq_rel, 5) * .4
            - pct_change(nvda_soxx_rel, 20) * .8
            - pct_change(nvda_soxx_rel, 5) * .2
        )
        compute = 40
        stress = clamp(rates * .35 + credit * .35 + equity * .20 + compute * .10)
        rows.append({
            "date": date,
            "sofr": sofr,
            "dgs2": dgs2,
            "dgs10": dgs10,
            "ig_oas": ig,
            "hy_oas": hy,
            "soxx": soxx,
            "qqq": qqq,
            "nvda": nvda,
            "soxx_qqq_rel": soxx_qqq_rel[-1],
            "nvda_soxx_rel": nvda_soxx_rel[-1],
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


def active_extended_change(quote: dict, market_state: str) -> tuple[float | None, int | None]:
    if market_state == "PRE":
        return quote.get("preMarketChangePercent"), quote.get("preMarketTime")
    if market_state == "POST":
        return quote.get("postMarketChangePercent"), quote.get("postMarketTime")
    return None, None


def build_extended_hours(quotes: dict[str, dict] | None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    generated_at = now.isoformat(timespec="seconds")
    base = {
        "market_state": "UNKNOWN",
        "generated_at": generated_at,
        "as_of": None,
        "available": False,
        "is_stale": None,
        "is_active_session": False,
        "stale_reason": "Extended-hours quote fields unavailable",
        "quote_age_minutes": None,
        "source": "Yahoo Finance quote API",
        "label": "Pre-market / After-market equity overlay",
        "status": "NORMAL",
        "interpretation": "Extended-hours data unavailable",
    }
    if not quotes:
        return base

    market_state = str(quotes.get("soxx", {}).get("marketState") or "UNKNOWN")
    changes = {}
    times = []
    enriched = {}
    for key, quote in quotes.items():
        ext_change, ext_time = active_extended_change(quote, market_state)
        enriched[key] = {
            **quote,
            "extended_change_percent": ext_change,
            "quote_time": ext_time,
            "quote_time_label": iso_from_timestamp(ext_time),
        }
        changes[key] = ext_change
        if ext_time:
            times.append(int(ext_time))

    inactive_reason = {
        "REGULAR": "Regular session is active; extended-hours overlay is inactive",
        "CLOSED": "Market is closed; extended-hours overlay is inactive",
    }.get(market_state)
    if inactive_reason:
        return base | {
            "market_state": market_state,
            "stale_reason": inactive_reason,
            "interpretation": inactive_reason,
            **enriched,
        }

    if len(changes) != 3 or any(not isinstance(v, (int, float)) for v in changes.values()) or not times:
        return base | {"market_state": market_state, **enriched}

    as_of_ts = max(times)
    quote_age_minutes = max(0, round((now.timestamp() - as_of_ts) / 60))
    is_stale = quote_age_minutes > 20

    soxx_vs_qqq = changes["soxx"] - changes["qqq"]
    nvda_vs_soxx = changes["nvda"] - changes["soxx"]
    soxx_warning = soxx_vs_qqq <= -0.75
    nvda_warning = nvda_vs_soxx <= -0.75
    status_label = "STRESS" if soxx_warning and nvda_warning else "WATCH" if soxx_warning or nvda_warning else "NORMAL"
    score = 75 if status_label == "STRESS" else 45 if status_label == "WATCH" else 10
    interpretation = (
        "SOXX and NVDA are both lagging their comparison baskets in extended-hours trading."
        if status_label == "STRESS"
        else "One extended-hours equity warning is active; wait for regular-session and credit confirmation."
        if status_label == "WATCH"
        else "Extended-hours equity moves are not showing material AI infrastructure stress."
    )
    return base | {
        "market_state": market_state,
        "as_of": iso_from_timestamp(as_of_ts),
        "available": True,
        "is_stale": is_stale,
        "is_active_session": market_state in {"PRE", "POST"},
        "stale_reason": "Extended-hours quotes are more than 20 minutes old" if is_stale else "",
        "quote_age_minutes": quote_age_minutes,
        **enriched,
        "soxx_vs_qqq_change": round(soxx_vs_qqq, 2),
        "nvda_vs_soxx_change": round(nvda_vs_soxx, 2),
        "overlay_score": score,
        "status": status_label,
        "interpretation": interpretation,
    }


def build_latest(rows: list[dict[str, float | str]], manual: dict, extended_hours: dict | None = None) -> dict:
    row = rows[-1]
    cols = {key: [float(r[key]) for r in rows] for key in rows[0] if key != "date"}
    stress_score = int(row["stress_score"])
    rates_score = int(row["rates_score"])
    credit_score = int(row["credit_score"])
    equity_score = int(row["equity_score"])
    compute_score = int(row["compute_score"])
    credit_stable = change(cols["hy_oas"], 5) <= .08 and change(cols["ig_oas"], 5) <= .04
    soxx_qqq_20 = pct_change(cols["soxx_qqq_rel"], 20)
    nvda_soxx_20 = pct_change(cols["nvda_soxx_rel"], 20)
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
            {"key": "equity", "title": "Equity Confirmation", "score": equity_score, "status": status(equity_score), "bullets": ["SOXX lagging QQQ" if soxx_qqq_20 < 0 else "SOXX holding vs QQQ", "NVDA lagging SOXX" if nvda_soxx_20 < 0 else "NVDA holding vs SOXX"]},
            {"key": "compute", "title": "AI Financing / Compute", "score": compute_score, "status": status(compute_score), "bullets": [f"GPU proxy {manual.get('gpu_proxy_status', 'unknown').replace('_', ' ')}", "No bad filing" if manual.get("financing_headline_status") == "no_bad_filing" else "Financing headline flagged"]},
        ],
        "triggers": {
            "positive": ["HY OAS unchanged over 5d" if credit_stable else "Credit data still observable", "Hyperscaler capex guidance still intact" if manual.get("capex_guidance_status") == "intact" else "Capex guidance flagged", "SOXX not materially lagging QQQ" if soxx_qqq_20 > -8 else "Equity weakness visible"],
            "warning": ["SOFR remains above stress threshold", "2Y Treasury rising over 20d" if change(cols["dgs2"], 20) > 0 else "2Y Treasury still elevated", "SOXX trend negative vs QQQ over 20d" if soxx_qqq_20 < 0 else "Equity confirmation not negative"],
            "negative": ["No confirmed negative financing event" if manual.get("financing_headline_status") == "no_bad_filing" else "Negative financing event flagged", "No major capex cut" if manual.get("capex_guidance_status") == "intact" else "Capex cut flagged", "No major GPU rental collapse confirmed" if manual.get("gpu_proxy_status") != "collapse" else "GPU rental collapse flagged"],
        },
        "hard_data": [
            metric("sofr", "SOFR", row["sofr"], fmt_rate, cols["sofr"]),
            metric("dgs2", "2Y Treasury", row["dgs2"], fmt_rate, cols["dgs2"]),
            metric("dgs10", "10Y Treasury", row["dgs10"], fmt_rate, cols["dgs10"]),
            metric("ig_oas", "IG OAS", row["ig_oas"], fmt_bps, cols["ig_oas"]),
            metric("hy_oas", "HY OAS", row["hy_oas"], fmt_bps, cols["hy_oas"]),
            metric("soxx_qqq_rel", "SOXX / QQQ Relative", row["soxx_qqq_rel"], lambda v: f"{v:.2f}", cols["soxx_qqq_rel"], percent=True),
        ],
        "action": {
            "status": status(stress_score).upper(),
            "meaning": "Rate pressure remains, but credit markets have not confirmed deterioration. This looks more like valuation/rate pressure than an AI credit event." if stress_score < 65 else "Stress is broad enough to reduce risk until credit and equity confirmation improve.",
            "portfolio_read_through": ["No need to panic on one or two down days in AI stocks", "Avoid aggressive leverage or chasing neocloud exposure", "Core NVDA / hyperscaler exposure can be maintained", "Upgrade to STRESS only if HY OAS widens + equities lag + GPU rental proxy weakens"],
        },
        "extended_hours": extended_hours or build_extended_hours(None),
        "sources": ["FRED public CSV", "Yahoo Finance chart API", "config/manual_signals.json"],
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
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (data_dir / "latest.json").write_text(json.dumps(latest, indent=2) + "\n")


def self_test() -> None:
    assert status(25) == "NORMAL"
    assert status(26) == "WATCH"
    assert status(31) == "WATCH"
    assert status(50) == "WATCH"
    assert status(51) == "STRESS"
    assert status(70) == "STRESS"
    assert status(71) == "CREDIT STRESS CONFIRMED"
    assert round(pct_change([100, 110], 1), 2) == 10
    sample = {
        "soxx": {"marketState": "PRE", "preMarketChangePercent": -1.4, "preMarketTime": 1_800_000_000},
        "qqq": {"marketState": "PRE", "preMarketChangePercent": -0.2, "preMarketTime": 1_800_000_000},
        "nvda": {"marketState": "PRE", "preMarketChangePercent": -2.4, "preMarketTime": 1_800_000_000},
    }
    overlay = build_extended_hours(sample, datetime.fromtimestamp(1_800_000_100, timezone.utc))
    assert overlay["available"] is True
    assert overlay["is_active_session"] is True
    assert overlay["quote_age_minutes"] == 2
    assert overlay["is_stale"] is False
    assert overlay["status"] == "STRESS"
    assert overlay["soxx_vs_qqq_change"] == -1.2
    regular = build_extended_hours({"soxx": {"marketState": "REGULAR"}}, datetime.fromtimestamp(1_800_000_100, timezone.utc))
    assert regular["available"] is False
    assert regular["stale_reason"] == "Regular session is active; extended-hours overlay is inactive"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    series = {key: fetch_series(series_id) for key, series_id in FRED_SERIES.items()}
    series.update({key: fetch_price_series(symbol) for key, symbol in PRICE_SERIES.items()})
    try:
        extended_hours = build_extended_hours(fetch_extended_quotes(PRICE_SERIES))
    except Exception as exc:
        extended_hours = build_extended_hours(None) | {"error": str(exc)}
    manual = json.loads((ROOT / "config/manual_signals.json").read_text())
    rows = build_rows(series)
    write_outputs(rows, build_latest(rows, manual, extended_hours))


if __name__ == "__main__":
    main()
