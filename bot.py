import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

import commands as bot_commands
from config import F1_ICS_URL, FOOTBALL_DATA_TEAM_ID, GUILD, SPURS_ICS_URL, TOKEN, KST
from utils import (
    cleanup_old_state,
    ensure_json_files,
    fetch_fd_h2h,
    fetch_fd_lineups,
    fetch_fd_match,
    fetch_ics_bytes_cached,
    fetch_spurs_standings_position,
    find_fd_match,
    find_fd_match_cached,
    find_next_event,
    find_next_n_events,
    find_recent_spurs_match,
    fmt_dm,
    f1_session_label,
    f1_session_short,
    format_h2h_message,
    format_lineup_message,
    format_result_message,
    get_guild_channel_id,
    get_subscribers_for_source,
    load_guild_settings,
    load_lineup_state,
    load_result_state,
    load_state,
    make_key,
    parse_events,
    save_lineup_state,
    save_result_state,
    save_state,
    _extract_opponent,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# =========================================================
# DISCORD BOT
# =========================================================
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

bot_commands.setup(bot)


# =========================================================
# HELPERS THAT NEED bot INSTANCE
# =========================================================
async def update_presence():
    """봇 상태를 다음 F1 + 다음 토트넘 일정으로 업데이트."""
    try:
        parts = []

        try:
            spurs_ics = await fetch_ics_bytes_cached(SPURS_ICS_URL)
            spurs_next = find_next_event(parse_events(spurs_ics))
            if spurs_next:
                t = spurs_next["start_kst"].strftime("%m/%d %H:%M")
                opp = _extract_opponent(spurs_next["summary"])
                parts.append(f"vs {opp} {t}")
        except Exception as e:
            logger.warning("presence Spurs 조회 실패: %s %s", type(e).__name__, e)

        try:
            f1_ics = await fetch_ics_bytes_cached(F1_ICS_URL)
            f1_next = find_next_event(parse_events(f1_ics))
            if f1_next:
                t = f1_next["start_kst"].strftime("%m/%d %H:%M")
                label = f1_session_short(f1_next["summary"])
                parts.append(f"{label} {t}")
        except Exception as e:
            logger.warning("presence F1 조회 실패: %s %s", type(e).__name__, e)

        status_text = " | ".join(parts) if parts else "토트넘 알림봇"
        await bot.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name=status_text)
        )
        logger.info("presence 업데이트: %s", status_text)

    except Exception as e:
        logger.error("update_presence 실패: %s %s", type(e).__name__, e)


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
            logger.warning("채널 발송 실패 (%s): %s %s", guild_id_str, type(e).__name__, e)


async def _lineup_suffix(kickoff: datetime, source: str) -> str:
    """DM 알림용 단축 라인업. 라인업 미확정이면 빈 문자열 반환."""
    if source != "spurs":
        return ""
    try:
        fd_match = await find_fd_match_cached(kickoff)
        if not fd_match:
            return ""
        match_id = fd_match["id"]
        is_home = fd_match.get("homeTeam", {}).get("id") == FOOTBALL_DATA_TEAM_ID
        lineup_data = await fetch_fd_lineups(match_id)
        side = "homeTeam" if is_home else "awayTeam"
        if not lineup_data.get(side, {}).get("startingXI"):
            return ""
        return "\n\n" + format_lineup_message(fd_match, lineup_data, is_home)
    except Exception as e:
        logger.warning("lineup_suffix 실패: %s %s", type(e).__name__, e)
        return ""


async def _h2h_suffix(kickoff: datetime, source: str) -> str:
    """D-1 DM 알림용 상대 전적. 조회 실패 시 빈 문자열 반환."""
    if source != "spurs":
        return ""
    try:
        fd_match = await find_fd_match_cached(kickoff)
        if not fd_match:
            return ""
        h2h_data = await fetch_fd_h2h(fd_match["id"])
        return format_h2h_message(h2h_data)
    except Exception as e:
        logger.warning("h2h_suffix 실패: %s %s", type(e).__name__, e)
        return ""


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
            logger.info("guild sync: %s", [c.name for c in synced])
        else:
            synced = await bot.tree.sync()
            logger.info("global sync: %s", [c.name for c in synced])

        logger.info("로그인 완료: %s", bot.user)
        bot.loop.create_task(update_presence())

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
        logger.error("on_ready error: %s %s", type(e).__name__, e)


# =========================================================
# DM NOTIFY LOOP
# =========================================================
async def notify_loop():
    await bot.wait_until_ready()
    state = load_state()

    def within(target_time: datetime) -> bool:
        return target_time <= now <= (target_time + timedelta(minutes=10))

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

                if within(d1):
                    k = make_key(source, ev["uid"], start_iso, "d-1")
                    if not state.get(k):
                        h2h = await _h2h_suffix(start, source)
                        for uid in get_subscribers_for_source(source):
                            try:
                                user = await bot.fetch_user(uid)
                                await user.send(fmt_dm("⏰ D-1 알림", title, ev) + h2h)
                            except Exception as e:
                                logger.warning("D-1 DM 실패 (%s): %s %s", uid, type(e).__name__, e)
                        state[k] = True

                if within(m30):
                    k = make_key(source, ev["uid"], start_iso, "m-30")
                    if not state.get(k):
                        suffix = await _lineup_suffix(start, source)
                        for uid in get_subscribers_for_source(source):
                            try:
                                user = await bot.fetch_user(uid)
                                await user.send(fmt_dm("🔥 30분 전 알림", title, ev) + suffix)
                            except Exception as e:
                                logger.warning("30분 전 DM 실패 (%s): %s %s", uid, type(e).__name__, e)
                        state[k] = True

                if within(m10):
                    k = make_key(source, ev["uid"], start_iso, "m-10")
                    if not state.get(k):
                        suffix = await _lineup_suffix(start, source)
                        for uid in get_subscribers_for_source(source):
                            try:
                                user = await bot.fetch_user(uid)
                                await user.send(fmt_dm("🚨 10분 전 알림", title, ev) + suffix)
                            except Exception as e:
                                logger.warning("10분 전 DM 실패 (%s): %s %s", uid, type(e).__name__, e)
                        state[k] = True

            save_state(state)

        except Exception as e:
            logger.error("notify_loop error: %s %s", type(e).__name__, e)

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
                minutes_until_kickoff = (kickoff - now).total_seconds() / 60
                state_key = f"spurs_lineup:{spurs_next['uid']}:{kickoff.isoformat()}"

                if -10 <= minutes_until_kickoff <= 75 and not lineup_state.get(state_key):
                    try:
                        fd_match = await find_fd_match_cached(kickoff)
                    except Exception as e:
                        logger.warning("football-data match 조회 실패: %s %s", type(e).__name__, e)
                        fd_match = None

                    if fd_match:
                        match_id = fd_match["id"]
                        is_home = fd_match.get("homeTeam", {}).get("id") == FOOTBALL_DATA_TEAM_ID

                        try:
                            lineup_data = await fetch_fd_lineups(match_id)
                        except Exception as e:
                            logger.warning("lineup fetch 실패: %s %s", type(e).__name__, e)
                            lineup_data = {}

                        side = "homeTeam" if is_home else "awayTeam"
                        if lineup_data.get(side, {}).get("startingXI"):
                            msg = format_lineup_message(fd_match, lineup_data, is_home)
                            await send_to_all_guild_channels(msg)

                            lineup_state[state_key] = True
                            save_lineup_state(lineup_state)
                            logger.info("라인업 알림 발송: %s", spurs_next["summary"])

        except Exception as e:
            logger.error("lineup_loop error: %s %s", type(e).__name__, e)

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
                        fd_match = await find_fd_match(kickoff)
                    except Exception as e:
                        logger.warning("result football-data match 조회 실패: %s %s", type(e).__name__, e)
                        fd_match = None

                    if fd_match:
                        match_id = fd_match["id"]
                        is_home = fd_match.get("homeTeam", {}).get("id") == FOOTBALL_DATA_TEAM_ID

                        try:
                            match_detail = await fetch_fd_match(match_id)
                            status = match_detail.get("status", "")

                            if status == "FINISHED":
                                standing = await fetch_spurs_standings_position(match_detail)
                                next_fixtures = find_next_n_events(spurs_events, 3)
                                msg = format_result_message(match_detail, is_home, standing, next_fixtures)

                                await send_to_all_guild_channels(msg)

                                for uid in get_subscribers_for_source("spurs"):
                                    try:
                                        user = await bot.fetch_user(uid)
                                        await user.send(msg)
                                    except Exception as e:
                                        logger.warning("result DM 실패 (%s): %s %s", uid, type(e).__name__, e)

                                result_state[state_key] = True
                                save_result_state(result_state)
                                logger.info("결과 알림 발송: %s", recent_match["summary"])
                                await update_presence()

                        except Exception as e:
                            logger.warning("result 상태 확인 실패: %s %s", type(e).__name__, e)

        except Exception as e:
            logger.error("result_loop error: %s %s", type(e).__name__, e)

        await asyncio.sleep(300)


# =========================================================
# RUN
# =========================================================
bot.run(TOKEN)
