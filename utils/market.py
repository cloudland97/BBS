import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from urllib.parse import quote as url_quote

import aiohttp

from config import (
    BOK_LAST_MEETING,
    BOK_RATE,
    ET,
    FED_LAST_MEETING,
    FED_RATE,
    KST,
    KIS_APP_KEY,
    KIS_APP_SECRET,
    MARKET_NOTIFIED_PATH,
    MARKET_SUB_PATH,
    YF_HEADERS,
)
from utils.storage import load_json as _load_json, save_json as _save_json

logger = logging.getLogger(__name__)


# =========================================================
# MARKET SUBSCRIBERS
# mode: "all" | "kr" | "us"
# =========================================================
def load_market_subscribers() -> dict:
    data = _load_json(MARKET_SUB_PATH, {"users": {}})
    # 하위호환: list → dict 마이그레이션
    if isinstance(data.get("users"), list):
        data["users"] = {u: "all" for u in data["users"]}
        _save_json(MARKET_SUB_PATH, data)
    return data


def add_market_subscriber(user_id: int, mode: str = "all"):
    data = load_market_subscribers()
    data["users"][str(user_id)] = mode
    _save_json(MARKET_SUB_PATH, data)


def remove_market_subscriber(user_id: int):
    data = load_market_subscribers()
    data["users"].pop(str(user_id), None)
    _save_json(MARKET_SUB_PATH, data)


def get_market_subscribers_for_time(time_type: str) -> list[int]:
    """time_type: 'kr' or 'us' — 해당 시간대를 구독 중인 user_id 목록."""
    users = load_market_subscribers().get("users", {})
    return [int(uid) for uid, mode in users.items() if mode in ("all", time_type)]


def get_market_subscriber_mode(user_id: int) -> str | None:
    return load_market_subscribers().get("users", {}).get(str(user_id))


def get_market_subscribers() -> list[int]:
    """전체 시황 구독자 (하위호환용)."""
    return [int(u) for u in load_market_subscribers().get("users", {}).keys()]


def is_market_subscriber(user_id: int) -> bool:
    return str(user_id) in load_market_subscribers().get("users", {})


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
    "^KS11", "^KQ11",
    "BTC-USD", "ETH-USD", "USDT-USD",
    "GC=F", "SI=F", "CL=F",
]

_SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

_FED_BASE = "https://www.federalreserve.gov"

# 금리는 연 8회만 바뀜 — 1시간 캐시로 불필요한 스크래핑 방지
_RATE_CACHE_TTL = 3600
_rate_cache: dict[str, tuple] = {}  # {"fed": (result, expires_ts), "bok": (result, expires_ts)}


def _parse_fed_fraction(s: str) -> float | None:
    """'3-1/2', '3‑3/4' 등 분수 표기(Unicode 하이픈 포함)를 float으로."""
    s = s.strip().replace("\u2011", "-").replace("\u2010", "-")
    m = re.match(r"^(\d+)-(\d+)/(\d+)$", s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    try:
        return float(s)
    except ValueError:
        return None


async def _fetch_fed_rate_from_fomc() -> tuple[float, float, str] | None:
    """Fed FOMC 보도자료 파싱 → (upper_rate, prev_upper_rate, date_str). 실패 시 None."""
    cached = _rate_cache.get("fed")
    if cached and datetime.now(KST).timestamp() < cached[1]:
        return cached[0]

    calendar_url = f"{_FED_BASE}/monetarypolicy/fomccalendars.htm"
    timeout = aiohttp.ClientTimeout(total=20)

    async def _fetch_text(session: aiohttp.ClientSession, url: str) -> str | None:
        try:
            async with session.get(url, headers=_SCRAPE_HEADERS) as r:
                r.raise_for_status()
                return await r.text()
        except Exception as e:
            logger.warning("FOMC fetch 실패 (%s): %s", url[-30:], e)
            return None

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            html = await _fetch_text(session, calendar_url)
            if not html:
                return None

            date_codes = sorted(
                set(re.findall(r"/newsevents/pressreleases/monetary(\d{8})a\.htm", html)),
                reverse=True,
            )
            if len(date_codes) < 2:
                return None

            # 최신 3개 병렬 fetch (2개면 충분하지만 1개 실패 대비)
            urls = [f"{_FED_BASE}/newsevents/pressreleases/monetary{c}a.htm" for c in date_codes[:3]]
            texts = await asyncio.gather(*[_fetch_text(session, u) for u in urls])

        _rate_pat = re.compile(
            r"(?:federal funds rate|target range)\s+(?:at\s+|to\s+remain\s+at\s+)"
            r"([\d\u2011\-]+(?:/\d+)?)\s+to\s+([\d\u2011\-]+(?:/\d+)?)\s+percent",
            re.IGNORECASE,
        )
        rates: list[tuple[float, str]] = []
        for code, text in zip(date_codes[:3], texts):
            if not text:
                continue
            m = _rate_pat.search(text)
            if not m:
                continue
            upper = _parse_fed_fraction(m.group(2))
            if upper is None:
                continue
            rates.append((upper, f"{code[2:4]}.{code[4:6]}.{code[6:8]}"))

        if not rates:
            return None
        cur_rate, cur_date = rates[0]
        prev_rate = next((r for r, _ in rates[1:] if r != cur_rate), cur_rate)

        if not (0.0 <= cur_rate <= 15.0):
            logger.warning("Fed rate 검증 실패: %.2f%%", cur_rate)
            return None
        if abs(cur_rate - prev_rate) > 1.0:
            logger.warning("Fed rate 변동 과대: %.2f → %.2f", prev_rate, cur_rate)
            return None

        result = (cur_rate, prev_rate, cur_date)
        _rate_cache["fed"] = (result, datetime.now(KST).timestamp() + _RATE_CACHE_TTL)
        return result
    except Exception as e:
        logger.warning("FOMC 페이지 fetch 실패: %s %s", type(e).__name__, e)
        return None


async def _fetch_bok_rate_from_web() -> tuple[float, float, str] | None:
    """BOK 영문 공식 페이지 파싱 → (current_rate, prev_rate, date_str). 실패 시 None."""
    cached = _rate_cache.get("bok")
    if cached and datetime.now(KST).timestamp() < cached[1]:
        return cached[0]

    url = "https://www.bok.or.kr/eng/singl/baseRate/progress.do?dataSeCd=01&menuNo=400016"
    timeout = aiohttp.ClientTimeout(total=20)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=_SCRAPE_HEADERS) as r:
                r.raise_for_status()
                html = await r.text()

        # JS 블록 주석(/* ... */) 제거 후 파싱 — 주석 처리된 구버전 배열 무시
        html_nc = re.sub(r"/\*.*?\*/", "", html, flags=re.DOTALL)
        # 마지막 항목은 날짜 뒤에 시간 등 추가 문자가 붙을 수 있음: ["2026/03/21 13", ...]
        pairs = re.findall(r'\["(\d{4}/\d{2}/\d{2})[^"]*",\s*([\d.]+)\]', html_nc)
        if len(pairs) < 2:
            return None

        cur_rate = float(pairs[-1][1])
        prev_rate = next(
            (float(r) for _, r in reversed(pairs[:-1]) if float(r) != cur_rate),
            cur_rate,
        )
        # 차트는 금리 변경일만 기록 — 동결 포함 마지막 회의일은 config에서 가져옴
        dt = BOK_LAST_MEETING

        if not (0.0 <= cur_rate <= 15.0):
            logger.warning("BOK rate 검증 실패: %.2f%%", cur_rate)
            return None
        if abs(cur_rate - prev_rate) > 1.0:
            logger.warning("BOK rate 변동 과대: %.2f → %.2f", prev_rate, cur_rate)
            return None

        result = (cur_rate, prev_rate, dt)
        _rate_cache["bok"] = (result, datetime.now(KST).timestamp() + _RATE_CACHE_TTL)
        return result
    except Exception as e:
        logger.warning("BOK 웹 페이지 fetch 실패: %s %s", type(e).__name__, e)
        return None



# =========================================================
# KIS OpenAPI
# =========================================================
_kis_token: str | None = None
_kis_token_expires: datetime | None = None
_kis_token_lock: asyncio.Lock | None = None
_KIS_TOKEN_PATH = "kis_token.json"


def _get_kis_lock() -> asyncio.Lock:
    global _kis_token_lock
    if _kis_token_lock is None:
        _kis_token_lock = asyncio.Lock()
    return _kis_token_lock


async def _fetch_kis_token() -> str | None:
    """KIS OAuth2 액세스 토큰 발급 (24시간 캐시)."""
    global _kis_token, _kis_token_expires
    if not KIS_APP_KEY or not KIS_APP_SECRET:
        return None
    global _kis_token, _kis_token_expires
    now = datetime.now(KST)
    if _kis_token and _kis_token_expires and now < _kis_token_expires:
        return _kis_token
    async with _get_kis_lock():
        if _kis_token and _kis_token_expires and now < _kis_token_expires:
            return _kis_token
        # 파일 캐시 확인 (프로세스 재시작 시 토큰 재사용)
        try:
            import json as _json
            with open(_KIS_TOKEN_PATH, encoding="utf-8") as f:
                cached = _json.load(f)
            exp = datetime.fromisoformat(cached["expires"])
            if now < exp and cached.get("token"):
                _kis_token = cached["token"]
                _kis_token_expires = exp
                return _kis_token
        except Exception:
            pass
        # 새 토큰 발급
        url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
        body = {"grant_type": "client_credentials", "appkey": KIS_APP_KEY, "appsecret": KIS_APP_SECRET}
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=body) as r:
                    r.raise_for_status()
                    j = await r.json(content_type=None)
            _kis_token = j.get("access_token")
            _kis_token_expires = now + timedelta(hours=23)
            try:
                import json as _json
                with open(_KIS_TOKEN_PATH, "w", encoding="utf-8") as f:
                    _json.dump({"token": _kis_token, "expires": _kis_token_expires.isoformat()}, f)
            except Exception:
                pass
            return _kis_token
        except Exception as e:
            logger.warning("KIS 토큰 발급 실패: %s %s", type(e).__name__, e)
            return None


_NAVER_TREND_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Referer": "https://finance.naver.com/",
}


async def fetch_investor_trends() -> dict:
    """NAVER Finance JSON API — KOSPI/KOSDAQ 투자자별 순매수 (억원).
    반환: {"kospi": {"개인":int,"외국인":int,"기관":int}, "kosdaq": {...}}
    실패 시 빈 dict 반환."""
    def _parse(val: str) -> int:
        try:
            return int(str(val).replace(",", "").replace("+", "") or "0")
        except ValueError:
            return 0

    result: dict = {}
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for market_key, naver_code in [("kospi", "KOSPI")]:  # KOSDAQ: 추가 시 ("kosdaq", "KOSDAQ") 포함
                url = f"https://m.stock.naver.com/api/index/{naver_code}/trend"
                try:
                    async with session.get(url, headers=_NAVER_TREND_HEADERS) as r:
                        r.raise_for_status()
                        j = await r.json(content_type=None)
                    bizdate = j.get("bizdate", "")
                    date_fmt = f"{bizdate[2:4]}.{bizdate[4:6]}.{bizdate[6:8]}" if len(bizdate) == 8 else ""
                    result[market_key] = {
                        "개인":   _parse(j.get("personalValue", "0")),
                        "외국인": _parse(j.get("foreignValue", "0")),
                        "기관":   _parse(j.get("institutionalValue", "0")),
                        "date":   date_fmt,
                    }
                except Exception as e:
                    logger.warning("NAVER %s 투자자 fetch 실패: %s %s", naver_code, type(e).__name__, e)
    except Exception as e:
        logger.warning("투자자 trend fetch 실패: %s %s", type(e).__name__, e)
    return result


async def fetch_kospi_night_futures() -> dict | None:
    """KIS OpenAPI — 코스피 야간선물 현재가. {price, change_pct}. 실패 시 None."""
    token = await _fetch_kis_token()
    if not token:
        return None
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-futureoption/v1/quotations/inquire-price"
    headers = {
        "authorization": f"Bearer {token}",
        "appkey":        KIS_APP_KEY,
        "appsecret":     KIS_APP_SECRET,
        "tr_id":         "FHMIF10000000",
        "content-type":  "application/json; charset=utf-8",
    }
    params = {
        "FID_COND_MRKT_DIV_CODE": "NF",  # 야간선물
        "FID_INPUT_ISCD":         "101NF",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, params=params) as r:
                r.raise_for_status()
                j = await r.json(content_type=None)
        out = j.get("output", {})
        if not out:
            return None
        price = float(str(out.get("LAST", "0")).replace(",", "") or "0")
        prev  = float(str(out.get("PREV_PRICE", "0")).replace(",", "") or "0")
        if price == 0:
            return None
        change_pct = ((price - prev) / prev * 100) if prev else 0.0
        return {"price": price, "change_pct": change_pct}
    except Exception as e:
        logger.warning("KIS 야간선물 fetch 실패: %s %s", type(e).__name__, e)
        return None


async def fetch_kis_indices() -> dict[str, dict]:
    """KIS OpenAPI — KOSPI/KOSDAQ 실시간 지수. {'^KS11': {price, change_pct}, ...}
    실패 시 빈 dict 반환 → YF fallback 사용."""
    token = await _fetch_kis_token()
    if not token:
        return {}

    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-index-price"
    headers = {
        "authorization": f"Bearer {token}",
        "appkey":        KIS_APP_KEY,
        "appsecret":     KIS_APP_SECRET,
        "tr_id":         "FHPUP02100000",
        "content-type":  "application/json; charset=utf-8",
    }
    # KIS 코드 → YF 심볼 매핑
    targets = [("0001", "^KS11"), ("1001", "^KQ11")]
    result: dict[str, dict] = {}
    timeout = aiohttp.ClientTimeout(total=10)

    async def _fetch_one(session: aiohttp.ClientSession, iscd: str, yf_sym: str):
        params = {"FID_COND_MRKT_DIV_CODE": "U", "FID_INPUT_ISCD": iscd}
        try:
            async with session.get(url, headers=headers, params=params) as r:
                r.raise_for_status()
                j = await r.json(content_type=None)
            out = j.get("output", {})
            price = float(str(out.get("bstp_nmix_prpr", "0")).replace(",", "") or "0")
            pct   = float(str(out.get("bstp_nmix_prdy_ctrt", "0")).replace(",", "") or "0")
            if price == 0:
                return
            result[yf_sym] = {"price": price, "change_pct": pct}
        except Exception as e:
            logger.warning("KIS 지수 fetch 실패 (%s): %s %s", iscd, type(e).__name__, e)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            await asyncio.gather(*[_fetch_one(session, iscd, sym) for iscd, sym in targets])
    except Exception as e:
        logger.warning("KIS 지수 세션 실패: %s %s", type(e).__name__, e)
    return result


async def _fetch_yf_all() -> list:
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        return await asyncio.gather(*[_fetch_yf(session, sym) for sym in _YF_SYMBOLS])


async def fetch_market_data() -> dict:
    (yf_results, (
        fed_tuple, bok_tuple, coin_mcap, investors, night_futures, kis_indices
    )) = await asyncio.gather(
        _fetch_yf_all(),
        asyncio.gather(
            _fetch_fed_rate_from_fomc(),
            _fetch_bok_rate_from_web(),
            fetch_coin_marketcaps(),
            fetch_investor_trends(),
            fetch_kospi_night_futures(),
            fetch_kis_indices(),
        ),
    )

    if fed_tuple is None:
        fed_tuple = (FED_RATE, FED_RATE, FED_LAST_MEETING)
    if bok_tuple is None:
        bok_tuple = (BOK_RATE, BOK_RATE, BOK_LAST_MEETING)

    # KIS 실시간 지수로 YF 결과 대체 (KIS 실패 시 YF 유지)
    yf_dict = dict(zip(_YF_SYMBOLS, yf_results))
    yf_dict.update(kis_indices)

    return {
        "yf": yf_dict,
        "rates": {"fed": fed_tuple, "bok": bok_tuple},
        "mcap": coin_mcap,
        "investors": investors,
        "night_futures": night_futures,
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
        cur, prev = pair[0], pair[1]
        date_tag  = f"  '{pair[2]}" if len(pair) > 2 and pair[2] else ""
        diff = cur - prev
        if abs(diff) < 0.001:
            return f"⚪ {name}  {cur:.2f}%  (동결){date_tag}"
        icon  = "🔴" if diff > 0 else "🟢"
        arrow = "▲" if diff > 0 else "▼"
        return f"{icon} {name}  {cur:.2f}%  {arrow} {abs(diff):.2f}%p{date_tag}"

    def krw_metal_row(usd_sym: str, name: str) -> tuple:
        """귀금속 USD/oz × USDKRW ÷ 31.1035 × 3.75 → 원/돈(3.75g) 표시."""
        d_metal = yf.get(usd_sym)
        d_fx    = yf.get("USDKRW=X")
        if d_metal is None or d_fx is None:
            return (name, "N/A", None)
        krw_per_don = d_metal["price"] * d_fx["price"] / 31.1035 * 3.75
        return (name, format(krw_per_don, ",.0f"), d_metal["change_pct"])

    def krw_coin_row(usd_sym: str, name: str) -> tuple:
        """USD 코인 가격 × USDKRW 환율 → 원화 표시."""
        d_coin = yf.get(usd_sym)
        d_fx   = yf.get("USDKRW=X")
        if d_coin is None or d_fx is None:
            return (name, "N/A", None)
        return (name, format(d_coin["price"] * d_fx["price"], ",.0f"), d_coin["change_pct"])

    def _rates_section() -> str:
        return "\n".join([
            _fmt_rate_row("연방기금", rates.get("fed")),
            _fmt_rate_row("한국은행", rates.get("bok")),
        ])

    def _index_section() -> str:
        # NASDAQ > KOSPI > KOSDAQ (수치 높은 순)
        rows = [
            yf_row("^IXIC", "NASDAQ"),
            yf_row("^KS11", "KOSPI"),
            yf_row("^KQ11", "KOSDAQ"),
        ]
        return _code_section(rows, dot_fn=_dot)

    def _night_futures_row() -> str | None:
        nf = data.get("night_futures")
        if not nf:
            return None
        price = format(nf["price"], ",.2f")
        pct   = nf["change_pct"]
        return f"{_dot(pct)} KOSPI야간선물  {price}  {_arrow(pct)} {abs(pct):.2f}%"

    def _investor_section() -> str | None:
        inv = data.get("investors")
        if not inv:
            return None

        def _fmt(v: int) -> str:
            sign = "+" if v >= 0 else ""
            return f"{sign}{v:,}억"

        def _inv_dot(v: int) -> str:
            if v >= 500:  return "🟢"
            if v >= 100:  return "🟡"
            if v <= -500: return "🔴"
            if v <= -100: return "🟠"
            return "⚪"

        order = ["개인", "외국인", "기관"]
        markets = [(k, lbl) for k, lbl in [("kospi", "KOSPI"), ("kosdaq", "KOSDAQ")] if inv.get(k)]
        show_header = len(markets) > 1
        lines = []
        for mkt_key, mkt_label in markets:
            mkt = inv[mkt_key]
            items = [(k, mkt.get(k, 0)) for k in order]
            label_w = max(len(k) for k, _ in items)
            val_w   = max(len(_fmt(v)) for _, v in items)
            header = f"── {mkt_label} ──" if show_header else ""
            date_tag = f"  '{mkt['date']}" if mkt.get("date") else ""
            if header:
                lines.append(header + date_tag)
            elif date_tag:
                lines.append(date_tag.strip())
            lines += [f"{_inv_dot(v)} {k:<{label_w}}  {_fmt(v):>{val_w}}" for k, v in items]
        if not lines:
            return None
        return "```\n" + "\n".join(lines) + "\n```"

    def _market_section() -> str:
        """환율 + 원자재·코인 통합, raw price 기준 내림차순."""
        usdkrw_price = (yf.get("USDKRW=X") or {}).get("price") or 0

        def _raw(sym: str) -> float:
            d = yf.get(sym)
            return d["price"] if d else 0.0

        # (name, price_str, pct, raw_price, mcap_str)
        entries: list[tuple] = []

        # 환율 항목
        entries.append((*yf_row("USDKRW=X", "USD/KRW", ",.1f"),  _raw("USDKRW=X"), ""))
        entries.append((*krw_coin_row("USDT-USD", "USDT/KRW"),    _raw("USDT-USD") * usdkrw_price, ""))
        # JPY100
        d_jpy = yf.get("JPYKRW=X")
        jpy_raw = d_jpy["price"] * 100 if d_jpy else 0.0
        entries.append((*jpy_row(), jpy_raw, ""))
        entries.append((*yf_row("CNYKRW=X", "CNY/KRW", ",.2f"),  _raw("CNYKRW=X"), ""))
        entries.append((*yf_row("DX-Y.NYB", "DXY",     ",.2f"),  _raw("DX-Y.NYB"), ""))

        # 원자재·코인
        entries.append((*yf_row("BTC-USD", "BTC(USD)"), _raw("BTC-USD"), _mcap_tag("BTC-USD")))
        entries.append((*yf_row("ETH-USD", "ETH(USD)"), _raw("ETH-USD"), _mcap_tag("ETH-USD")))
        entries.append((*yf_row("CL=F",    "WTI", ",.2f"), _raw("CL=F"), ""))

        # raw price 내림차순 정렬
        entries.sort(key=lambda e: e[3], reverse=True)

        # _code_section 형식으로 변환 (name, price_str, pct, mcap_str)
        rows = [(e[0], e[1], e[2], e[4]) for e in entries]
        return _code_section(rows, dot_fn=_dot)

    inv_section = _investor_section()
    nf_row      = _night_futures_row()

    parts = [
        f"📊 **시황 브리핑** — {label}",
        f"📅 {ts} KST",
        "",
        "**🏦 기준금리**",
        _rates_section(),
        "",
        "**📈 증시**",
        _index_section(),
    ]
    if nf_row:
        parts += ["", "**🌙 KOSPI 야간선물**", nf_row]
    if inv_section:
        parts += ["", "**👥 투자자별 순매수 (KOSPI)**", inv_section]
    parts += [
        "",
        "**💱 환율 · 원자재 · 코인**",
        _market_section(),
    ]
    return "\n".join(parts)
