"""전국은행연합회 고시환율 — smbs.biz 스크래핑.

USD / JPY / EUR 매매기준율을 가져와 DM 발송용 메시지를 생성한다.
데이터 소스: http://www.smbs.biz/Flash/TodayExRate_flash.jsp?tr_date=YYYY-MM-DD
"""

import logging
import time
from datetime import datetime, timedelta
import aiohttp

from config import KST, YF_HEADERS

_exrate_cache: dict | None = None
_EXRATE_CACHE_TTL = 600

logger = logging.getLogger(__name__)

_BASE_URL = "http://www.smbs.biz/Flash/TodayExRate_flash.jsp"
_TARGETS  = ["USD", "JPY", "EUR", "CNH"]
# (symbol, updown_key, diff_key)  — conId 배열 순서 기준 (1-indexed)
_META = [
    ("USD", "updown1", "diff1"),
    ("JPY", "updown2", "diff2"),
    ("EUR", "updown3", "diff3"),
    ("CNH", "updown9", "diff9"),
]


# =========================================================
# FETCH
# =========================================================
async def _fetch_for_date(session: aiohttp.ClientSession, date_str: str) -> dict | None:
    """주어진 날짜(YYYY-MM-DD)의 환율 데이터를 가져온다. 데이터 없으면 None."""
    try:
        async with session.get(_BASE_URL, params={"tr_date": date_str}, headers=YF_HEADERS) as r:
            r.raise_for_status()
            text = await r.text()
    except Exception as e:
        logger.warning("smbs fetch 실패 (%s): %s", date_str, e)
        return None

    # 실데이터 없으면 "?test0=test&updown=0&loading=ok&" 수준의 짧은 응답
    if len(text.strip()) < 100:
        return None

    qs = text.strip().lstrip("?")
    params = {}
    for part in qs.split("&"):
        if "=" in part:
            k, _, v = part.partition("=")
            params[k.strip()] = v.strip()

    rates, diffs, updowns = {}, {}, {}
    for symbol, updown_key, diff_key in _META:
        raw = params.get(symbol, "")
        if not raw:
            continue
        try:
            rates[symbol] = float(raw.replace(",", ""))
        except ValueError:
            continue
        try:
            diffs[symbol] = float(params.get(diff_key, "0") or "0")
        except ValueError:
            diffs[symbol] = 0.0
        updowns[symbol] = params.get(updown_key, "3")

    if not rates:
        return None
    return {"rates": rates, "diffs": diffs, "updowns": updowns}


async def fetch_exrate() -> dict:
    """최근 영업일 환율(USD/JPY/EUR) 반환.
    반환: {"date": "YYYY-MM-DD", "rates": {...}, "diffs": {...}, "updowns": {...}}
    실패 시: {"date": None, "rates": {}, "diffs": {}, "updowns": {}}
    """
    global _exrate_cache
    now = time.monotonic()
    if _exrate_cache is not None and now - _exrate_cache["ts"] < _EXRATE_CACHE_TTL:
        return _exrate_cache["data"]

    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        today = datetime.now(KST)
        for delta in range(7):
            candidate = today - timedelta(days=delta)
            date_str = candidate.strftime("%Y-%m-%d")
            data = await _fetch_for_date(session, date_str)
            if data:
                logger.info("smbs 환율 수집: %s %s", date_str, data["rates"])
                result = {"date": date_str, **data}
                _exrate_cache = {"data": result, "ts": now}
                return result

    logger.warning("smbs 환율 수집 실패: 최근 7일 데이터 없음")
    return {"date": None, "rates": {}, "diffs": {}, "updowns": {}}


# =========================================================
# FORMAT
# =========================================================
_LABELS   = {"USD": "달러  (USD/KRW)", "JPY": "엔화  (JPY/100)", "EUR": "유로  (EUR/KRW)"}
_ARROW    = {"0": "▲", "1": "▼", "3": "─", "2": "▲"}


def format_exrate_message(data: dict, title: str = "고시환율") -> str:
    date    = data.get("date") or "?"
    rates   = data.get("rates", {})
    diffs   = data.get("diffs", {})
    updowns = data.get("updowns", {})

    if not rates:
        return f"💱 **{title}**\n데이터를 불러올 수 없어."

    lines = []
    for symbol in _TARGETS:
        val = rates.get(symbol)
        if val is None:
            continue
        label  = _LABELS.get(symbol, symbol)
        diff   = diffs.get(symbol, 0.0)
        arrow  = _ARROW.get(updowns.get(symbol, "3"), "─")
        lines.append(f"{label:<16} ₩{val:>10,.2f}  {arrow}{diff:+.2f}")

    # 크로스레이트
    usd = rates.get("USD")
    jpy = rates.get("JPY")
    eur = rates.get("EUR")
    cross_lines = []
    if usd and jpy:
        usdjpy = usd / (jpy / 100)
        cross_lines.append(f"{'USD/JPY':<16} {usdjpy:>10.2f}")
    if usd and eur:
        eurusd = eur / usd
        cross_lines.append(f"{'EUR/USD':<16} {eurusd:>10.4f}")

    body = "\n".join(lines)
    if cross_lines:
        body += "\n\n[크로스레이트]\n" + "\n".join(cross_lines)

    return f"💱 **{title}** ({date})\n```\n{body}\n```"
