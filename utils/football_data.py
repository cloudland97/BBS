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

RECENT_MATCHES_TTL = 600   # 10분 (경기 끝나야 바뀜)
H2H_TTL = 3600             # 1시간 (시즌 중 천천히 변함)


async def fetch_football_data(url: str) -> dict:
    timeout = aiohttp.ClientTimeout(total=15)
    headers = {"X-Auth-Token": FOOTBALL_DATA_TOKEN}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(url) as r:
            r.raise_for_status()
            return await r.json()


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
    global _h2h_cache
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


async def fetch_spurs_standings_position(match: dict) -> int | None:
    """football-data.org에서 토트넘 리그 순위 반환. 컵 대회는 None."""
    try:
        competition_code = match.get("competition", {}).get("code", "")
        if competition_code not in LEAGUE_COMPETITION_CODES:
            return None
        data = await fetch_football_data(
            f"{FOOTBALL_DATA_BASE}/competitions/{competition_code}/standings"
        )
        for group in data.get("standings", []):
            if group.get("type") != "TOTAL":
                continue
            for row in group.get("table", []):
                if row.get("team", {}).get("id") == FOOTBALL_DATA_TEAM_ID:
                    return row.get("position")
        return None
    except Exception as e:
        logger.warning("standings fetch 실패: %s %s", type(e).__name__, e)
        return None
