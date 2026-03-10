import os
import re
import json
import time
import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import aiohttp
from icalendar import Calendar
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# =========================================================
# ENV
# =========================================================
load_dotenv("bss.env")

TOKEN = os.getenv("DISCORD_TOKEN")
SPURS_ICS_URL = os.getenv("SPURS_ICS_URL")
F1_ICS_URL = os.getenv("F1_ICS_URL")
GUILD_ID = os.getenv("GUILD_ID")

GUILD = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None
KST = ZoneInfo("Asia/Seoul")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN이 비어있음. bss.env 확인!")
if not SPURS_ICS_URL:
    raise RuntimeError("SPURS_ICS_URL이 비어있음. bss.env 확인!")
if not F1_ICS_URL:
    raise RuntimeError("F1_ICS_URL이 비어있음. bss.env 확인!")

# =========================================================
# CONSTANTS
# =========================================================
SPURS_SOFASCORE_TEAM_ID = 33

SOFASCORE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.sofascore.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Cache-Control": "no-cache",
}

ICS_CACHE_TTL = 240
SF_MATCH_CACHE_TTL = 240
STATE_CLEANUP_DAYS = 7

# =========================================================
# FILE PATHS
# =========================================================
STATE_PATH = "notified.json"
SUB_PATH = "subscribers.json"
GUILD_SETTINGS_PATH = "guild_settings.json"
LINEUP_PATH = "lineup_sent.json"
RESULT_PATH = "result_sent.json"

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

async def send_to_all_guild_channels(message: str):
    guild_settings = load_guild_settings()
    for guild_id_str, settings in guild_settings.items():
        ch_id = settings.get("channel_id")
        if not ch_id:
            continue
        try:
            ch = bot.get_channel(ch_id)
            if ch is None:
                ch = await bot.fetch_channel(ch_id)
            await ch.send(message)
        except Exception as e:
            print(f"채널 발송 실패 ({guild_id_str}):", type(e).__name__, e)

# =========================================================
# DISCORD BOT
# =========================================================
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================================================
# CHANNEL GUARD
# =========================================================
async def ensure_server_channel(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ 이 명령어는 서버 내 설정된 채널에서만 사용할 수 있어.", ephemeral=True
        )
        return False

    allowed_channel_id = get_guild_channel_id(interaction.guild.id)

    if not allowed_channel_id:
        await interaction.response.send_message(
            "⚠️ 이 서버는 아직 봇 채널이 설정되지 않았어.\n관리자가 사용할 채널에서 `/bbset` 먼저 실행해줘.",
            ephemeral=True
        )
        return False

    if interaction.channel_id != allowed_channel_id:
        ch = interaction.guild.get_channel(allowed_channel_id)
        mention = ch.mention if ch else f"<#{allowed_channel_id}>"
        await interaction.response.send_message(
            f"⚠️ 이 서버에서는 {mention} 채널에서만 봇을 사용할 수 있어.", ephemeral=True
        )
        return False

    return True

async def ensure_server_channel_or_dm(interaction: discord.Interaction) -> bool:
    if interaction.guild is None:
        return True
    return await ensure_server_channel(interaction)

# =========================================================
# READY / SYNC
# =========================================================
@bot.event
async def on_ready():
    try:
        ensure_json_files()

        for load_fn, save_fn in [
            (load_state, save_state),
            (load_lineup_state, save_lineup_state),
            (load_result_state, save_result_state),
        ]:
            cleaned = cleanup_old_state(load_fn())
            save_fn(cleaned)

        if GUILD:
            bot.tree.copy_global_to(guild=GUILD)
            synced = await bot.tree.sync(guild=GUILD)
            print("guild sync:", [c.name for c in synced])
        else:
            synced = await bot.tree.sync()
            print("global sync:", [c.name for c in synced])

        print(f"로그인 완료: {bot.user}")

        if not hasattr(bot, "_notifier_started"):
            bot._notifier_started = True
            bot.loop.create_task(notify_loop())

        if not hasattr(bot, "_lineup_started"):
            bot._lineup_started = True
            bot.loop.create_task(lineup_loop())

        if not hasattr(bot, "_result_started"):
            bot._result_started = True
            bot.loop.create_task(result_loop())

    except Exception as e:
        print("on_ready error:", type(e).__name__, e)

# =========================================================
# SLASH COMMANDS
# =========================================================
@app_commands.default_permissions(administrator=True)
@bot.tree.command(name="bbset", description="이 채널을 이 서버의 봇 전용 채널로 설정합니다")
async def bbset(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message("❌ `/bbset`은 서버 채널에서만 사용할 수 있어.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ 이 명령어는 관리자만 사용할 수 있어.", ephemeral=True)
        return

    set_guild_channel(interaction.guild.id, interaction.channel_id)
    await interaction.response.send_message(
        f"✅ 이 채널을 봇 전용 채널로 설정했어.\n이제 이 서버에서는 {interaction.channel.mention} 에서만 명령어가 동작해."
    )

@bot.tree.command(name="bbtime", description="토트넘 / F1 가장 가까운 일정을 보여줍니다")
async def bbtime(interaction: discord.Interaction):
    if not await ensure_server_channel(interaction):
        return
    try:
        await interaction.response.defer(thinking=True)

        spurs_bytes = await fetch_ics_bytes_cached(SPURS_ICS_URL)
        f1_bytes = await fetch_ics_bytes_cached(F1_ICS_URL)

        spurs_ev = find_next_event(parse_events(spurs_bytes))
        f1_ev = find_next_event(parse_events(f1_bytes))

        msgs = []
        if spurs_ev:
            msgs.append(fmt_next("⚽ 토트넘", spurs_ev))
        if f1_ev:
            msgs.append(fmt_next(f1_session_label(f1_ev["summary"]), f1_ev))

        await interaction.followup.send("\n\n".join(msgs) if msgs else "다음 일정이 없습니다.")

    except Exception as e:
        msg = f"에러: {type(e).__name__}: {e}"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except:
            pass

@bot.tree.command(name="bbf1", description="F1 다음 GP의 전체 세션 일정을 보여줍니다")
async def bbf1(interaction: discord.Interaction):
    if not await ensure_server_channel(interaction):
        return
    try:
        await interaction.response.defer(thinking=True)

        f1_bytes = await fetch_ics_bytes_cached(F1_ICS_URL)
        gp_name, sessions = find_next_gp_sessions(parse_events(f1_bytes))

        if not gp_name:
            await interaction.followup.send("다음 F1 일정이 없습니다.")
            return

        await interaction.followup.send(fmt_bbf1(gp_name, sessions))

    except Exception as e:
        msg = f"에러: {type(e).__name__}: {e}"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except:
            pass

@bot.tree.command(name="bbup", description="경기 알림 DM 구독")
@app_commands.describe(종목="알림 받을 종목 선택 (기본: 전체)")
@app_commands.choices(종목=[
    app_commands.Choice(name="전체 (토트넘 + F1)", value="all"),
    app_commands.Choice(name="토트넘만", value="spurs"),
    app_commands.Choice(name="F1만", value="f1"),
])
async def bbup(interaction: discord.Interaction, 종목: app_commands.Choice[str] = None):
    if not await ensure_server_channel_or_dm(interaction):
        return

    mode = 종목.value if 종목 else "all"
    mode_labels = {"all": "토트넘 + F1 전체", "spurs": "토트넘만", "f1": "F1만"}

    add_subscriber(interaction.user.id, mode)
    await interaction.response.send_message(
        f"✅ 경기 알림 구독 완료 ({mode_labels[mode]})\n24시간 전 / 30분 전 / 10분 전에 DM 보내줄게.",
        ephemeral=True
    )

@bot.tree.command(name="bbdown", description="경기 알림 DM 구독 해제")
async def bbdown(interaction: discord.Interaction):
    if not await ensure_server_channel_or_dm(interaction):
        return
    remove_subscriber(interaction.user.id)
    await interaction.response.send_message("❌ 경기 알림 구독 해제 완료", ephemeral=True)

@bot.tree.command(name="bbtest", description="내 DM으로 테스트 메시지를 보냅니다")
async def bbtest(interaction: discord.Interaction):
    if not await ensure_server_channel_or_dm(interaction):
        return
    try:
        await interaction.user.send("📩 BBS 테스트 DM이야. DM 알림이 정상 작동 중이야.")
        await interaction.response.send_message("✅ DM 테스트 메시지를 보냈어. 개인 메시지함 확인해봐.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            "❌ DM을 보낼 수 없어. 디스코드 개인정보 설정에서 DM 허용을 확인해줘.", ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ DM 테스트 실패: {type(e).__name__}: {e}", ephemeral=True)

@bot.tree.command(name="bblast", description="토트넘 가장 최근 경기 결과를 보여줍니다")
async def bblast(interaction: discord.Interaction):
    if not await ensure_server_channel(interaction):
        return
    try:
        await interaction.response.defer(thinking=True)

        data = await fetch_sofascore(
            f"https://api.sofascore.com/api/v1/team/{SPURS_SOFASCORE_TEAM_ID}/events/last/0"
        )
        events = data.get("events", [])

        # 완료된 경기 중 가장 최근 것
        finished = [
            ev for ev in events
            if ev.get("status", {}).get("type") == "finished"
        ]
        if not finished:
            await interaction.followup.send("최근 경기 데이터를 찾을 수 없어.")
            return

        ev = max(finished, key=lambda x: x.get("startTimestamp", 0))
        is_home = ev.get("homeTeam", {}).get("id") == SPURS_SOFASCORE_TEAM_ID

        home_name  = ev.get("homeTeam", {}).get("name", "?")
        away_name  = ev.get("awayTeam", {}).get("name", "?")
        home_score = ev.get("homeScore", {}).get("current", 0)
        away_score = ev.get("awayScore", {}).get("current", 0)
        tournament = ev.get("tournament", {}).get("name", "?")

        ts = ev.get("startTimestamp", 0)
        match_date = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(KST).strftime("%Y-%m-%d (%a) %H:%M")

        spurs_score = home_score if is_home else away_score
        opp_score   = away_score if is_home else home_score

        if spurs_score > opp_score:
            result_str = "승 ✅"
        elif spurs_score == opp_score:
            result_str = "무 🟡"
        else:
            result_str = "패 ❌"

        msg = (
            f"📊 **토트넘 최근 경기**\n"
            f"\n"
            f"**{home_name} {home_score} - {away_score} {away_name}**\n"
            f"{tournament} | {match_date} KST\n"
            f"\n"
            f"결과: {result_str}"
        )
        await interaction.followup.send(msg)

    except Exception as e:
        msg = f"에러: {type(e).__name__}: {e}"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except:
            pass


@bot.tree.command(name="bbhelp", description="사용 가능한 모든 명령어를 보여줍니다")
async def bbhelp(interaction: discord.Interaction):
    if not await ensure_server_channel_or_dm(interaction):
        return

    mode = get_subscriber_mode(interaction.user.id)
    mode_labels = {"all": "토트넘 + F1 전체", "spurs": "토트넘만", "f1": "F1만"}
    sub_status = f"구독 중 ({mode_labels.get(mode, mode)})" if mode else "미구독"

    msg = (
        "**📋 BBS 봇 명령어 목록**\n"
        "\n"
        "**일정**\n"
        "`/bbtime` — 토트넘 / F1 다음 일정 1개씩\n"
        "`/bbf1` — F1 다음 GP 전체 세션 일정\n"
        "`/bblast` — 토트넘 최근 경기 결과\n"
        "\n"
        "**알림 구독 (DM)**\n"
        "`/bbup [종목]` — 경기 알림 구독 (전체 / 토트넘만 / F1만)\n"
        "`/bbdown` — 구독 해제\n"
        "`/bbtest` — DM 수신 테스트\n"
        "\n"
        "**서버 설정 (관리자 전용)**\n"
        "`/bbset` — 현재 채널을 봇 전용 채널로 설정\n"
        "\n"
        "**자동 알림 (채널)**\n"
        "⚽ 토트넘 오피셜 라인업 — 킥오프 75분 전부터 자동 감지\n"
        "📊 경기 결과 + 다음 3경기 — 경기 종료 후 자동 발송\n"
        "\n"
        f"내 구독 상태: **{sub_status}**"
    )
    await interaction.response.send_message(msg, ephemeral=True)

# =========================================================
# DM NOTIFY LOOP
# =========================================================
async def notify_loop():
    await bot.wait_until_ready()
    state = load_state()

    while not bot.is_closed():
        now = datetime.now(KST)

        try:
            spurs_ics = await fetch_ics_bytes_cached(SPURS_ICS_URL)
            f1_ics = await fetch_ics_bytes_cached(F1_ICS_URL)

            spurs_next = find_next_event(parse_events(spurs_ics))
            f1_next = find_next_event(parse_events(f1_ics))

            targets = []
            if spurs_next:
                targets.append(("spurs", "⚽ 토트넘", spurs_next))
            if f1_next:
                targets.append(("f1", f1_session_label(f1_next["summary"]), f1_next))

            for source, title, ev in targets:
                start = ev["start_kst"]
                start_iso = start.isoformat()

                d1  = start - timedelta(hours=24)
                m30 = start - timedelta(minutes=30)
                m10 = start - timedelta(minutes=10)

                def within(target_time):
                    return target_time <= now <= (target_time + timedelta(minutes=10))

                async def lineup_suffix_for_spurs(kickoff=start, src=source) -> str:
                    if src != "spurs":
                        return ""
                    try:
                        sf_event = await find_sofascore_match_cached(kickoff)
                        if not sf_event:
                            return ""
                        event_id = sf_event["id"]
                        is_home = sf_event.get("homeTeam", {}).get("id") == SPURS_SOFASCORE_TEAM_ID
                        lineup_data = await fetch_sofascore_lineups(event_id)
                        side = "home" if is_home else "away"
                        if not lineup_data.get(side, {}).get("confirmed", False):
                            return ""
                        missing_data = await fetch_sofascore_missing_players(event_id)
                        return "\n\n" + format_lineup_message(sf_event, lineup_data, missing_data, is_home)
                    except Exception as e:
                        print("lineup_suffix 실패:", type(e).__name__, e)
                        return ""

                if within(d1):
                    k = make_key(source, ev["uid"], start_iso, "d-1")
                    if not state.get(k):
                        for uid in get_subscribers_for_source(source):
                            try:
                                user = await bot.fetch_user(uid)
                                await user.send(fmt_dm("⏰ D-1 알림", title, ev))
                            except Exception as e:
                                print(f"D-1 DM 실패 ({uid}):", type(e).__name__, e)
                        state[k] = True

                if within(m30):
                    k = make_key(source, ev["uid"], start_iso, "m-30")
                    if not state.get(k):
                        suffix = await lineup_suffix_for_spurs()
                        for uid in get_subscribers_for_source(source):
                            try:
                                user = await bot.fetch_user(uid)
                                await user.send(fmt_dm("🔥 30분 전 알림", title, ev) + suffix)
                            except Exception as e:
                                print(f"30분 전 DM 실패 ({uid}):", type(e).__name__, e)
                        state[k] = True

                if within(m10):
                    k = make_key(source, ev["uid"], start_iso, "m-10")
                    if not state.get(k):
                        suffix = await lineup_suffix_for_spurs()
                        for uid in get_subscribers_for_source(source):
                            try:
                                user = await bot.fetch_user(uid)
                                await user.send(fmt_dm("🚨 10분 전 알림", title, ev) + suffix)
                            except Exception as e:
                                print(f"10분 전 DM 실패 ({uid}):", type(e).__name__, e)
                        state[k] = True

            save_state(state)

        except Exception as e:
            print("notify_loop error:", type(e).__name__, e)

        await asyncio.sleep(300)

# =========================================================
# LINEUP LOOP
# =========================================================
async def lineup_loop():
    await bot.wait_until_ready()
    lineup_state = load_lineup_state()

    while not bot.is_closed():
        now = datetime.now(KST)

        try:
            spurs_ics = await fetch_ics_bytes_cached(SPURS_ICS_URL)
            spurs_next = find_next_event(parse_events(spurs_ics))

            if spurs_next:
                kickoff = spurs_next["start_kst"]
                diff_min = (kickoff - now).total_seconds() / 60
                state_key = f"spurs_lineup:{spurs_next['uid']}:{kickoff.isoformat()}"

                if -10 <= diff_min <= 75 and not lineup_state.get(state_key):
                    try:
                        sf_event = await find_sofascore_match_cached(kickoff)
                    except Exception as e:
                        print("sofascore match 조회 실패:", type(e).__name__, e)
                        sf_event = None

                    if sf_event:
                        event_id = sf_event["id"]
                        is_home = sf_event.get("homeTeam", {}).get("id") == SPURS_SOFASCORE_TEAM_ID

                        try:
                            lineup_data = await fetch_sofascore_lineups(event_id)
                        except Exception as e:
                            print("lineup fetch 실패:", type(e).__name__, e)
                            lineup_data = {}

                        side = "home" if is_home else "away"
                        if lineup_data.get(side, {}).get("confirmed", False):
                            missing_data = await fetch_sofascore_missing_players(event_id)
                            msg = format_lineup_message(sf_event, lineup_data, missing_data, is_home)
                            await send_to_all_guild_channels(msg)

                            lineup_state[state_key] = True
                            save_lineup_state(lineup_state)
                            print(f"라인업 알림 발송: {spurs_next['summary']}")

        except Exception as e:
            print("lineup_loop error:", type(e).__name__, e)

        await asyncio.sleep(300)

# =========================================================
# RESULT LOOP
# =========================================================
async def result_loop():
    await bot.wait_until_ready()
    result_state = load_result_state()

    while not bot.is_closed():
        try:
            spurs_ics = await fetch_ics_bytes_cached(SPURS_ICS_URL)
            spurs_events = parse_events(spurs_ics)
            recent_match = find_recent_spurs_match(spurs_events)

            if recent_match:
                kickoff = recent_match["start_kst"]
                state_key = f"spurs_result:{recent_match['uid']}:{kickoff.isoformat()}"

                if not result_state.get(state_key):
                    try:
                        sf_event = await find_sofascore_match(kickoff)  # 캐시 미사용 (진행 중 상태 최신값 필요)
                    except Exception as e:
                        print("result sofascore match 조회 실패:", type(e).__name__, e)
                        sf_event = None

                    if sf_event:
                        event_id = sf_event["id"]
                        is_home = sf_event.get("homeTeam", {}).get("id") == SPURS_SOFASCORE_TEAM_ID

                        try:
                            event_data = await fetch_sofascore_event(event_id)
                            status_type = event_data.get("event", {}).get("status", {}).get("type", "")

                            if status_type == "finished":
                                standing = await fetch_spurs_standings_position(event_data)
                                next_fixtures = find_next_n_events(spurs_events, 3)
                                msg = format_result_message(event_data, is_home, standing, next_fixtures)

                                await send_to_all_guild_channels(msg)

                                for uid in get_subscribers_for_source("spurs"):
                                    try:
                                        user = await bot.fetch_user(uid)
                                        await user.send(msg)
                                    except Exception as e:
                                        print(f"result DM 실패 ({uid}):", type(e).__name__, e)

                                result_state[state_key] = True
                                save_result_state(result_state)
                                print(f"결과 알림 발송: {recent_match['summary']}")

                        except Exception as e:
                            print("result status 확인 실패:", type(e).__name__, e)

        except Exception as e:
            print("result_loop error:", type(e).__name__, e)

        await asyncio.sleep(300)

# =========================================================
# RUN
# =========================================================
bot.run(TOKEN)
