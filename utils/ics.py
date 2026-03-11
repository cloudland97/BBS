import time
from datetime import datetime, timedelta, timezone

import aiohttp
from icalendar import Calendar

from config import ICS_CACHE_TTL, KST

_ics_cache: dict[str, tuple[bytes, float]] = {}

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


# ── F1 헬퍼 ───────────────────────────────────────────────
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
    if " - " in summary:
        return summary.split(" - ")[0].strip()
    return summary


def find_next_gp_sessions(events) -> tuple[str, list] | tuple[None, None]:
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

    return min(upcoming, key=earliest), upcoming[min(upcoming, key=earliest)]


# ── 팀명 / 상대 추출 ───────────────────────────────────────
def _shorten_team(name: str) -> str:
    return _TEAM_SHORT.get(name.lower(), name)


def _extract_opponent(summary: str) -> str:
    spurs_kw = ["tottenham", "spurs"]
    clean = summary.strip().lstrip("⚽️🏆🎯🏴󠁧󠁢󠁥󠁮󠁧󠁿 ")
    for sep in [" vs ", " v ", " VS ", " V ", " - "]:
        if sep in clean:
            parts = clean.split(sep, 1)
            left, right = parts[0].strip(), parts[1].strip()
            opp = right if any(k in left.lower() for k in spurs_kw) else left
            return _shorten_team(opp)
    return _shorten_team(clean)


# ── DM / 커맨드 포맷 ───────────────────────────────────────
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
