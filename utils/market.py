import asyncio
import json
import logging
import os
import urllib.request
from datetime import date, datetime, timedelta
from urllib.parse import quote as url_quote

import aiohttp

from config import (
    BOK_API_KEY,
    BOK_RATE,
    ET,
    FED_RATE,
    KST,
    MARKET_NOTIFIED_PATH,
    MARKET_SUB_PATH,
    YF_HEADERS,
)

logger = logging.getLogger(__name__)


# =========================================================
# JSON HELPERS
# =========================================================
def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =========================================================
# MARKET SUBSCRIBERS
# =========================================================
def load_market_subscribers() -> dict:
    return _load_json(MARKET_SUB_PATH, {"users": []})


def add_market_subscriber(user_id: int):
    data = load_market_subscribers()
    if str(user_id) not in data["users"]:
        data["users"].append(str(user_id))
    _save_json(MARKET_SUB_PATH, data)


def remove_market_subscriber(user_id: int):
    data = load_market_subscribers()
    data["users"] = [u for u in data["users"] if u != str(user_id)]
    _save_json(MARKET_SUB_PATH, data)


def get_market_subscribers() -> list[int]:
    return [int(u) for u in load_market_subscribers().get("users", [])]


def is_market_subscriber(user_id: int) -> bool:
    return str(user_id) in load_market_subscribers().get("users", [])


# =========================================================
# MARKET NOTIFIED STATE
# =========================================================
def load_market_notified() -> dict:
    return _load_json(MARKET_NOTIFIED_PATH, {})


def save_market_notified(data: dict):
    _save_json(MARKET_NOTIFIED_PATH, data)


def cleanup_market_notified(data: dict, days: int = 2) -> dict:
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    return {k: v for k, v in data.items() if k[:10] >= cutoff}


# =========================================================
# NASDAQ DST-AWARE TIMING
# =========================================================
def get_nasdaq_open_kst() -> str:
    today = date.today()
    open_et = datetime(today.year, today.month, today.day, 9, 30, tzinfo=ET)
    return open_et.astimezone(KST).strftime("%H:%M")


def get_nasdaq_close_kst() -> str:
    today = date.today()
    close_et = datetime(today.year, today.month, today.day, 16, 0, tzinfo=ET)
    return close_et.astimezone(KST).strftime("%H:%M")


# =========================================================
# MARKET CAP (CoinGecko — 코인 시총/순위, 무료/키 불필요)
# =========================================================
_COINGECKO_IDS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
}


def _fmt_mcap(v: float) -> str:
    if v >= 1e12: return f"${v/1e12:.2f}T"
    if v >= 1e9:  return f"${v/1e9:.0f}B"
    if v >= 1e6:  return f"${v/1e6:.0f}M"
    return f"${int(v)}"


async def fetch_coin_marketcaps() -> dict[str, dict]:
    """CoinGecko API로 코인 시총+순위 조회. {yf_sym: {rank, marketcap}} 반환."""
    ids = ",".join(_COINGECKO_IDS.values())
    url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={ids}"
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=YF_HEADERS) as r:
                r.raise_for_status()
                data = await r.json(content_type=None)
                id_to_sym = {v: k for k, v in _COINGECKO_IDS.items()}
                return {
                    id_to_sym[item["id"]]: {
                        "rank": item.get("market_cap_rank"),
                        "marketcap": item.get("market_cap"),
                    }
                    for item in data
                    if item.get("id") in id_to_sym
                }
    except Exception as e:
        logger.warning("CoinGecko fetch 실패: %s %s", type(e).__name__, e)
        return {}


# =========================================================
# MARKET DATA FETCH
# =========================================================
async def _fetch_yf(session: aiohttp.ClientSession, symbol: str) -> dict | None:
    encoded = url_quote(symbol, safe="-.")
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=2d"
    try:
        async with session.get(url, headers=YF_HEADERS) as r:
            r.raise_for_status()
            data = await r.json(content_type=None)
            result = data.get("chart", {}).get("result", [])
            if not result:
                return None
            meta = result[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            prev  = meta.get("previousClose") or meta.get("chartPreviousClose")
            if price is None:
                return None
            change_pct = ((price - prev) / prev * 100) if prev else 0.0
            return {"price": price, "change_pct": change_pct}
    except Exception as e:
        logger.warning("YF fetch 실패 (%s): %s %s", symbol, type(e).__name__, e)
        return None


_YF_SYMBOLS = [
    "USDKRW=X", "JPYKRW=X", "CNYKRW=X", "DX-Y.NYB",
    "^IXIC",
    "^KS11", "^KQ11", "^N225",
    "^VIX",
    "BTC-USD", "ETH-USD", "USDT-USD",
    "GC=F", "SI=F", "CL=F",
]

# FRED series: 미국 연방기금 상단 타깃 (공개 CSV, API 키 불필요)
_FRED_FED_SERIES = "DFEDTARU"


_FRED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _fetch_fred_rate_sync(series_id: str) -> tuple[float, float] | None:
    """FRED 공개 CSV 동기 fetch (urllib 사용, 스레드 실행용)."""
    start = (datetime.now(KST) - timedelta(days=90)).strftime("%Y-%m-%d")
    url = (
        f"https://fred.stlouisfed.org/graph/fredgraph.csv"
        f"?id={series_id}&observation_start={start}"
    )
    try:
        req = urllib.request.Request(url, headers=_FRED_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8-sig")  # BOM 자동 제거
        values = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue
            val = parts[1].strip()
            if not parts[0][:4].isdigit() or val in (".", ""):  # 날짜가 아니면 헤더
                continue
            try:
                values.append(float(val))
            except ValueError:
                continue
        if not values:
            return None
        current = values[-1]
        prev = next((v for v in reversed(values[:-1]) if v != current), current)
        return (current, prev)
    except Exception as e:
        logger.warning("FRED fetch 실패 (%s): %s %s", series_id, type(e).__name__, e)
        return None


async def _fetch_fred_rate(series_id: str) -> tuple[float, float] | None:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_fred_rate_sync, series_id)


async def _fetch_bok_rate() -> tuple[float, float] | None:
    """한국은행 ECOS API로 기준금리 조회. (current, prev) 반환. 키 없으면 None."""
    if not BOK_API_KEY:
        return None
    start = (datetime.now(KST) - timedelta(days=365)).strftime("%Y%m%d")
    end   = datetime.now(KST).strftime("%Y%m%d")
    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{BOK_API_KEY}"
        f"/json/kr/1/100/722Y001/D/{start}/{end}/0101000"
    )
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as r:
                r.raise_for_status()
                data = await r.json(content_type=None)
                rows = data.get("StatisticSearch", {}).get("row", [])
                values = [float(row["DATA_VALUE"]) for row in rows if row.get("DATA_VALUE")]
                if not values:
                    return None
                current = values[-1]
                prev = next((v for v in reversed(values[:-1]) if v != current), current)
                return (current, prev)
    except Exception as e:
        logger.warning("BOK API fetch 실패: %s %s", type(e).__name__, e)
        return None


async def _fetch_fear_greed() -> dict | None:
    """CNN Fear & Greed Index 조회 (API 키 불필요)."""
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://edition.cnn.com/",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as r:
                r.raise_for_status()
                data = await r.json(content_type=None)
                fg = data.get("fear_and_greed", {})
                score  = fg.get("score")
                rating = fg.get("rating", "")
                prev   = fg.get("previous_close")
                if score is None:
                    return None
                return {"score": round(score, 1), "rating": rating, "prev": round(prev, 1) if prev else None}
    except Exception as e:
        logger.warning("Fear&Greed fetch 실패: %s %s", type(e).__name__, e)
        return None


async def fetch_market_data() -> dict:
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        yf_results = await asyncio.gather(*[_fetch_yf(session, sym) for sym in _YF_SYMBOLS])

    fed_tuple, bok_tuple, fg, coin_mcap = await asyncio.gather(
        _fetch_fred_rate(_FRED_FED_SERIES),
        _fetch_bok_rate(),
        _fetch_fear_greed(),
        fetch_coin_marketcaps(),
    )

    if fed_tuple is None:
        fed_tuple = (FED_RATE, FED_RATE)
    if bok_tuple is None:
        bok_tuple = (BOK_RATE, BOK_RATE)

    return {
        "yf": dict(zip(_YF_SYMBOLS, yf_results)),
        "rates": {"fed": fed_tuple, "bok": bok_tuple},
        "fear_greed": fg,
        "mcap": coin_mcap,
    }


# =========================================================
# MARKET MESSAGE FORMAT
# =========================================================
def _arrow(pct: float) -> str:
    if pct > 0.05:  return "▲"
    if pct < -0.05: return "▼"
    return "→"


def _dot(pct: float | None, hi: float = 1.0, lo: float = 0.2) -> str:
    """변화율 기준 색상 점: 🟢🟡⚪🟠🔴"""
    if pct is None:   return "⚪"
    if pct >= hi:     return "🟢"
    if pct >= lo:     return "🟡"
    if pct <= -hi:    return "🔴"
    if pct <= -lo:    return "🟠"
    return "⚪"


def _code_section(rows: list[tuple], dot_fn=None) -> str:
    """rows: (label, price_str, pct) 또는 (label, price_str, pct, mcap_str)
    dot_fn: pct → 이모지 함수 (선택). 제공 시 각 행 앞에 색상 점 추가.
    """
    label_w = max(len(r[0]) for r in rows)
    price_w = max(len(r[1]) for r in rows)
    lines = []
    for row in rows:
        label, price_str, pct = row[0], row[1], row[2]
        mcap_str = row[3] if len(row) > 3 else ""
        prefix = (dot_fn(pct) + " ") if dot_fn else ""
        if pct is None:
            line = f"{prefix}{label:<{label_w}}  {price_str:>{price_w}}"
        else:
            line = (
                f"{prefix}{label:<{label_w}}  {price_str:>{price_w}}  "
                f"{_arrow(pct)} {abs(pct):>5.2f}%"
            )
        if mcap_str:
            line += f"  {mcap_str}"
        lines.append(line)
    return "```\n" + "\n".join(lines) + "\n```"


def format_market_message(data: dict, label: str) -> str:
    now = datetime.now(KST)
    ts  = now.strftime("%m/%d (%a) %H:%M")
    yf  = data.get("yf", {})

    def yf_row(sym: str, name: str, fmt: str = ",.0f") -> tuple:
        d = yf.get(sym)
        if d is None:
            return (name, "N/A", None)
        return (name, format(d["price"], fmt), d["change_pct"])

    def jpy_row() -> tuple:
        """JPY/KRW 100엔 기준으로 표시."""
        d = yf.get("JPYKRW=X")
        if d is None:
            return ("JPY100/KRW", "N/A", None)
        return ("JPY100/KRW", format(d["price"] * 100, ",.1f"), d["change_pct"])

    rates  = data.get("rates", {})
    mcap   = data.get("mcap", {})  # {yf_sym: {rank, marketcap}}

    def _mcap_tag(yf_sym: str) -> str:
        """YF 심볼 → '시총 #순위' 문자열. 데이터 없으면 빈 문자열."""
        item = mcap.get(yf_sym, {})
        cap  = item.get("marketcap")
        rank = item.get("rank")
        if not cap or not rank:
            return ""
        return f"{_fmt_mcap(cap)} #{rank}"

    def _fmt_rate_row(name: str, pair: tuple | None) -> str:
        if pair is None:
            return f"⚪ {name}  N/A"
        cur, prev = pair
        diff = cur - prev
        if abs(diff) < 0.001:
            return f"⚪ {name}  {cur:.2f}%  (동결)"
        icon  = "🔴" if diff > 0 else "🟢"
        arrow = "▲" if diff > 0 else "▼"
        return f"{icon} {name}  {cur:.2f}%  {arrow} {abs(diff):.2f}%p"

    def krw_coin_row(usd_sym: str, name: str) -> tuple:
        """USD 코인 가격 × USDKRW 환율 → 원화 표시."""
        d_coin = yf.get(usd_sym)
        d_fx   = yf.get("USDKRW=X")
        if d_coin is None or d_fx is None:
            return (name, "N/A", None)
        return (name, format(d_coin["price"] * d_fx["price"], ",.0f"), d_coin["change_pct"])

    def krw_metal_row(usd_sym: str, name: str) -> tuple:
        """귀금속 USD/oz × USDKRW ÷ 31.1035 × 3.75 → 원/돈(3.75g) 표시."""
        d_metal = yf.get(usd_sym)
        d_fx    = yf.get("USDKRW=X")
        if d_metal is None or d_fx is None:
            return (name, "N/A", None)
        krw_per_don = d_metal["price"] * d_fx["price"] / 31.1035 * 3.75
        return (name, format(krw_per_don, ",.0f"), d_metal["change_pct"])

    fx_rows = [
        yf_row("USDKRW=X", "USD/KRW",  ",.1f"),
        krw_coin_row("USDT-USD", "USDT/KRW"),
        jpy_row(),
        yf_row("CNYKRW=X", "CNY/KRW",  ",.2f"),
        yf_row("DX-Y.NYB", "DXY",      ",.2f"),
    ]
    asian_rows = [
        yf_row("^KS11", "KOSPI"),
        yf_row("^KQ11", "KOSDAQ"),
        yf_row("^N225", "닛케이"),
        yf_row("^IXIC", "NASDAQ"),
    ]

    def mcap_yf_row(sym: str, name: str, fmt: str = ",.0f") -> tuple:
        r = yf_row(sym, name, fmt)
        return (*r, _mcap_tag(sym))

    def mcap_krw_row(sym: str, name: str) -> tuple:
        r = krw_coin_row(sym, name)
        return (*r, _mcap_tag(sym))

    def mcap_metal_row(sym: str, name: str) -> tuple:
        r = krw_metal_row(sym, name)
        return (*r, _mcap_tag(sym))

    coin_rows = [
        mcap_yf_row("BTC-USD", "BTC(USD)"),
        mcap_yf_row("ETH-USD", "ETH(USD)"),
    ]
    fg = data.get("fear_greed")
    _rating_kr = {
        "Extreme Fear": "극단적 공포", "Fear": "공포",
        "Neutral": "중립", "Greed": "탐욕", "Extreme Greed": "극단적 탐욕",
    }
    _fg_dot = {
        "Extreme Fear": "🔴", "Fear": "🟠",
        "Neutral": "🟡", "Greed": "🟢", "Extreme Greed": "🔵",
    }

    def _fmt_fg() -> str:
        if fg is None:
            return "⚪  N/A"
        score  = fg["score"]
        rating = _rating_kr.get(fg["rating"], fg["rating"])
        dot    = _fg_dot.get(fg["rating"], "⚪")
        prev   = fg.get("prev")
        diff   = round(score - prev, 1) if prev is not None else None
        if diff is None or abs(diff) < 0.1:
            return f"{dot}  {score:.0f}  ({rating})"
        arrow = "▲" if diff > 0 else "▼"
        return f"{dot}  {score:.0f}  {arrow} {abs(diff):.1f}  ({rating})"

    commodity_rows = [
        mcap_metal_row("GC=F", "금(돈/KRW)"),
        mcap_metal_row("SI=F", "은(돈/KRW)"),
        yf_row("CL=F", "WTI(bbl)", ",.2f"),
    ]

    def _vix_dot(v: float) -> str:
        if v < 15:  return "🟢"
        if v < 20:  return "🟡"
        if v < 30:  return "🟠"
        return "🔴"

    def _vix_fg_block() -> str:
        vix_d = yf.get("^VIX")
        if vix_d:
            dot = _vix_dot(vix_d["price"])
            vix_line = (
                f"{dot} VIX       {format(vix_d['price'], ',.2f')}  "
                f"{_arrow(vix_d['change_pct'])} {abs(vix_d['change_pct']):>5.2f}%"
            )
        else:
            vix_line = "⚪ VIX       N/A"
        fg_line = f"   공포탐욕  {_fmt_fg()}"
        return f"```\n{vix_line}\n{fg_line}\n```"

    parts = [
        f"📊 **시황 브리핑** — {label}",
        f"📅 {ts} KST",
        "",
        "**🏦 기준금리**",
        f"```\n{_fmt_rate_row('연방기금  ', rates.get('fed'))}\n{_fmt_rate_row('한국은행  ', rates.get('bok'))}\n```",
        "**📈 증시 / 변동성**",
        _code_section(asian_rows, dot_fn=_dot),
        _vix_fg_block(),
        "**💱 환율 · 원자재 · 코인**",
        _code_section(fx_rows),
        _code_section(commodity_rows, dot_fn=_dot),
        _code_section(coin_rows, dot_fn=lambda pct: _dot(pct, hi=2.0, lo=0.5)),
    ]
    return "\n".join(parts)
