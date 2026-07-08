#!/usr/bin/env python3
"""Build data/latest.json and data/history.csv from public sources."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=6mo&interval=1d&events=history"
YAHOO_QUOTE = "https://query1.finance.yahoo.com/v7/finance/quote?symbols={}"
YAHOO_PREPOST_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}?interval=1m&range=1d&includePrePost=true"
SEC_COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{}.json"
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{}.json"
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "AIInfrastructureStressCockpit/1.0 contact: no-email")
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
COMPUTE_PRIMARY = {
    "crwv": "CRWV",
    "nbis": "NBIS",
    "apld": "APLD",
    "iren": "IREN",
}
INFRA_SPILLOVER = {
    "dlr": "DLR",
    "eqix": "EQIX",
    "vrt": "VRT",
    "etn": "ETN",
}
EXTRA_PRICE_SERIES = COMPUTE_PRIMARY | INFRA_SPILLOVER | {"xli": "XLI"}
COMPUTE_WEIGHTS = {
    "financing_event_score": .45,
    "balance_sheet_pressure_score": .25,
    "compute_equity_confirmation_score": .20,
    "infrastructure_spillover_score": .10,
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


def fetch_price_series_safe(symbol: str) -> dict[str, float]:
    try:
        return fetch_price_series(symbol)
    except Exception:
        return {}


def fetch_sec_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": SEC_USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.load(res)


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


def component_status(items: list[str]) -> str:
    if not items:
        return "ok"
    if all(item == "ok" for item in items):
        return "ok"
    if all(item in {"fallback", "failed"} for item in items):
        return "fallback"
    return "partial"


def parse_day(value: str | None) -> datetime.date | None:
    try:
        return datetime.fromisoformat(value or "").date()
    except ValueError:
        return None


def age_multiplier(filing_date: datetime.date, today: datetime.date) -> float:
    age = (today - filing_date).days
    if age <= 30:
        return 1.0
    if age <= 60:
        return .6
    return .3


def sec_ciks(tickers: list[str]) -> tuple[dict[str, str], str]:
    try:
        rows = fetch_sec_json(SEC_COMPANY_TICKERS).values()
        wanted = {ticker.upper() for ticker in tickers}
        return {
            row["ticker"].upper(): str(row["cik_str"]).zfill(10)
            for row in rows
            if row.get("ticker", "").upper() in wanted
        }, "ok"
    except Exception:
        return {}, "failed"


def build_financing_event_score(ciks: dict[str, str], today: datetime.date) -> dict:
    events = []
    failures = []
    offering_counts = {}
    shelf_forms = {"S-3", "S-3ASR", "F-3", "F-3ASR"}
    ignored_forms = {"3", "4", "5", "144"}

    for ticker in COMPUTE_PRIMARY.values():
        cik = ciks.get(ticker)
        if not cik:
            failures.append(ticker)
            continue
        try:
            recent = fetch_sec_json(SEC_SUBMISSIONS.format(cik)).get("filings", {}).get("recent", {})
        except Exception:
            failures.append(ticker)
            continue

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        items = recent.get("items", [])
        for i, form in enumerate(forms):
            form = str(form).upper()
            if form in ignored_forms:
                continue
            filing_date = parse_day(dates[i] if i < len(dates) else None)
            if not filing_date or not 0 <= (today - filing_date).days <= 90:
                continue

            signal_type = None
            base_points = 0
            reason = ""
            if form in shelf_forms:
                signal_type, base_points, reason = "shelf_registration", 8, "Shelf registration or financing capacity filing"
            elif form.startswith("424B"):
                signal_type, base_points, reason = "offering_prospectus", 12, "Prospectus or offering supplement"
            elif form == "8-K":
                item_text = str(items[i] if i < len(items) else "")
                material_financing = any(token in item_text for token in ("1.01", "2.03"))
                signal_type = "material_financing_8k" if material_financing else "recent_8k"
                base_points = 8 if material_financing else 3
                reason = "8-K references material agreement or debt item" if material_financing else "Recent 8-K counted as light financing flag"
            if not signal_type:
                continue

            points = round(base_points * age_multiplier(filing_date, today), 1)
            events.append({
                "ticker": ticker,
                "form": form,
                "filing_date": filing_date.isoformat(),
                "accession_number": accessions[i] if i < len(accessions) else "",
                "signal_type": signal_type,
                "points": points,
                "reason": reason,
            })
            if signal_type in {"shelf_registration", "offering_prospectus"}:
                offering_counts.setdefault(ticker, []).append(filing_date)

    for ticker, filing_dates in offering_counts.items():
        if len(filing_dates) > 1:
            latest = max(filing_dates)
            events.append({
                "ticker": ticker,
                "form": "MULTIPLE",
                "filing_date": latest.isoformat(),
                "accession_number": "",
                "signal_type": "multiple_offering_related_filings",
                "points": round(5 * age_multiplier(latest, today), 1),
                "reason": "Multiple shelf or offering-related filings within 90 days",
            })

    score = clamp(25 + sum(float(event["points"]) for event in events))
    return {
        "score": score if ciks else 25,
        "status": "failed" if len(failures) == len(COMPUTE_PRIMARY) else "partial" if failures else "ok",
        "events": sorted(events, key=lambda item: item["filing_date"], reverse=True)[:30],
        "failed_tickers": failures,
    }


def latest_fact(facts: dict, tags: list[str]) -> float | None:
    candidates = []
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        for unit_rows in gaap.get(tag, {}).get("units", {}).values():
            for row in unit_rows:
                if row.get("val") is None or row.get("form") not in {"10-Q", "10-K", "20-F", "6-K"}:
                    continue
                filed = parse_day(row.get("filed")) or parse_day(row.get("end"))
                if filed:
                    candidates.append((filed, float(row["val"])))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0])[-1][1]


def ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den <= 0:
        return None
    return num / den


def build_balance_sheet_score(ciks: dict[str, str]) -> dict:
    rows = []
    scores = []
    failures = []
    for ticker in COMPUTE_PRIMARY.values():
        cik = ciks.get(ticker)
        if not cik:
            failures.append(ticker)
            rows.append({"ticker": ticker, "data_status": "fallback"})
            continue
        try:
            facts = fetch_sec_json(SEC_FACTS.format(cik))
        except Exception:
            failures.append(ticker)
            rows.append({"ticker": ticker, "data_status": "failed"})
            continue

        cash = latest_fact(facts, ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"])
        debt_parts = [
            latest_fact(facts, [tag])
            for tag in ["LongTermDebt", "LongTermDebtCurrent", "ShortTermBorrowings", "DebtCurrent"]
        ]
        debt = sum(part for part in debt_parts if part and part > 0) or None
        revenue = latest_fact(facts, ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"])
        interest = latest_fact(facts, ["InterestExpenseNonOperating", "InterestExpense"])
        capex = latest_fact(facts, ["PaymentsToAcquirePropertyPlantAndEquipment"])
        ocf = latest_fact(facts, ["NetCashProvidedByUsedInOperatingActivities"])

        debt_to_cash = ratio(debt, cash)
        capex_to_revenue = ratio(abs(capex) if capex is not None else None, revenue)
        interest_to_revenue = ratio(abs(interest) if interest is not None else None, revenue)
        fcf_proxy_to_revenue = ratio((ocf or 0) - abs(capex), revenue) if ocf is not None and capex is not None else None
        company_score = 35
        if debt_to_cash is not None:
            company_score += 10 if debt_to_cash > 3 else 5 if debt_to_cash > 1.5 else 0
        if capex_to_revenue is not None:
            company_score += 10 if capex_to_revenue > .75 else 5 if capex_to_revenue > .35 else 0
        if interest_to_revenue is not None:
            company_score += 10 if interest_to_revenue > .10 else 5 if interest_to_revenue > .04 else 0
        if fcf_proxy_to_revenue is not None:
            company_score += 12 if fcf_proxy_to_revenue < -.50 else 8 if fcf_proxy_to_revenue < -.25 else 0

        usable = any(value is not None for value in (debt_to_cash, capex_to_revenue, interest_to_revenue, fcf_proxy_to_revenue))
        if usable:
            scores.append(clamp(company_score))
        rows.append({
            "ticker": ticker,
            "fiscal_period": "latest SEC fact",
            "debt_to_cash": round(debt_to_cash, 2) if debt_to_cash is not None else None,
            "capex_to_revenue": round(capex_to_revenue, 2) if capex_to_revenue is not None else None,
            "interest_to_revenue": round(interest_to_revenue, 2) if interest_to_revenue is not None else None,
            "fcf_proxy_to_revenue": round(fcf_proxy_to_revenue, 2) if fcf_proxy_to_revenue is not None else None,
            "score": clamp(company_score) if usable else None,
            "data_status": "ok" if usable else "fallback",
        })

    if len(scores) < 2:
        return {"score": 35, "status": "fallback", "rows": rows, "failed_tickers": failures}
    return {
        "score": clamp(sum(scores) / len(scores)),
        "status": "partial" if failures or len(scores) < len(COMPUTE_PRIMARY) else "ok",
        "rows": rows,
        "failed_tickers": failures,
    }


def series_return(series: dict[str, float], days: int) -> float | None:
    values = [series[date] for date in sorted(series)]
    if len(values) <= days or not values[-days - 1]:
        return None
    return (values[-1] / values[-days - 1] - 1) * 100


def average_return(price_series: dict[str, dict[str, float]], symbols: list[str], days: int) -> tuple[float | None, list[str]]:
    returns = [(symbol, series_return(price_series.get(symbol.lower(), {}), days)) for symbol in symbols]
    usable = [(symbol, value) for symbol, value in returns if value is not None]
    if not usable:
        return None, []
    return sum(value for _, value in usable) / len(usable), [symbol for symbol, _ in usable]


def build_equity_confirmation_score(price_series: dict[str, dict[str, float]]) -> dict:
    rel = {}
    usable_primary = []
    benchmark_symbols = ["QQQ", "SOXX"]
    for days in (5, 20, 60):
        basket, usable = average_return(price_series, list(COMPUTE_PRIMARY.values()), days)
        bench, _ = average_return(price_series, benchmark_symbols, days)
        if days == 60:
            usable_primary = usable
        rel[days] = None if basket is None or bench is None else basket - bench
    if len(usable_primary) < 2 or rel[20] is None:
        return {"score": 35, "status": "fallback", "details": {"usable_tickers": usable_primary}}
    score = 35 + max(-rel[20], 0) * 1.4 + max(-(rel[5] or 0), 0) * .7 + max(-(rel[60] or 0), 0) * .6 - max(rel[20], 0) * .2
    nvda_20 = series_return(price_series.get("nvda", {}), 20)
    basket_20, _ = average_return(price_series, list(COMPUTE_PRIMARY.values()), 20)
    return {
        "score": clamp(score),
        "status": "ok" if len(usable_primary) == len(COMPUTE_PRIMARY) else "partial",
        "details": {
            "usable_tickers": usable_primary,
            "benchmark": "50% QQQ / 50% SOXX",
            "relative_5d_pct_points": round(rel[5], 2) if rel[5] is not None else None,
            "relative_20d_pct_points": round(rel[20], 2) if rel[20] is not None else None,
            "relative_60d_pct_points": round(rel[60], 2) if rel[60] is not None else None,
            "nvda_relative_20d_pct_points": round(basket_20 - nvda_20, 2) if basket_20 is not None and nvda_20 is not None else None,
        },
    }


def build_infrastructure_spillover_score(price_series: dict[str, dict[str, float]]) -> dict:
    rel = {}
    usable_infra = []
    benchmark = ["QQQ", "XLI"] if price_series.get("xli") else ["QQQ"]
    for days in (5, 20):
        basket, usable = average_return(price_series, list(INFRA_SPILLOVER.values()), days)
        bench, _ = average_return(price_series, benchmark, days)
        if days == 20:
            usable_infra = usable
        rel[days] = None if basket is None or bench is None else basket - bench
    if len(usable_infra) < 2 or rel[20] is None:
        return {"score": 30, "status": "fallback", "details": {"usable_tickers": usable_infra}}
    score = 30 + max(-rel[20], 0) * 1.0 + max(-(rel[5] or 0), 0) * .4
    return {
        "score": clamp(score),
        "status": "ok" if len(usable_infra) == len(INFRA_SPILLOVER) else "partial",
        "details": {
            "usable_tickers": usable_infra,
            "benchmark": "50% QQQ / 50% XLI" if "XLI" in benchmark else "QQQ fallback",
            "relative_5d_pct_points": round(rel[5], 2) if rel[5] is not None else None,
            "relative_20d_pct_points": round(rel[20], 2) if rel[20] is not None else None,
        },
    }


def build_compute_stress(price_series: dict[str, dict[str, float]], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    ciks, cik_status = sec_ciks(list(COMPUTE_PRIMARY.values()))
    financing = build_financing_event_score(ciks, now.date()) if ciks else {"score": 25, "status": "failed", "events": [], "failed_tickers": list(COMPUTE_PRIMARY.values())}
    balance = build_balance_sheet_score(ciks) if ciks else {"score": 35, "status": "failed", "rows": [], "failed_tickers": list(COMPUTE_PRIMARY.values())}
    equity = build_equity_confirmation_score(price_series)
    spillover = build_infrastructure_spillover_score(price_series)
    raw_components = {
        "financing_event_score": financing,
        "balance_sheet_pressure_score": balance,
        "compute_equity_confirmation_score": equity,
        "infrastructure_spillover_score": spillover,
    }
    components = {
        key: {
            "score": value["score"],
            "weight": COMPUTE_WEIGHTS[key],
            "contribution": round(value["score"] * COMPUTE_WEIGHTS[key], 2),
            "status": value["status"],
        }
        for key, value in raw_components.items()
    }
    caveats = [
        "SEC data is best-effort.",
        "Filing detection is rule-based, not legal analysis.",
        "Equity-price data is confirmation, not the primary early-warning signal.",
        "No GPU rental pricing is scraped.",
    ]
    if cik_status != "ok":
        caveats.append("SEC ticker mapping failed; SEC components used fallback values.")
    if balance["status"] != "ok":
        caveats.append("XBRL balance-sheet extraction is partial or fallback for at least one primary ticker.")
    if equity["status"] != "ok" or spillover["status"] != "ok":
        caveats.append("Some Yahoo price histories were missing or too short for compute confirmation.")
    top_statuses = [component["status"] for component in components.values()]
    return {
        "score": clamp(sum(component["contribution"] for component in components.values())),
        "status": "ok" if all(item == "ok" for item in top_statuses) else "fallback" if all(item in {"fallback", "failed"} for item in top_statuses) else "partial",
        "generated_at": now.isoformat(timespec="seconds"),
        "components": components,
        "details": {
            "financing_events": financing["events"],
            "balance_sheet": balance["rows"],
            "equity_confirmation": equity["details"],
            "infrastructure_spillover": spillover["details"],
            "sec_status": cik_status if cik_status != "ok" else component_status([financing["status"], balance["status"]]),
            "caveats": caveats,
        },
    }


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


def build_latest(rows: list[dict[str, float | str]], extended_hours: dict | None = None, compute_stress: dict | None = None) -> dict:
    row = rows[-1]
    cols = {key: [float(r[key]) for r in rows] for key in rows[0] if key != "date"}
    stress_score = int(row["stress_score"])
    rates_score = int(row["rates_score"])
    credit_score = int(row["credit_score"])
    equity_score = int(row["equity_score"])
    compute_score = int(row["compute_score"])
    compute_stress = compute_stress or {
        "score": compute_score,
        "status": "fallback",
        "components": {},
        "details": {"financing_events": [], "balance_sheet": [], "caveats": ["Compute stress detail unavailable."]},
    }
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
            {"key": "compute", "title": "Compute Financing Stress", "score": compute_score, "status": status(compute_score), "bullets": [f"SEC data {compute_stress.get('status', 'fallback')}", "Financing filings detected" if compute_stress.get("details", {}).get("financing_events") else "No recent financing filing signal"]},
        ],
        "triggers": {
            "positive": ["HY OAS unchanged over 5d" if credit_stable else "Credit data still observable", "Official stress score remains close-based", "SOXX not materially lagging QQQ" if soxx_qqq_20 > -8 else "Equity weakness visible"],
            "warning": ["SOFR remains above stress threshold", "2Y Treasury rising over 20d" if change(cols["dgs2"], 20) > 0 else "2Y Treasury still elevated", "SOXX trend negative vs QQQ over 20d" if soxx_qqq_20 < 0 else "Equity confirmation not negative"],
            "negative": ["Recent financing filings detected" if compute_stress.get("details", {}).get("financing_events") else "No recent financing filing signal", "Balance-sheet data partial" if compute_stress.get("components", {}).get("balance_sheet_pressure_score", {}).get("status") != "ok" else "Balance-sheet extraction usable", "No GPU rental pricing scraped"],
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
        "compute_stress": compute_stress,
        "sources": ["FRED public CSV", "Yahoo Finance chart API", "SEC EDGAR submissions JSON", "SEC EDGAR companyfacts JSON"],
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
    dates = [(datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)).date().isoformat() for i in range(65)]
    prices = {key: {day: 100 - i * .3 for i, day in enumerate(dates)} for key in COMPUTE_PRIMARY}
    prices |= {
        "qqq": {day: 100 for day in dates},
        "soxx": {day: 100 for day in dates},
    }
    equity = build_equity_confirmation_score(prices)
    assert equity["status"] == "ok"
    assert equity["score"] > 35


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    series = {key: fetch_series(series_id) for key, series_id in FRED_SERIES.items()}
    series.update({key: fetch_price_series(symbol) for key, symbol in PRICE_SERIES.items()})
    compute_prices = {key: series.get(key, {}) for key in PRICE_SERIES}
    compute_prices.update({key: fetch_price_series_safe(symbol) for key, symbol in EXTRA_PRICE_SERIES.items()})
    try:
        extended_hours = build_extended_hours(fetch_extended_quotes(PRICE_SERIES))
    except Exception as exc:
        extended_hours = build_extended_hours(None) | {"error": str(exc)}
    rows = build_rows(series)
    compute_stress = build_compute_stress(compute_prices)
    rows[-1]["compute_score"] = compute_stress["score"]
    rows[-1]["stress_score"] = clamp(float(rows[-1]["rates_score"]) * .35 + float(rows[-1]["credit_score"]) * .35 + float(rows[-1]["equity_score"]) * .20 + compute_stress["score"] * .10)
    write_outputs(rows, build_latest(rows, extended_hours, compute_stress))


if __name__ == "__main__":
    main()
