import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import aiohttp

from config import (
    FOOTBALL_DATA_BASE,
    FOOTBALL_DATA_TEAM_ID,
    FOOTBALL_DATA_TOKEN,
    FD_MATCH_CACHE_TTL,
    LEAGUE_COMPETITION_CODES,
)

logger = logging.getLogger(__name__)

# ── 인메모리 캐시 ──────────────────────────────────────────
_fd_match_cache: dict[str, tuple[dict | None, float]] = {}
_recent_matches_cache: tuple[list, float] | None = None
_h2h_cache: dict[int, tuple[dict, float]] = {}
_standings_cache: dict[str, tuple[list, float]] = {}

RECENT_MATCHES_TTL = 600   # 10분
H2H_TTL = 3600             # 1시간
STANDINGS_TTL = 600        # 10분


async def fetch_football_data(url: str, retries: int = 2, session: aiohttp.ClientSession | None = None) -> dict:
    """football-data.org API 호출. 실패 시 최대 retries회 재시도 (지수 백오프)."""
    timeout = aiohttp.ClientTimeout(total=15)
    headers = {"X-Auth-Token": FOOTBALL_DATA_TOKEN}
    last_error: Exception = RuntimeError("요청 실패")

    for attempt in range(retries + 1):
        try:
            if session is not None:
                async with session.get(url, headers=headers) as r:
                    r.raise_for_status()
                    return await r.json()
            else:
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as s:
                    async with s.get(url) as r:
                        r.raise_for_status()
                        return await r.json()
        except Exception as e:
            last_error = e
            if attempt < retries:
                wait = 2 ** attempt  # 1초 → 2초
                logger.warning("API 재시도 %d/%d (%s): %s", attempt + 1, retries, url, e)
                await asyncio.sleep(wait)

    raise last_error


async def find_fd_match(kickoff_kst: datetime) -> dict | None:
    """football-data.org에서 킥오프 시간에 가장 근접한 토트넘 경기를 반환."""
    kickoff_utc = kickoff_kst.astimezone(timezone.utc)
    from_date = (kickoff_utc - timedelta(days=1)).strftime("%Y-%m-%d")
    to_date = (kickoff_utc + timedelta(days=1)).strftime("%Y-%m-%d")
    url = f"{FOOTBALL_DATA_BASE}/teams/{FOOTBALL_DATA_TEAM_ID}/matches?dateFrom={from_date}&dateTo={to_date}"
    try:
        data = await fetch_football_data(url)
        matches = data.get("matches", [])
        best, best_diff = None, float("inf")
        for match in matches:
            utc_date = match.get("utcDate", "")
            if not utc_date:
                continue
            match_dt = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
            diff = abs((match_dt - kickoff_utc).total_seconds())
            if diff < best_diff:
                best_diff = diff
                best = match
        return best if (best and best_diff <= 3600) else None
    except Exception as e:
        logger.warning("football-data match 조회 실패: %s %s", type(e).__name__, e)
        return None


async def find_fd_match_cached(kickoff_kst: datetime) -> dict | None:
    key = kickoff_kst.isoformat()
    now = time.monotonic()
    cached = _fd_match_cache.get(key)
    if cached and now - cached[1] < FD_MATCH_CACHE_TTL:
        return cached[0]
    match = await find_fd_match(kickoff_kst)
    _fd_match_cache[key] = (match, now)
    return match


async def fetch_fd_match(match_id: int) -> dict:
    """경기 상세 정보 (상태, 스코어, 득점자 포함). 캐시 미사용 — 진행 중 경기 최신값 필요."""
    return await fetch_football_data(f"{FOOTBALL_DATA_BASE}/matches/{match_id}")


async def fetch_fd_lineups(match_id: int) -> dict:
    try:
        return await fetch_football_data(f"{FOOTBALL_DATA_BASE}/matches/{match_id}/lineups")
    except Exception as e:
        logger.warning("lineup fetch 실패 (%s): %s %s", match_id, type(e).__name__, e)
        return {}


async def fetch_fd_h2h(match_id: int) -> dict:
    """두 팀 간 상대 전적 조회. 1시간 캐시."""
    now = time.monotonic()
    cached = _h2h_cache.get(match_id)
    if cached and now - cached[1] < H2H_TTL:
        return cached[0]
    try:
        data = await fetch_football_data(f"{FOOTBALL_DATA_BASE}/matches/{match_id}/head2head")
        _h2h_cache[match_id] = (data, now)
        return data
    except Exception as e:
        logger.warning("h2h fetch 실패 (%s): %s %s", match_id, type(e).__name__, e)
        return {}


async def fetch_spurs_recent_matches(n: int = 5) -> list[dict]:
    """최근 완료된 토트넘 경기 목록 반환 (최신순). 10분 캐시."""
    global _recent_matches_cache
    now = time.monotonic()
    if _recent_matches_cache and now - _recent_matches_cache[1] < RECENT_MATCHES_TTL:
        return _recent_matches_cache[0][:n]
    try:
        today = datetime.now(timezone.utc)
        from_date = (today - timedelta(days=90)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")
        url = f"{FOOTBALL_DATA_BASE}/teams/{FOOTBALL_DATA_TEAM_ID}/matches?status=FINISHED&dateFrom={from_date}&dateTo={to_date}"
        data = await fetch_football_data(url)
        matches = data.get("matches", [])
        matches.sort(key=lambda m: m.get("utcDate", ""), reverse=True)
        _recent_matches_cache = (matches, now)
        return matches[:n]
    except Exception as e:
        logger.warning("recent matches fetch 실패: %s %s", type(e).__name__, e)
        return []



async def _fetch_competition_table(competition_code: str) -> list:
    """TOTAL 타입 순위표 반환. 10분 캐시."""
    now = time.monotonic()
    cached = _standings_cache.get(competition_code)
    if cached and now - cached[1] < STANDINGS_TTL:
        return cached[0]
    try:
        data = await fetch_football_data(
            f"{FOOTBALL_DATA_BASE}/competitions/{competition_code}/standings"
        )
        for group in data.get("standings", []):
            if group.get("type") == "TOTAL":
                table = group.get("table", [])
                _standings_cache[competition_code] = (table, now)
                return table
        return []
    except Exception as e:
        logger.warning("standings table fetch 실패 (%s): %s %s", competition_code, type(e).__name__, e)
        return []


async def fetch_opponent_standing(match: dict) -> dict | None:
    """상대팀 순위 행 반환. 컵대회 또는 조회 실패 시 None."""
    competition_code = match.get("competition", {}).get("code", "")
    if competition_code not in LEAGUE_COMPETITION_CODES:
        return None
    is_home = match.get("homeTeam", {}).get("id") == FOOTBALL_DATA_TEAM_ID
    opponent_id = match.get("awayTeam", {}).get("id") if is_home else match.get("homeTeam", {}).get("id")
    if not opponent_id:
        return None
    table = await _fetch_competition_table(competition_code)
    for row in table:
        if row.get("team", {}).get("id") == opponent_id:
            return row
    return None


async def fetch_standings_mini(match: dict, n: int = 3) -> tuple[list, int | None]:
    """토트넘 기준 ±n 구간 순위표 행 목록 + 토트넘 순위 반환. 컵대회는 ([], None)."""
    competition_code = match.get("competition", {}).get("code", "")
    if competition_code not in LEAGUE_COMPETITION_CODES:
        return [], None
    table = await _fetch_competition_table(competition_code)
    if not table:
        return [], None
    spurs_pos = None
    for row in table:
        if row.get("team", {}).get("id") == FOOTBALL_DATA_TEAM_ID:
            spurs_pos = row.get("position")
            break
    if spurs_pos is None:
        return [], None
    start = max(0, spurs_pos - 1 - n)      # position은 1-based
    end = min(len(table), spurs_pos + n)
    return table[start:end], spurs_pos
