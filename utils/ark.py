import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp

from config import (
    ARK_ALERT_TIME,
    ARK_ETFS,
    ARK_NOTIFIED_PATH,
    ARK_SUB_PATH,
    KST,
    YF_HEADERS,
)
from utils.storage import load_json as _load_json, save_json as _save_json

logger = logging.getLogger(__name__)


# =========================================================
# ARK SUBSCRIBERS
# =========================================================
def load_ark_subscribers() -> dict:
    return _load_json(ARK_SUB_PATH, {"users": []})


def add_ark_subscriber(user_id: int):
    data = load_ark_subscribers()
    if str(user_id) not in data["users"]:
        data["users"].append(str(user_id))
    _save_json(ARK_SUB_PATH, data)


def remove_ark_subscriber(user_id: int):
    data = load_ark_subscribers()
    data["users"] = [u for u in data["users"] if u != str(user_id)]
    _save_json(ARK_SUB_PATH, data)


def get_ark_subscribers() -> list[int]:
    return [int(u) for u in load_ark_subscribers().get("users", [])]


def is_ark_subscriber(user_id: int) -> bool:
    return str(user_id) in load_ark_subscribers().get("users", [])


# =========================================================
# ARK NOTIFIED STATE
# =========================================================
def load_ark_notified() -> dict:
    return _load_json(ARK_NOTIFIED_PATH, {})


def save_ark_notified(data: dict):
    _save_json(ARK_NOTIFIED_PATH, data)


def cleanup_ark_notified(data: dict, days: int = 2) -> dict:
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    return {k: v for k, v in data.items() if k >= cutoff}


# =========================================================
# ARK TRADE FETCH
# =========================================================
async def _fetch_ark_etf_trades(
    session: aiohttp.ClientSession, etf: str, date_from: str
) -> list[dict]:
    url = f"https://arkfunds.io/api/v2/etf/trades?symbol={etf}&date_from={date_from}"
    try:
        async with session.get(url, headers=YF_HEADERS) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
            return data.get("trades", [])
    except Exception as e:
        logger.warning("ARK trades fetch 실패 (%s): %s %s", etf, type(e).__name__, e)
        return []


async def _fetch_ark_etf_holdings(
    session: aiohttp.ClientSession, etf: str
) -> dict[str, dict]:
    """ETF 보유종목 조회 → {ticker: {shares, weight}} 반환."""
    url = f"https://arkfunds.io/api/v2/etf/holdings?symbol={etf}"
    try:
        async with session.get(url, headers=YF_HEADERS) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
            return {
                h["ticker"]: {"shares": h.get("shares", 0), "weight": h.get("weight", 0.0)}
                for h in data.get("holdings", [])
            }
    except Exception as e:
        logger.warning("ARK holdings fetch 실패 (%s): %s %s", etf, type(e).__name__, e)
        return {}


async def fetch_ark_trades() -> dict:
    """가장 최근 거래일의 전체 ARK 매매 내역 + 현재 보유량/비중 반환."""
    date_from = (datetime.now(KST) - timedelta(days=7)).strftime("%Y-%m-%d")
    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        all_results = await asyncio.gather(
            *[_fetch_ark_etf_trades(session, etf, date_from) for etf in ARK_ETFS],
            *[_fetch_ark_etf_holdings(session, etf) for etf in ARK_ETFS],
        )
    n = len(ARK_ETFS)
    trade_results, holding_results = all_results[:n], all_results[n:]

    # holdings: {etf: {ticker: {shares, weight}}}
    holdings = dict(zip(ARK_ETFS, holding_results))

    all_trades: list[dict] = []
    for trades in trade_results:
        all_trades.extend(trades)

    if not all_trades:
        return {"date": None, "by_etf": {}, "holdings": holdings}

    latest_date = max(t["date"] for t in all_trades if t.get("date"))

    by_etf: dict[str, list[dict]] = {}
    for t in all_trades:
        if t.get("date") != latest_date:
            continue
        etf = t.get("fund", "?")
        by_etf.setdefault(etf, []).append(t)

    # etf_percent 내림차순 정렬
    for etf in by_etf:
        by_etf[etf].sort(key=lambda x: x.get("etf_percent", 0) or 0, reverse=True)

    return {"date": latest_date, "by_etf": by_etf, "holdings": holdings}


# =========================================================
# ARK MESSAGE FORMAT
# =========================================================
def format_ark_message(data: dict) -> str:
    trade_date = data.get("date")
    by_etf     = data.get("by_etf", {})
    holdings   = data.get("holdings", {})

    if not trade_date or not by_etf:
        return "🦆 **ARK 매매 내역**\n데이터를 불러올 수 없어."

    parts = [f"🦆 **ARK 매매 내역** ({trade_date})", ""]

    for etf in ARK_ETFS:
        trades = by_etf.get(etf)
        if not trades:
            continue

        etf_holdings = holdings.get(etf, {})
        parts.append(f"**{etf}**")
        lines = []
        for t in trades:
            direction   = t.get("direction", "?").upper()
            ticker      = t.get("ticker", "?")
            traded      = t.get("shares", 0) or 0
            etf_pct     = t.get("etf_percent", 0.0) or 0.0
            arrow       = "🟢" if direction == "BUY" else "🔴"
            sign        = "+" if direction == "BUY" else "-"

            h           = etf_holdings.get(ticker, {})
            held_shares = h.get("shares", 0)
            weight      = h.get("weight", 0.0)

            hold_str = f"{held_shares:>12,}주 ({weight:.2f}%)" if held_shares else "       미보유"
            lines.append(
                f"{arrow} {direction:<4} {ticker:<6}  "
                f"{sign}{traded:>9,}주 ({etf_pct:.3f}%)  →  {hold_str}"
            )
        parts.append("```\n" + "\n".join(lines) + "\n```")

    return "\n".join(parts)
