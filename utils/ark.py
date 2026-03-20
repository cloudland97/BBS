import asyncio
import logging
import time
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
# CATHIESARK 평균 매입가 캐시 (24시간)
# =========================================================
_avg_cost_cache: dict | None = None   # {"data": {ticker: float}, "ts": float}
_AVG_COST_TTL = 24 * 3600


async def scrape_cathiesark_avg_costs() -> dict[str, float]:
    """cathiesark.com에서 ARK 전체 포트폴리오 평균 매입가 스크래핑.
    반환: {ticker: avg_cost} — 실패 시 {}
    """
    global _avg_cost_cache
    now = time.monotonic()
    if _avg_cost_cache and now - _avg_cost_cache["ts"] < _AVG_COST_TTL:
        return _avg_cost_cache["data"]

    from utils.playwright_manager import get_browser

    url = "https://cathiesark.com/ark-funds-combined/complete-holdings"
    result: dict[str, float] = {}

    try:
        browser = await get_browser()
        context = await browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(3)

            # 테이블 행 파싱
            rows = await page.query_selector_all("table tbody tr")
            for row in rows:
                try:
                    cells = await row.query_selector_all("td")
                    if len(cells) < 6:
                        continue
                    texts = [await c.inner_text() for c in cells]
                    # 컬럼: Rank, Company, Ticker, Shares, Weight, Avg Cost, Current Price, ...
                    # 사이트 구조에 따라 ticker/avg_cost 위치 추정
                    ticker = ""
                    avg_cost = 0.0
                    for i, t in enumerate(texts):
                        t = t.strip()
                        # ticker: 2~5 대문자
                        if not ticker and t.isupper() and 2 <= len(t) <= 5:
                            ticker = t
                        # avg_cost: $숫자 형태
                        if ticker and t.startswith("$"):
                            try:
                                avg_cost = float(t.replace("$", "").replace(",", ""))
                                break
                            except ValueError:
                                continue
                    if ticker and avg_cost:
                        result[ticker] = avg_cost
                except Exception:
                    continue
        finally:
            await context.close()
    except Exception as e:
        logger.warning("cathiesark 평균가 스크래핑 실패: %s %s", type(e).__name__, e)
        return {}

    if result:
        _avg_cost_cache = {"data": result, "ts": now}
        logger.info("cathiesark 평균가 수집: %d종목", len(result))
    return result


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
    """ETF 보유종목 조회 → {ticker: {shares, weight, market_value}} 반환."""
    url = f"https://arkfunds.io/api/v2/etf/holdings?symbol={etf}"
    try:
        async with session.get(url, headers=YF_HEADERS) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
            return {
                h["ticker"]: {
                    "shares": h.get("shares", 0),
                    "weight": h.get("weight", 0.0),
                    "market_value": h.get("market_value", 0.0),
                }
                for h in data.get("holdings", [])
            }
    except Exception as e:
        logger.warning("ARK holdings fetch 실패 (%s): %s %s", etf, type(e).__name__, e)
        return {}


async def _fetch_etf_aum(session: aiohttp.ClientSession, etf: str) -> float:
    """Yahoo Finance v8 chart에서 price × sharesOutstanding으로 AUM 계산. 실패 시 0.0 반환."""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{etf}?interval=1d&range=1d"
    try:
        async with session.get(url, headers=YF_HEADERS) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
            meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
            price  = meta.get("regularMarketPrice") or 0.0
            shares = meta.get("sharesOutstanding") or 0
            return price * shares
    except Exception as e:
        logger.warning("ETF AUM fetch 실패 (%s): %s %s", etf, type(e).__name__, e)
        return 0.0


async def fetch_ark_trades() -> dict:
    """최근 2거래일 전체 ARK 매매 내역 + 현재 보유량/market value 반환."""
    date_from = (datetime.now(KST) - timedelta(days=14)).strftime("%Y-%m-%d")
    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        all_results = await asyncio.gather(
            *[_fetch_ark_etf_trades(session, etf, date_from) for etf in ARK_ETFS],
            *[_fetch_ark_etf_holdings(session, etf) for etf in ARK_ETFS],
        )
    n = len(ARK_ETFS)
    trade_results   = all_results[:n]
    holding_results = all_results[n:]

    holdings = dict(zip(ARK_ETFS, holding_results))

    all_trades: list[dict] = []
    for trades in trade_results:
        all_trades.extend(trades)

    if not all_trades:
        return {"dates": [], "by_etf": {}, "holdings": holdings}

    # 최근 2거래일 추출
    dates = sorted({t["date"] for t in all_trades if t.get("date")}, reverse=True)[:2]

    # by_etf: {etf: {date: [trades]}}
    by_etf: dict[str, dict[str, list[dict]]] = {}
    for t in all_trades:
        if t.get("date") not in dates:
            continue
        etf  = t.get("fund", "?")
        date = t["date"]
        by_etf.setdefault(etf, {}).setdefault(date, []).append(t)

    # etf_percent 내림차순 정렬
    for etf in by_etf:
        for date in by_etf[etf]:
            by_etf[etf][date].sort(key=lambda x: x.get("etf_percent", 0) or 0, reverse=True)

    avg_costs = await scrape_cathiesark_avg_costs()
    return {"dates": dates, "by_etf": by_etf, "holdings": holdings, "avg_costs": avg_costs}


# =========================================================
# ARK MESSAGE FORMAT
# =========================================================
def format_ark_message(data: dict) -> str:
    dates     = data.get("dates", [])
    by_etf    = data.get("by_etf", {})
    holdings  = data.get("holdings", {})
    avg_costs = data.get("avg_costs", {})

    if not dates:
        return "🦆 **ARK 매매 내역**\n데이터를 불러올 수 없어."

    date_label = " · ".join(dates)
    parts = [f"🦆 **ARK 포트폴리오** ({date_label})", ""]

    # ── 포트폴리오 집계 ───────────────────────────────────────
    ticker_info: dict[str, dict] = {}
    for etf, etf_holdings in holdings.items():
        for ticker, h in etf_holdings.items():
            if ticker not in ticker_info:
                ticker_info[ticker] = {"market_value": 0.0, "total_shares": 0, "trades": []}
            ticker_info[ticker]["market_value"] += h.get("market_value", 0.0) or 0.0
            ticker_info[ticker]["total_shares"] += h.get("shares", 0) or 0

    # 최근 거래 수집 — holdings에 없는 신규 종목도 포함
    for etf, dates_dict in by_etf.items():
        for date in dates:
            for t in dates_dict.get(date, []):
                tkr = t.get("ticker")
                if not tkr:
                    continue
                if tkr not in ticker_info:
                    ticker_info[tkr] = {"market_value": 0.0, "total_shares": 0, "trades": []}
                ticker_info[tkr]["trades"].append({**t, "_etf": etf, "_date": date})

    # market_value 기준 정렬
    all_sorted = sorted(ticker_info.items(), key=lambda x: x[1]["market_value"], reverse=True)[:20]

    def _fmt_mv(v: float) -> str:
        if v >= 1e9:
            return f"${v/1e9:.2f}B"
        if v >= 1e6:
            return f"${v/1e6:.1f}M"
        if v >= 1e3:
            return f"${v/1e3:.0f}K"
        return f"${v:.0f}" if v else ""

    def _row_str(ticker: str, info: dict) -> str:
        mv     = info["market_value"]
        shares = info["total_shares"]
        avg    = avg_costs.get(ticker, 0.0)

        if not mv and not shares:
            weight_part = "신규"
        else:
            mv_str      = _fmt_mv(mv)
            share_str   = f"{shares:,}주" if shares else ""
            weight_part = f"{mv_str:<9}  {share_str}"

        avg_part = f"  평단${avg:,.2f}" if avg else ""

        if not info["trades"]:
            trade_part = ""
        else:
            t         = info["trades"][0]
            direction = t.get("direction", "?").upper()
            tr_shares = t.get("shares", 0) or 0
            arrow     = "🟢" if direction == "BUY" else "🔴"
            sign      = "+" if direction == "BUY" else "-"
            trade_part = f"  {arrow}{sign}{tr_shares:,}({t['_etf']})"

        return f"{ticker:<6}  {weight_part}{avg_part}{trade_part}"

    top20_set = {ticker for ticker, _ in all_sorted}
    lines = []
    for i, (ticker, info) in enumerate(all_sorted, 1):
        lines.append(f"{i:>2}  {_row_str(ticker, info)}")
    parts.append("**전체 Top 20**\n```\n" + "\n".join(lines) + "\n```")

    # 최근 2거래일 거래 종목 중 Top20 미포함
    traded_tickers = {
        t.get("ticker")
        for dates_dict in by_etf.values()
        for date in dates
        for t in dates_dict.get(date, [])
        if t.get("ticker")
    }
    extra = [
        (ticker, info) for ticker, info in
        sorted(ticker_info.items(), key=lambda x: x[1]["market_value"], reverse=True)
        if ticker in traded_tickers and ticker not in top20_set
    ]

    if extra:
        lines = []
        for i, (ticker, info) in enumerate(extra, len(all_sorted) + 1):
            lines.append(f"{i:>2}  {_row_str(ticker, info)}")
        parts.append("**최근 거래 종목 (Top20 외)**\n```\n" + "\n".join(lines) + "\n```")

    # ── 날짜별 매매 내역 ──────────────────────────────────────
    for date in dates:
        day_lines = []
        for etf in ARK_ETFS:
            etf_holdings = holdings.get(etf, {})
            day_trades   = by_etf.get(etf, {}).get(date, [])
            for t in day_trades:
                direction   = t.get("direction", "?").upper()
                ticker      = t.get("ticker", "?")
                traded      = t.get("shares", 0) or 0
                etf_pct     = t.get("etf_percent", 0.0) or 0.0
                arrow       = "🟢" if direction == "BUY" else "🔴"
                sign        = "+" if direction == "BUY" else "-"
                h           = etf_holdings.get(ticker, {})
                held_shares = h.get("shares", 0)
                weight      = h.get("weight", 0.0)
                hold_str    = f"{held_shares:>12,}주 ({weight:.2f}%)" if held_shares else "       미보유"
                day_lines.append(
                    f"{arrow} {direction:<4} {ticker:<6}  "
                    f"{sign}{traded:>9,}주 ({etf_pct:.3f}%)  →  {hold_str}"
                )
        if day_lines:
            parts.append(f"**{date} 매매**\n```\n" + "\n".join(day_lines) + "\n```")

    return "\n".join(parts)
