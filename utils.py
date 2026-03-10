import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import aiohttp
from icalendar import Calendar

from config import (
    F1_ICS_URL,
    GUILD_SETTINGS_PATH,
    ICS_CACHE_TTL,
    KST,
    LINEUP_PATH,
    RESULT_PATH,
    SF_MATCH_CACHE_TTL,
    SOFASCORE_HEADERS,
    SPURS_ICS_URL,
    SPURS_SOFASCORE_TEAM_ID,
    STATE_CLEANUP_DAYS,
    STATE_PATH,
    SUB_PATH,
)

# =========================================================
# IN-MEMORY CACHES
# =========================================================
_ics_cache: dict[str, tuple[bytes, float]] = {}
_sf_match_cache: dict[str, tuple[dict | None, float]] = {}
_ISO_RE = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)?')

# =========================================================
# JSON HELPERS
# =========================================================
def ensure_json_files():
    for path, default in [
        (STATE_PATH, {}),
        (SUB_PATH, {"users": {}}),
        (GUILD_SETTINGS_PATH, {}),
        (LINEUP_PATH, {}),
        (RESULT_PATH, {}),
    ]:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=2)

def _load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_state():        return _load_json(STATE_PATH, {})
def save_state(s):       _save_json(STATE_PATH, s)
def load_lineup_state(): return _load_json(LINEUP_PATH, {})
def save_lineup_state(s):_save_json(LINEUP_PATH, s)
def load_result_state(): return _load_json(RESULT_PATH, {})
def save_result_state(s):_save_json(RESULT_PATH, s)

def load_guild_settings():    return _load_json(GUILD_SETTINGS_PATH, {})
def save_guild_settings(data):_save_json(GUILD_SETTINGS_PATH, data)

def set_guild_channel(guild_id: int, channel_id: int):
    data = load_guild_settings()
    data[str(guild_id)] = {"channel_id": channel_id}
    save_guild_settings(data)

def get_guild_channel_id(guild_id: int):
    return load_guild_settings().get(str(guild_id), {}).get("channel_id")

# =========================================================
# SUBSCRIBER HELPERS (구독 모드: all / spurs / f1)
# =========================================================
def load_subscribers() -> dict:
    data = _load_json(SUB_PATH, {"users": {}})
    # 구버전 list 포맷 자동 마이그레이션
    if isinstance(data.get("users"), list):
        data["users"] = {str(uid): "all" for uid in data["users"]}
        _save_json(SUB_PATH, data)
    return data

def save_subscribers(data):
    _save_json(SUB_PATH, data)

def add_subscriber(user_id: int, mode: str = "all"):
    data = load_subscribers()
    data["users"][str(user_id)] = mode
    save_subscribers(data)

def remove_subscriber(user_id: int):
    data = load_subscribers()
    data["users"].pop(str(user_id), None)
    save_subscribers(data)

def get_subscribers_for_source(source: str) -> list[int]:
    """source: 'spurs' or 'f1' — 해당 종목 구독 유저 ID 목록."""
    users = load_subscribers().get("users", {})
    return [
        int(uid_str)
        for uid_str, mode in users.items()
        if mode == "all" or mode == source
    ]

def get_subscriber_mode(user_id: int) -> str | None:
    """현재 구독 모드 반환. 미구독이면 None."""
    return load_subscribers().get("users", {}).get(str(user_id))

# =========================================================
# STATE CLEANUP
# =========================================================
def cleanup_old_state(state: dict, days: int = STATE_CLEANUP_DAYS) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = {}
    for k, v in state.items():
        m = _ISO_RE.search(k)
        if not m:
            result[k] = v
            continue
        try:
            dt = datetime.fromisoformat(m.group())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt > cutoff:
                result[k] = v
        except ValueError:
            result[k] = v
    return result

# =========================================================
# ICS / EVENT HELPERS
# =========================================================
def make_key(source: str, uid: str, start_iso: str, kind: str) -> str:
    return f"{source}:{uid}:{start_iso}:{kind}"

async def fetch_ics_bytes(url: str) -> bytes:
    timeout = aiohttp.ClientTimeout(total=40)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as r:
            r.raise_for_status()
            return await r.read()

async def fetch_ics_bytes_cached(url: str) -> bytes:
    now = time.monotonic()
    cached = _ics_cache.get(url)
    if cached and now - cached[1] < ICS_CACHE_TTL:
        return cached[0]
    data = await fetch_ics_bytes(url)
    _ics_cache[url] = (data, now)
    return data

def parse_events(ics_bytes: bytes) -> list:
    cal = Calendar.from_ical(ics_bytes)
    events = []
    for c in cal.walk():
        if c.name != "VEVENT":
            continue
        summary = str(c.get("SUMMARY", "")).strip()
        uid = str(c.get("UID", "")).strip() or summary
        dtstart = c.get("DTSTART")
        if not dtstart:
            continue
        start = dtstart.dt
        if not isinstance(start, datetime):
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        events.append({
            "uid": uid,
            "summary": summary,
            "start_kst": start.astimezone(KST),
        })
    return events

def find_next_event(events) -> dict | None:
    now = datetime.now(KST)
    future = sorted([e for e in events if e["start_kst"] > now], key=lambda x: x["start_kst"])
    return future[0] if future else None

def find_next_n_events(events, n: int = 3) -> list:
    now = datetime.now(KST)
    future = sorted([e for e in events if e["start_kst"] > now], key=lambda x: x["start_kst"])
    return future[:n]

def find_recent_spurs_match(events) -> dict | None:
    """킥오프가 지났지만 3시간 이내인 경기 반환."""
    now = datetime.now(KST)
    window = now - timedelta(hours=3)
    recent = sorted(
        [e for e in events if window <= e["start_kst"] <= now],
        key=lambda x: x["start_kst"],
        reverse=True,
    )
    return recent[0] if recent else None

def f1_session_label(summary: str) -> str:
    s = summary.lower()
    if "sprint shootout" in s or "sprint qualifying" in s:
        return "🏎 F1 스프린트 예선"
    if "sprint" in s:
        return "🏎 F1 스프린트"
    if "practice 1" in s or "fp1" in s:
        return "🏎 F1 프리 프랙티스 1"
    if "practice 2" in s or "fp2" in s:
        return "🏎 F1 프리 프랙티스 2"
    if "practice 3" in s or "fp3" in s:
        return "🏎 F1 프리 프랙티스 3"
    if "qualifying" in s or "qualify" in s:
        return "🏎 F1 예선"
    if "race" in s:
        return "🏎 F1 본경기"
    return "🏎 F1"

def f1_session_short(summary: str) -> str:
    """bbf1용 짧은 세션 이름."""
    s = summary.lower()
    if "sprint shootout" in s or "sprint qualifying" in s:
        return "스프린트 예선"
    if "sprint" in s:
        return "스프린트"
    if "practice 1" in s or "fp1" in s:
        return "FP1"
    if "practice 2" in s or "fp2" in s:
        return "FP2"
    if "practice 3" in s or "fp3" in s:
        return "FP3"
    if "qualifying" in s or "qualify" in s:
        return "예선"
    if "race" in s:
        return "본경기"
    return summary.split(" - ")[-1].strip() if " - " in summary else summary

def f1_gp_name(summary: str) -> str:
    """ICS 이벤트 이름에서 GP 이름 추출 (세션 이름 제거)."""
    if " - " in summary:
        return summary.split(" - ")[0].strip()
    return summary

def find_next_gp_sessions(events) -> tuple[str, list] | tuple[None, None]:
    """다음 GP 이름과 해당 GP의 모든 세션(정렬됨) 반환."""
    now = datetime.now(KST)
    groups: dict[str, list] = {}
    for ev in events:
        gp = f1_gp_name(ev["summary"])
        groups.setdefault(gp, []).append(ev)

    upcoming: dict[str, list] = {}
    for gp, sessions in groups.items():
        future = [s for s in sessions if s["start_kst"] > now - timedelta(hours=3)]
        if future:
            upcoming[gp] = sorted(sessions, key=lambda x: x["start_kst"])

    if not upcoming:
        return None, None

    def earliest(gp):
        return min(s["start_kst"] for s in upcoming[gp] if s["start_kst"] > now - timedelta(hours=3))

    next_gp = min(upcoming, key=earliest)
    return next_gp, upcoming[next_gp]

_TEAM_SHORT = {
    "atletico madrid": "Atletico",
    "manchester city": "Man City",
    "manchester united": "Man Utd",
    "newcastle united": "Newcastle",
    "nottingham forest": "Nott'm F",
    "west ham united": "West Ham",
    "sheffield united": "Sheffield",
    "brighton & hove albion": "Brighton",
    "brighton and hove albion": "Brighton",
    "wolverhampton wanderers": "Wolves",
    "bayer leverkusen": "Leverkusen",
    "borussia dortmund": "Dortmund",
    "real madrid": "R. Madrid",
    "barcelona": "Barcelona",
    "inter milan": "Inter",
    "ac milan": "AC Milan",
    "paris saint-germain": "PSG",
    "paris saint germain": "PSG",
}

def _shorten_team(name: str) -> str:
    return _TEAM_SHORT.get(name.lower(), name)

def _extract_opponent(summary: str) -> str:
    """ICS 이벤트 이름에서 상대팀 이름만 추출."""
    spurs_kw = ["tottenham", "spurs"]
    clean = summary.strip().lstrip("⚽️🏆🎯🏴󠁧󠁢󠁥󠁮󠁧󠁿 ")
    for sep in [" vs ", " v ", " VS ", " V ", " - "]:
        if sep in clean:
            parts = clean.split(sep, 1)
            left, right = parts[0].strip(), parts[1].strip()
            opp = right if any(k in left.lower() for k in spurs_kw) else left
            return _shorten_team(opp)
    return _shorten_team(clean)

def fmt_next(title: str, ev) -> str:
    t = ev["start_kst"].strftime("%Y-%m-%d (%a) %H:%M")
    return f"**{title} 다음 일정**\n**{ev['summary']}**\n시작: {t} (KST)"

def fmt_dm(prefix: str, title: str, ev) -> str:
    t = ev["start_kst"].strftime("%Y-%m-%d (%a) %H:%M")
    return f"{prefix}\n**{title}**\n**{ev['summary']}**\n시작: {t} (KST)"

def fmt_bbf1(gp_name: str, sessions: list) -> str:
    lines = ["🏎 **F1 다음 GP 일정**", "", f"**{gp_name}**", ""]
    for ev in sessions:
        t = ev["start_kst"].strftime("%m/%d (%a) %H:%M")
        label = f1_session_short(ev["summary"])
        lines.append(f"`{label:<8}` {t} KST")
    return "\n".join(lines)

# =========================================================
# SOFASCORE HELPERS
# =========================================================
async def fetch_sofascore(url: str) -> dict:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout, headers=SOFASCORE_HEADERS) as session:
        async with session.get(url) as r:
            r.raise_for_status()
            return await r.json()

async def find_sofascore_match(kickoff_kst: datetime) -> dict | None:
    """ICS kickoff 시간과 가장 근접한 Sofascore 이벤트를 반환. 과거 경기는 last도 검색."""
    now = datetime.now(KST)
    urls = [f"https://api.sofascore.com/api/v1/team/{SPURS_SOFASCORE_TEAM_ID}/events/next/0"]
    if kickoff_kst <= now + timedelta(hours=1):
        urls.append(f"https://api.sofascore.com/api/v1/team/{SPURS_SOFASCORE_TEAM_ID}/events/last/0")

    all_events = []
    seen_ids: set[int] = set()
    for url in urls:
        try:
            data = await fetch_sofascore(url)
            for ev in data.get("events", []):
                if ev.get("id") not in seen_ids:
                    seen_ids.add(ev["id"])
                    all_events.append(ev)
        except Exception as e:
            print(f"sofascore fetch 실패 ({url}):", type(e).__name__, e)

    best = None
    best_diff = float("inf")
    for ev in all_events:
        ts = ev.get("startTimestamp")
        if not ts:
            continue
        ev_dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(KST)
        diff = abs((ev_dt - kickoff_kst).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best = ev

    return best if (best and best_diff <= 1800) else None

async def find_sofascore_match_cached(kickoff_kst: datetime) -> dict | None:
    key = kickoff_kst.isoformat()
    now = time.monotonic()
    cached = _sf_match_cache.get(key)
    if cached and now - cached[1] < SF_MATCH_CACHE_TTL:
        return cached[0]
    ev = await find_sofascore_match(kickoff_kst)
    _sf_match_cache[key] = (ev, now)
    return ev

async def fetch_sofascore_lineups(event_id: int) -> dict:
    return await fetch_sofascore(f"https://api.sofascore.com/api/v1/event/{event_id}/lineups")

async def fetch_sofascore_missing_players(event_id: int) -> dict:
    try:
        return await fetch_sofascore(f"https://api.sofascore.com/api/v1/event/{event_id}/missing-players")
    except Exception as e:
        print(f"missing-players fetch 실패 ({event_id}):", type(e).__name__, e)
        return {}

async def fetch_sofascore_event(event_id: int) -> dict:
    return await fetch_sofascore(f"https://api.sofascore.com/api/v1/event/{event_id}")

async def fetch_spurs_standings_position(event_data: dict) -> int | None:
    """현재 Tottenham 리그 순위 반환. 컵 대회 등 순위 없으면 None."""
    try:
        ev = event_data.get("event", {})
        ut_id = ev.get("tournament", {}).get("uniqueTournament", {}).get("id")
        season_id = ev.get("season", {}).get("id")
        if not ut_id or not season_id:
            return None
        data = await fetch_sofascore(
            f"https://api.sofascore.com/api/v1/unique-tournament/{ut_id}/season/{season_id}/standings/total"
        )
        for group in data.get("standings", []):
            for row in group.get("rows", []):
                if row.get("team", {}).get("id") == SPURS_SOFASCORE_TEAM_ID:
                    return row.get("position")
        return None
    except Exception as e:
        print("standings fetch 실패:", type(e).__name__, e)
        return None

def _player_name(p: dict) -> str:
    player = p.get("player", {})
    return player.get("shortName") or player.get("name") or "?"

def format_lineup_message(sf_event: dict, lineup_data: dict, missing_data: dict, is_home: bool) -> str:
    side = "home" if is_home else "away"
    home_name = sf_event.get("homeTeam", {}).get("name", "?")
    away_name = sf_event.get("awayTeam", {}).get("name", "?")
    ts = sf_event.get("startTimestamp", 0)
    kickoff_str = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(KST).strftime("%Y-%m-%d (%a) %H:%M")

    players = lineup_data.get(side, {}).get("players", [])
    starters = [p for p in players if not p.get("substitute", False)]
    subs = [p for p in players if p.get("substitute", False)]

    lines = [
        "⚽ **토트넘 오피셜 라인업**", "",
        f"**{home_name} vs {away_name}**",
        f"Kickoff: {kickoff_str} KST", "",
        "**Starting XI**",
    ]
    for p in starters:
        lines.append(_player_name(p))

    lines += ["", "**Substitutes**"]
    for p in subs:
        lines.append(_player_name(p))

    spurs_missing = []
    if isinstance(missing_data.get(side), list):
        spurs_missing = missing_data[side]
    elif isinstance(missing_data.get("missingPlayers"), dict):
        spurs_missing = missing_data["missingPlayers"].get(side, [])

    if spurs_missing:
        lines += ["", "**Unavailable**"]
        for m in spurs_missing:
            name = _player_name(m)
            reason = m.get("type", {}).get("name", "") or m.get("reason", "")
            lines.append(f"{name} ({reason})" if reason else name)

    return "\n".join(lines)

def format_result_message(event_data: dict, is_home: bool, standing: int | None, next_fixtures: list) -> str:
    ev = event_data.get("event", {})
    home_name = ev.get("homeTeam", {}).get("name", "?")
    away_name = ev.get("awayTeam", {}).get("name", "?")
    home_score = ev.get("homeScore", {}).get("current", 0)
    away_score = ev.get("awayScore", {}).get("current", 0)
    tournament = ev.get("tournament", {}).get("name", "?")

    spurs_score = home_score if is_home else away_score
    opp_score = away_score if is_home else home_score

    if spurs_score > opp_score:
        result_str = "승 ✅"
    elif spurs_score == opp_score:
        result_str = "무 🟡"
    else:
        result_str = "패 ❌"

    lines = [
        "📊 **경기 종료**", "",
        f"**{home_name} {home_score} - {away_score} {away_name}**",
        f"{tournament}", "",
        f"결과: {result_str}",
    ]
    if standing is not None:
        lines.append(f"현재 순위: **{standing}위**")

    if next_fixtures:
        lines += ["", "📅 **다음 일정**"]
        for i, fx in enumerate(next_fixtures, 1):
            t = fx["start_kst"].strftime("%m/%d (%a) %H:%M")
            lines.append(f"{i}. {fx['summary']} | {t} KST")

    return "\n".join(lines)
