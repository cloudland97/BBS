import asyncio
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

import commands as bot_commands
from config import F1_ICS_URL, GUILD, SPURS_ICS_URL, SPURS_SOFASCORE_TEAM_ID, TOKEN, KST
from utils import (
    cleanup_old_state,
    ensure_json_files,
    fetch_ics_bytes_cached,
    fetch_sofascore_event,
    fetch_sofascore_lineups,
    fetch_sofascore_missing_players,
    find_next_event,
    find_next_n_events,
    find_recent_spurs_match,
    find_sofascore_match,
    find_sofascore_match_cached,
    fmt_dm,
    f1_session_label,
    f1_session_short,
    format_lineup_message,
    format_result_message,
    fetch_spurs_standings_position,
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

# =========================================================
# DISCORD BOT
# =========================================================
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# 슬래시 커맨드 등록
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
        except:
            pass

        try:
            f1_ics = await fetch_ics_bytes_cached(F1_ICS_URL)
            f1_next = find_next_event(parse_events(f1_ics))
            if f1_next:
                t = f1_next["start_kst"].strftime("%m/%d %H:%M")
                label = f1_session_short(f1_next["summary"])
                parts.append(f"{label} {t}")
        except:
            pass

        status_text = " | ".join(parts) if parts else "토트넘 알림봇"

        await bot.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name=status_text)
        )
        print(f"presence 업데이트: {status_text}")

    except Exception as e:
        print("update_presence 실패:", type(e).__name__, e)


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
        print("on_ready error:", type(e).__name__, e)


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
                                await update_presence()

                        except Exception as e:
                            print("result status 확인 실패:", type(e).__name__, e)

        except Exception as e:
            print("result_loop error:", type(e).__name__, e)

        await asyncio.sleep(300)


# =========================================================
# RUN
# =========================================================
bot.run(TOKEN)
