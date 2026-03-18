import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
import discord
from discord.ext import commands, tasks

import commands as bot_commands
from config import ARK_ALERT_TIME, F1_ICS_URL, FOOTBALL_DATA_TEAM_ID, GUILD, SPURS_ICS_URL, TOKEN, KST
from utils import (
    cleanup_ark_notified,
    cleanup_market_notified,
    cleanup_old_state,
    clear_old_lineup_cache,
    ensure_json_files,
    extract_opponent,
    fetch_ark_trades,
    fetch_fd_h2h,
    fetch_fd_lineups,
    fetch_fd_match,
    fetch_ics_bytes_cached,
    fetch_market_data,
    fetch_opponent_standing,
    fetch_standings_mini,
    find_fd_match,
    find_fd_match_cached,
    find_lineup_window_match,
    find_live_match,
    find_next_event,
    find_next_n_events,
    find_recent_spurs_match,
    fmt_dm,
    f1_session_label,
    f1_session_short,
    format_ark_message,
    format_bbc_lineup_message,
    format_h2h_message,
    format_lineup_message,
    format_market_message,
    format_opponent_brief,
    format_result_message,
    format_injury_message,
    get_ark_subscribers,
    get_cached_lineup,
    get_market_subscribers,
    get_nasdaq_close_kst,
    get_nasdaq_open_kst,
    get_subscribers_for_source,
    load_ark_notified,
    load_guild_settings,
    load_lineup_state,
    load_market_notified,
    load_result_state,
    load_state,
    make_key,
    parse_events,
    save_ark_notified,
    save_lineup_state,
    save_market_notified,
    save_result_state,
    save_state,
    scrape_bbc_lineup,
    scrape_injuries,
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

# 라이브 스코어 상태 (in-memory)
_live_embed_msgs: dict[int, discord.Message] = {}  # guild_id -> Message
_live_match_id: int | None = None
_live_last_score: str = ""  # 변경 감지용 직렬화 문자열


# =========================================================
# HELPERS THAT NEED bot INSTANCE
# =========================================================
def _build_live_embed(match_detail: dict) -> discord.Embed:
    """라이브 스코어 embed 생성."""
    home = match_detail.get("homeTeam", {}).get("name", "?")
    away = match_detail.get("awayTeam", {}).get("name", "?")
    score = match_detail.get("score", {})
    full = score.get("fullTime", {})
    home_score = full.get("home", 0) if full.get("home") is not None else "-"
    away_score = full.get("away", 0) if full.get("away") is not None else "-"
    status = match_detail.get("status", "")

    if status == "FINISHED":
        title = f"✅ FT | {home} {home_score} - {away_score} {away}"
        color = 0x888888
    else:
        title = f"⚽ LIVE | {home} {home_score} - {away_score} {away}"
        color = 0x00ff88

    embed = discord.Embed(title=title, color=color)

    # 골 이벤트 (최대 10개)
    goals = match_detail.get("goals", [])[:10]
    if goals:
        spurs_team_id = FOOTBALL_DATA_TEAM_ID
        goal_lines = []
        for goal in goals:
            team_id = goal.get("team", {}).get("id")
            scorer = goal.get("scorer", {}).get("name", "?")
            minute = goal.get("minute", "?")
            goal_type = goal.get("type", "")
            og_suffix = " (OG)" if goal_type == "OWN_GOAL" else ""
            if team_id == spurs_team_id:
                goal_lines.append(f"🟢 {scorer}{og_suffix} {minute}'")
            else:
                goal_lines.append(f"🔴 {scorer}{og_suffix} {minute}'")
        embed.description = "\n".join(goal_lines)

    now_str = datetime.now(KST).strftime("%H:%M")
    embed.set_footer(text=f"football-data.org | {now_str} 기준")
    return embed


async def update_presence():
    """봇 상태를 다음 F1 + 다음 토트넘 일정으로 업데이트."""
    try:
        parts = []
        try:
            spurs_ics = await fetch_ics_bytes_cached(SPURS_ICS_URL)
            spurs_next = find_next_event(parse_events(spurs_ics))
            if spurs_next:
                t = spurs_next["start_kst"].strftime("%m/%d %H:%M")
                opp = extract_opponent(spurs_next["summary"])
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


async def _send_dms(uids: list[int], msg: str, label: str):
    """구독자 목록에 DM 발송. 실패 시 warning 로그."""
    for uid in uids:
        try:
            user = await bot.fetch_user(uid)
            await user.send(msg)
        except Exception as e:
            logger.warning("%s DM 실패 (%s): %s %s", label, uid, type(e).__name__, e)


async def _lineup_suffix(kickoff: datetime, source: str, uid: str = "") -> str:
    """DM 알림용 단축 라인업. 라인업 미확정이면 빈 문자열 반환."""
    if source != "spurs":
        return ""
    # 1. BBC 캐시 확인
    if uid:
        cached = get_cached_lineup(uid)
        if cached:
            return "\n\n" + format_bbc_lineup_message(cached)
    # 2. football-data.org 시도
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


async def _opponent_brief_suffix(kickoff: datetime, source: str) -> str:
    """D-1 DM 알림용 상대팀 리그 현황. 컵대회 또는 조회 실패 시 빈 문자열 반환."""
    if source != "spurs":
        return ""
    try:
        fd_match = await find_fd_match_cached(kickoff)
        if not fd_match:
            return ""
        row = await fetch_opponent_standing(fd_match)
        if not row:
            return ""
        return "\n\n" + format_opponent_brief(row)
    except Exception as e:
        logger.warning("opponent_brief_suffix 실패: %s %s", type(e).__name__, e)
        return ""


# =========================================================
# READY / SYNC
# =========================================================
@bot.event
async def on_ready():
    try:
        # 봇 수명 동안 유지되는 공유 aiohttp 세션
        if not hasattr(bot, "http_session") or bot.http_session is None or bot.http_session.closed:
            bot.http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
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
        await update_presence()

        # 오래된 BBC 라인업 캐시 정리
        clear_old_lineup_cache(datetime.now(KST) - timedelta(days=1))

        if not live_score_loop.is_running():
            live_score_loop.start()
        if not notify_loop.is_running():
            notify_loop.start()
        if not lineup_loop.is_running():
            lineup_loop.start()
        if not lineup_prefetch_loop.is_running():
            lineup_prefetch_loop.start()
        if not result_loop.is_running():
            result_loop.start()
        if not market_loop.is_running():
            market_loop.start()
        if not ark_loop.is_running():
            ark_loop.start()

    except Exception as e:
        logger.error("on_ready error: %s %s", type(e).__name__, e)


# =========================================================
# LIVE SCORE LOOP
# =========================================================
@tasks.loop(seconds=60)
async def live_score_loop():
    global _live_embed_msgs, _live_match_id, _live_last_score
    try:
        spurs_ics = await fetch_ics_bytes_cached(SPURS_ICS_URL)
        live_event = find_live_match(parse_events(spurs_ics))

        if not live_event:
            _live_embed_msgs.clear()
            _live_match_id = None
            _live_last_score = ""
            return

        kickoff = live_event["start_kst"]
        fd_match = await find_fd_match_cached(kickoff)
        if not fd_match:
            return

        match_id = fd_match["id"]
        match_detail = await fetch_fd_match(match_id)
        status = match_detail.get("status", "")

        # 변경 감지용 직렬화
        score = match_detail.get("score", {}).get("fullTime", {})
        goals = match_detail.get("goals", [])
        score_str = f"{status}:{score.get('home')}:{score.get('away')}:{len(goals)}"
        if score_str == _live_last_score:
            return
        _live_last_score = score_str

        embed = _build_live_embed(match_detail)
        guild_settings = load_guild_settings()

        for guild_id_str, settings in guild_settings.items():
            ch_id = settings.get("channel_id")
            if not ch_id:
                continue
            guild_id = int(guild_id_str)
            try:
                ch = bot.get_channel(ch_id)
                if ch is None:
                    ch = await bot.fetch_channel(ch_id)
                existing_msg = _live_embed_msgs.get(guild_id)
                if existing_msg:
                    await existing_msg.edit(embed=embed)
                else:
                    msg = await ch.send(embed=embed)
                    _live_embed_msgs[guild_id] = msg
            except Exception as e:
                logger.warning("live_score 채널 발송 실패 (%s): %s %s", guild_id_str, type(e).__name__, e)

        if status == "FINISHED":
            _live_embed_msgs.clear()
            _live_match_id = None
            _live_last_score = ""

    except Exception as e:
        logger.error("live_score_loop error: %s %s", type(e).__name__, e)


@live_score_loop.before_loop
async def before_live_score_loop():
    await bot.wait_until_ready()


@live_score_loop.error
async def on_live_score_loop_error(error: Exception):
    logger.error("live_score_loop 예외 (루프 중단): %s %s", type(error).__name__, error)


# =========================================================
# DM NOTIFY LOOP
# =========================================================
@tasks.loop(seconds=300)
async def notify_loop():
    state = load_state()
    now = datetime.now(KST)

    def within(target_time: datetime) -> bool:
        return target_time <= now <= (target_time + timedelta(minutes=10))

    try:
        spurs_ics, f1_ics = await asyncio.gather(
            fetch_ics_bytes_cached(SPURS_ICS_URL),
            fetch_ics_bytes_cached(F1_ICS_URL),
        )

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
            uids = get_subscribers_for_source(source)

            async def _d1_suffix(start=start, source=source):
                ob, h2h, injuries = await asyncio.gather(
                    _opponent_brief_suffix(start, source),
                    _h2h_suffix(start, source),
                    scrape_injuries() if source == "spurs" else asyncio.sleep(0),
                )
                suffix = ob + h2h
                if source == "spurs" and isinstance(injuries, list) and injuries:
                    suffix += "\n\n" + format_injury_message(injuries)
                return suffix

            async def _pre_suffix(start=start, source=source, ev_uid=ev["uid"]):
                return await _lineup_suffix(start, source, uid=ev_uid)

            slots = [
                ("d-1",  start - timedelta(hours=24),   "⏰ D-1 알림",    _d1_suffix),
                ("m-30", start - timedelta(minutes=30), "🔥 30분 전 알림", _pre_suffix),
                ("m-10", start - timedelta(minutes=10), "🚨 10분 전 알림", _pre_suffix),
            ]

            for kind, target, label, get_suffix in slots:
                if not within(target):
                    continue
                k = make_key(source, ev["uid"], start_iso, kind)
                if state.get(k):
                    continue
                suffix = await get_suffix()
                await _send_dms(uids, fmt_dm(label, title, ev) + suffix, kind)
                state[k] = True

        save_state(state)

    except Exception as e:
        logger.error("notify_loop error: %s %s", type(e).__name__, e)


@notify_loop.before_loop
async def before_notify_loop():
    await bot.wait_until_ready()


@notify_loop.error
async def on_notify_loop_error(error: Exception):
    logger.error("notify_loop 예외 (루프 중단): %s %s", type(error).__name__, error)


# =========================================================
# LINEUP LOOP
# =========================================================
@tasks.loop(seconds=300)
async def lineup_loop():
    lineup_state = load_lineup_state()
    now = datetime.now(KST)

    try:
        spurs_ics = await fetch_ics_bytes_cached(SPURS_ICS_URL)
        spurs_next = find_lineup_window_match(parse_events(spurs_ics))

        if spurs_next:
            kickoff = spurs_next["start_kst"]
            state_key = f"spurs_lineup:{spurs_next['uid']}:{kickoff.isoformat()}"

            if not lineup_state.get(state_key):
                msg = None

                # 1. BBC 캐시 확인
                cached = get_cached_lineup(spurs_next["uid"])
                if cached:
                    msg = format_bbc_lineup_message(cached)
                    logger.info("BBC 캐시 라인업 사용: %s", spurs_next["summary"])

                # 2. 캐시 없으면 football-data.org 시도
                if not msg:
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

                if msg:
                    await send_to_all_guild_channels(msg)
                    await _send_dms(get_subscribers_for_source("spurs"), msg, "lineup")

                    lineup_state[state_key] = True
                    save_lineup_state(lineup_state)
                    logger.info("라인업 알림 발송: %s", spurs_next["summary"])

    except Exception as e:
        logger.error("lineup_loop error: %s %s", type(e).__name__, e)


@lineup_loop.before_loop
async def before_lineup_loop():
    await bot.wait_until_ready()


@lineup_loop.error
async def on_lineup_loop_error(error: Exception):
    logger.error("lineup_loop 예외 (루프 중단): %s %s", type(error).__name__, error)


# =========================================================
# LINEUP PREFETCH LOOP (BBC Sport)
# =========================================================
@tasks.loop(seconds=300)
async def lineup_prefetch_loop():
    """킥오프 61분 전에 BBC Sport 라인업 미리 스크래핑."""
    now = datetime.now(KST)

    try:
        spurs_ics = await fetch_ics_bytes_cached(SPURS_ICS_URL)
        spurs_next = find_next_event(parse_events(spurs_ics))

        if not spurs_next:
            return

        kickoff = spurs_next["start_kst"]
        uid = spurs_next["uid"]
        diff = kickoff - now

        # 윈도우: T-90min ~ T-61min
        if not (timedelta(minutes=61) <= diff <= timedelta(minutes=90)):
            return

        # 이미 캐시에 있으면 스킵
        if get_cached_lineup(uid):
            return

        opponent = extract_opponent(spurs_next["summary"])
        success = await scrape_bbc_lineup(uid, kickoff, opponent)

        if success:
            logger.info("BBC 라인업 프리페치 성공: %s vs %s", "Spurs", opponent)
        else:
            logger.info("BBC 라인업 프리페치 실패: %s vs %s", "Spurs", opponent)

    except Exception as e:
        logger.error("lineup_prefetch_loop error: %s %s", type(e).__name__, e)


@lineup_prefetch_loop.before_loop
async def before_lineup_prefetch_loop():
    await bot.wait_until_ready()


@lineup_prefetch_loop.error
async def on_lineup_prefetch_loop_error(error: Exception):
    logger.error("lineup_prefetch_loop 예외 (루프 중단): %s %s", type(error).__name__, error)


# =========================================================
# RESULT LOOP
# =========================================================
@tasks.loop(seconds=300)
async def result_loop():
    result_state = load_result_state()

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
                            standings_data = await fetch_standings_mini(match_detail, n=3)
                            next_fixtures = find_next_n_events(spurs_events, 3)
                            msg = format_result_message(match_detail, is_home, standings_data, next_fixtures)

                            await _send_dms(get_subscribers_for_source("spurs"), msg, "result")

                            result_state[state_key] = True
                            save_result_state(result_state)
                            logger.info("결과 알림 발송: %s", recent_match["summary"])
                            await update_presence()

                    except Exception as e:
                        logger.warning("result 상태 확인 실패: %s %s", type(e).__name__, e)

    except Exception as e:
        logger.error("result_loop error: %s %s", type(e).__name__, e)


@result_loop.before_loop
async def before_result_loop():
    await bot.wait_until_ready()


@result_loop.error
async def on_result_loop_error(error: Exception):
    logger.error("result_loop 예외 (루프 중단): %s %s", type(error).__name__, error)


# =========================================================
# MARKET LOOP (매 60초 — KST 시간 체크)
# =========================================================
@tasks.loop(seconds=30)
async def market_loop():
    now = datetime.now(KST)
    if now.weekday() >= 5:  # 토(5)/일(6) 스킵
        return

    nasdaq_open  = get_nasdaq_open_kst()
    nasdaq_close = get_nasdaq_close_kst()

    alert_times = {
        "09:00":      "코스피 개장",
        "15:30":      "코스피 마감",
        nasdaq_open:  "나스닥 개장",
        nasdaq_close: "나스닥 마감",
    }

    today_key = now.strftime("%Y-%m-%d")
    notified = load_market_notified()
    notified = cleanup_market_notified(notified)

    for alert_hm, label in alert_times.items():
        state_key = f"{today_key}:{alert_hm}"
        if notified.get(state_key):
            continue
        h, m = map(int, alert_hm.split(":"))
        alert_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if not (alert_dt <= now <= alert_dt + timedelta(minutes=2)):
            continue

        try:
            data = await fetch_market_data()
            msg  = format_market_message(data, label)

            await _send_dms(get_market_subscribers(), msg, "시황")

            notified[state_key] = True
            save_market_notified(notified)
            logger.info("시황 알림 발송: %s (%s)", label, alert_hm)
        except Exception as e:
            logger.error("market_loop 발송 실패: %s %s", type(e).__name__, e)


@market_loop.before_loop
async def before_market_loop():
    await bot.wait_until_ready()


@market_loop.error
async def on_market_loop_error(error: Exception):
    logger.error("market_loop 예외 (루프 중단): %s %s", type(error).__name__, error)


# =========================================================
# ARK LOOP (매 60초 — 07:00 KST 고정)
# =========================================================
@tasks.loop(seconds=30)
async def ark_loop():
    now = datetime.now(KST)
    if now.weekday() >= 5:  # 토(5)/일(6) 스킵
        return

    h, m = map(int, ARK_ALERT_TIME.split(":"))
    alert_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if not (alert_dt <= now <= alert_dt + timedelta(minutes=2)):
        return

    today_key = now.strftime("%Y-%m-%d")
    notified  = load_ark_notified()
    notified  = cleanup_ark_notified(notified)

    if notified.get(today_key):
        return

    try:
        data = await fetch_ark_trades()
        msg  = format_ark_message(data)

        await _send_dms(get_ark_subscribers(), msg, "ARK")

        notified[today_key] = True
        save_ark_notified(notified)
        logger.info("ARK 알림 발송: %s", today_key)
    except Exception as e:
        logger.error("ark_loop 발송 실패: %s %s", type(e).__name__, e)


@ark_loop.before_loop
async def before_ark_loop():
    await bot.wait_until_ready()


@ark_loop.error
async def on_ark_loop_error(error: Exception):
    logger.error("ark_loop 예외 (루프 중단): %s %s", type(error).__name__, error)


# =========================================================
# CLEANUP
# =========================================================
@bot.event
async def on_close():
    if hasattr(bot, "http_session") and bot.http_session and not bot.http_session.closed:
        await bot.http_session.close()
        bot.http_session = None


# =========================================================
# RUN
# =========================================================
bot.run(TOKEN)
