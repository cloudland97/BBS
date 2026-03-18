import asyncio
import logging

import discord
from discord import app_commands

logger = logging.getLogger(__name__)

from config import SPURS_ICS_URL, F1_ICS_URL, FOOTBALL_DATA_TEAM_ID
from utils import (
    add_ark_subscriber,
    add_market_subscriber,
    add_subscriber,
    fetch_ark_trades,
    fetch_fd_h2h,
    fetch_market_data,
    format_ark_message,
    format_market_message,
    fetch_fd_lineups,
    fetch_ics_bytes_cached,
    fetch_opponent_standing,
    fetch_spurs_recent_matches,
    fetch_standings_mini,
    find_fd_match_cached,
    find_next_event,
    find_next_gp_sessions,
    fmt_bbf1,
    fmt_next,
    f1_session_label,
    format_h2h_message,
    format_lineup_message,
    format_lineup_message_full,
    format_opponent_brief,
    format_previous_result,
    format_recent_form,
    format_standings_mini,
    get_guild_channel_id,
    get_subscriber_mode,
    is_ark_subscriber,
    is_market_subscriber,
    parse_events,
    remove_ark_subscriber,
    remove_market_subscriber,
    remove_subscriber,
    set_guild_channel,
    scrape_injuries,
    format_injury_message,
)


def setup(bot: app_commands.CommandTree.__class__) -> None:
    """bot 인스턴스를 받아 슬래시 커맨드를 등록한다."""

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

    async def reply_error(interaction: discord.Interaction, e: Exception):
        msg = f"에러: {type(e).__name__}: {e}"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException as ex:
            if ex.code == 40060:  # already acknowledged — followup으로 재시도
                try:
                    await interaction.followup.send(msg, ephemeral=True)
                except Exception:
                    pass
            else:
                logger.warning("interaction 응답 실패: %s %s", type(ex).__name__, ex)
        except Exception as ex:
            logger.warning("interaction 응답 실패: %s %s", type(ex).__name__, ex)

    MODE_LABELS = {"all": "토트넘 + F1 전체", "spurs": "토트넘만", "f1": "F1만"}

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

    @bot.tree.command(name="bbtt", description="토트넘 이전 결과 / 다음 경기 / 최근 폼")
    async def bbtt(interaction: discord.Interaction):
        if not await ensure_server_channel(interaction):
            return
        try:
            await interaction.response.defer(thinking=True)
        except (discord.NotFound, discord.HTTPException):
            return
        try:

            # ICS + 최근 경기 API 병렬 호출
            spurs_bytes, recent_matches = await asyncio.gather(
                fetch_ics_bytes_cached(SPURS_ICS_URL),
                fetch_spurs_recent_matches(5),
            )

            msg_parts = []

            # 1. 이전 경기 결과
            if recent_matches:
                msg_parts.append(format_previous_result(recent_matches[0]))

            # 2. 다음 경기
            spurs_ev = find_next_event(parse_events(spurs_bytes))
            if not spurs_ev:
                msg_parts.append("다음 토트넘 일정이 없습니다.")
                await interaction.followup.send("\n\n".join(msg_parts))
                return

            t = spurs_ev["start_kst"].strftime("%Y-%m-%d (%a) %H:%M")
            msg_parts.append(f"⚽ **다음 경기**\n**{spurs_ev['summary']}**\n시작: {t} (KST)")

            # football-data.org에서 경기 찾기 (라인업 + H2H + 상대 현황용)
            fd_match = await find_fd_match_cached(spurs_ev["start_kst"])
            if fd_match:
                match_id = fd_match["id"]
                is_home = fd_match.get("homeTeam", {}).get("id") == FOOTBALL_DATA_TEAM_ID

                # 상대 현황 + 순위표 + 라인업 + H2H + 부상자 병렬 호출
                opp_row, standings_result, lineup_data, h2h_data, injuries = await asyncio.gather(
                    fetch_opponent_standing(fd_match),
                    fetch_standings_mini(fd_match),
                    fetch_fd_lineups(match_id),
                    fetch_fd_h2h(match_id),
                    scrape_injuries(),
                )
                mini_table, spurs_pos = standings_result

                # 상대팀 현황
                if opp_row:
                    msg_parts.append(format_opponent_brief(opp_row))

                # 토트넘 기준 리그 순위표
                if mini_table:
                    msg_parts.append(format_standings_mini(mini_table, spurs_pos))

                # 라인업 확정 시 풀 라인업 표시
                side = "homeTeam" if is_home else "awayTeam"
                if lineup_data.get(side, {}).get("startingXI"):
                    msg_parts.append(format_lineup_message_full(fd_match, lineup_data))
                    if injuries:
                        msg_parts.append(format_injury_message(injuries))

                # H2H
                h2h_text = format_h2h_message(h2h_data)
                if h2h_text:
                    msg_parts.append(h2h_text)

            # 3. 최근 5경기 폼
            form_text = format_recent_form(recent_matches)
            if form_text:
                msg_parts.append(form_text)

            await interaction.followup.send("\n\n".join(msg_parts))

        except Exception as e:
            await reply_error(interaction, e)

    @bot.tree.command(name="bbf1", description="F1 다음 GP의 전체 세션 일정을 보여줍니다")
    async def bbf1(interaction: discord.Interaction):
        if not await ensure_server_channel(interaction):
            return
        try:
            await interaction.response.defer(thinking=True)
        except (discord.NotFound, discord.HTTPException):
            return
        try:
            f1_bytes = await fetch_ics_bytes_cached(F1_ICS_URL)
            gp_name, sessions = find_next_gp_sessions(parse_events(f1_bytes))

            if not gp_name:
                await interaction.followup.send("다음 F1 일정이 없습니다.")
                return

            await interaction.followup.send(fmt_bbf1(gp_name, sessions))

        except Exception as e:
            await reply_error(interaction, e)

    @bot.tree.command(name="bblineup", description="토트넘 다음 경기 양 팀 풀 라인업을 보여줍니다")
    async def bblineup(interaction: discord.Interaction):
        if not await ensure_server_channel(interaction):
            return
        try:
            await interaction.response.defer(thinking=True)
        except (discord.NotFound, discord.HTTPException):
            return
        try:
            spurs_bytes = await fetch_ics_bytes_cached(SPURS_ICS_URL)
            spurs_ev = find_next_event(parse_events(spurs_bytes))

            if not spurs_ev:
                await interaction.followup.send("다음 토트넘 일정이 없습니다.")
                return

            fd_match = await find_fd_match_cached(spurs_ev["start_kst"])
            if not fd_match:
                await interaction.followup.send("⚠️ football-data.org에서 경기를 찾을 수 없어.")
                return

            lineup_data = await fetch_fd_lineups(fd_match["id"])
            home_xi = lineup_data.get("homeTeam", {}).get("startingXI")
            away_xi = lineup_data.get("awayTeam", {}).get("startingXI")

            if not home_xi and not away_xi:
                t = spurs_ev["start_kst"].strftime("%m/%d (%a) %H:%M")
                await interaction.followup.send(
                    f"⏳ 아직 라인업이 발표되지 않았어.\n**{spurs_ev['summary']}** | {t} KST"
                )
                return

            await interaction.followup.send(format_lineup_message_full(fd_match, lineup_data))

        except Exception as e:
            await reply_error(interaction, e)

    @bot.tree.command(name="bbup", description="알림 DM 구독")
    @app_commands.describe(종목="알림 받을 종목 선택 (기본: 전체)")
    @app_commands.choices(종목=[
        app_commands.Choice(name="전체 (경기 + 시황 + ARK)", value="all"),
        app_commands.Choice(name="토트넘만", value="spurs"),
        app_commands.Choice(name="F1만", value="f1"),
        app_commands.Choice(name="시황 알림", value="market"),
        app_commands.Choice(name="캐시우드 (ARK)", value="ark"),
    ])
    async def bbup(interaction: discord.Interaction, 종목: app_commands.Choice[str] = None):
        if not await ensure_server_channel_or_dm(interaction):
            return

        mode = 종목.value if 종목 else "all"

        if mode == "all":
            add_subscriber(interaction.user.id, "all")
            add_market_subscriber(interaction.user.id)
            add_ark_subscriber(interaction.user.id)
            await interaction.response.send_message(
                "✅ 전체 알림 구독 완료 (경기 + 시황 + ARK)\n"
                "• 경기 알림: 24시간 전 / 30분 전 / 10분 전\n"
                "• 시황 브리핑: 09:00 / 15:30 / 나스닥 개·폐장\n"
                "• ARK 매매 내역: 매일 07:00",
                ephemeral=True,
            )
        elif mode == "market":
            add_market_subscriber(interaction.user.id)
            await interaction.response.send_message(
                "✅ 시황 알림 구독 완료\n"
                "매일 09:00 / 15:30 / 나스닥 개·폐장 시 DM으로 시황 브리핑을 보내줄게.",
                ephemeral=True,
            )
        elif mode == "ark":
            add_ark_subscriber(interaction.user.id)
            await interaction.response.send_message(
                "✅ ARK 매매 알림 구독 완료\n"
                "매일 07:00 KST에 캐시우드 ARK 전 펀드 매매 내역을 DM으로 보내줄게.",
                ephemeral=True,
            )
        else:
            add_subscriber(interaction.user.id, mode)
            await interaction.response.send_message(
                f"✅ 경기 알림 구독 완료 ({MODE_LABELS[mode]})\n24시간 전 / 30분 전 / 10분 전에 DM 보내줄게.",
                ephemeral=True,
            )

    @bot.tree.command(name="bbdown", description="알림 DM 구독 전체 해제 (경기 + 시황 + ARK)")
    async def bbdown(interaction: discord.Interaction):
        if not await ensure_server_channel_or_dm(interaction):
            return
        remove_subscriber(interaction.user.id)
        remove_market_subscriber(interaction.user.id)
        remove_ark_subscriber(interaction.user.id)
        await interaction.response.send_message("❌ 모든 알림 구독 해제 완료", ephemeral=True)

    @bot.tree.command(name="bbmk", description="현재 시황 (환율·지수·코인·원자재) 즉시 조회")
    async def bbmk(interaction: discord.Interaction):
        if not await ensure_server_channel_or_dm(interaction):
            return
        try:
            await interaction.response.defer(thinking=True)
        except (discord.NotFound, discord.HTTPException):
            return
        try:
            data = await fetch_market_data()
            msg  = format_market_message(data, "즉시 조회")
            await interaction.followup.send(msg)
        except Exception as e:
            await reply_error(interaction, e)

    @bot.tree.command(name="bbark", description="ARK 전 펀드 최근 거래일 매매 내역 조회")
    async def ark(interaction: discord.Interaction):
        if not await ensure_server_channel_or_dm(interaction):
            return
        try:
            await interaction.response.defer(thinking=True)
        except (discord.NotFound, discord.HTTPException):
            return
        try:
            data = await fetch_ark_trades()
            msg  = format_ark_message(data)
            await interaction.followup.send(msg)
        except Exception as e:
            await reply_error(interaction, e)

    @bot.tree.command(name="bbdm", description="구독 중인 알림을 지금 즉시 DM으로 받아봅니다")
    async def bbdm(interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            return  # interaction 만료 (3초 초과)
        except discord.HTTPException:
            return  # 이미 응답됨 등 기타

        # 채널 가드 (defer 이후 followup으로)
        if interaction.guild is not None:
            allowed_channel_id = get_guild_channel_id(interaction.guild.id)
            if not allowed_channel_id:
                await interaction.followup.send(
                    "⚠️ 이 서버는 아직 봇 채널이 설정되지 않았어.\n관리자가 사용할 채널에서 `/bbset` 먼저 실행해줘.",
                    ephemeral=True,
                )
                return
            if interaction.channel_id != allowed_channel_id:
                ch = interaction.guild.get_channel(allowed_channel_id)
                mention = ch.mention if ch else f"<#{allowed_channel_id}>"
                await interaction.followup.send(
                    f"⚠️ 이 서버에서는 {mention} 채널에서만 봇을 사용할 수 있어.", ephemeral=True
                )
                return

        user_id = interaction.user.id
        mode    = get_subscriber_mode(user_id)
        is_mkt  = is_market_subscriber(user_id)
        is_ark  = is_ark_subscriber(user_id)

        if not mode and not is_mkt and not is_ark:
            await interaction.followup.send(
                "⚠️ 구독 중인 알림이 없어.\n`/bbup`으로 먼저 구독해줘.", ephemeral=True
            )
            return

        sent = []
        errors = []

        try:
            # 시황 + ARK 병렬 fetch
            mkt_data, ark_data = await asyncio.gather(
                fetch_market_data() if is_mkt else asyncio.sleep(0),
                fetch_ark_trades()  if is_ark else asyncio.sleep(0),
            )
            if is_mkt:
                await interaction.user.send(format_market_message(mkt_data, "즉시 브리핑"))
                sent.append("📊 시황 브리핑")
            if is_ark:
                await interaction.user.send(format_ark_message(ark_data))
                sent.append("🦆 ARK 매매 내역")

            # 스포츠 (다음 경기 정보)
            if mode:
                sports_msgs = []

                if mode in ("all", "spurs"):
                    try:
                        spurs_bytes, recent_matches = await asyncio.gather(
                            fetch_ics_bytes_cached(SPURS_ICS_URL),
                            fetch_spurs_recent_matches(1),
                        )
                        spurs_ev = find_next_event(parse_events(spurs_bytes))
                        parts = []
                        if recent_matches:
                            parts.append(format_previous_result(recent_matches[0]))
                        if spurs_ev:
                            t = spurs_ev["start_kst"].strftime("%Y-%m-%d (%a) %H:%M")
                            parts.append(f"⚽ **다음 경기**\n**{spurs_ev['summary']}**\n시작: {t} (KST)")
                            fd_match = await find_fd_match_cached(spurs_ev["start_kst"])
                            if fd_match:
                                opp_row, standings_result, h2h_data = await asyncio.gather(
                                    fetch_opponent_standing(fd_match),
                                    fetch_standings_mini(fd_match),
                                    fetch_fd_h2h(fd_match["id"]),
                                )
                                mini_table, spurs_pos = standings_result
                                if opp_row:
                                    parts.append(format_opponent_brief(opp_row))
                                if mini_table:
                                    parts.append(format_standings_mini(mini_table, spurs_pos))
                                h2h_text = format_h2h_message(h2h_data)
                                if h2h_text:
                                    parts.append(h2h_text)
                        if parts:
                            sports_msgs.append("\n\n".join(parts))
                    except Exception as e:
                        errors.append(f"토트넘: {type(e).__name__}")

                if mode in ("all", "f1"):
                    try:
                        from utils import fmt_bbf1, find_next_gp_sessions
                        f1_bytes = await fetch_ics_bytes_cached(F1_ICS_URL)
                        gp_name, sessions = find_next_gp_sessions(parse_events(f1_bytes))
                        if gp_name:
                            sports_msgs.append(fmt_bbf1(gp_name, sessions))
                    except Exception as e:
                        errors.append(f"F1: {type(e).__name__}")

                for msg in sports_msgs:
                    await interaction.user.send(msg)
                if sports_msgs:
                    sent.append("⚽🏎️ 경기 일정")

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ DM을 보낼 수 없어. 디스코드 개인정보 설정에서 DM 허용을 확인해줘.", ephemeral=True
            )
            return
        except Exception as e:
            errors.append(f"DM 발송 오류: {type(e).__name__}: {e}")

        result = "✅ DM 발송 완료: " + ", ".join(sent) if sent else "⚠️ 발송된 내용이 없어."
        if errors:
            result += "\n⚠️ 오류: " + ", ".join(errors)
        await interaction.followup.send(result, ephemeral=True)

    @bot.tree.command(name="bblist", description="현재 내 구독 현황을 DM으로 확인합니다")
    async def bblist(interaction: discord.Interaction):
        if not await ensure_server_channel_or_dm(interaction):
            return

        user_id = interaction.user.id
        mode    = get_subscriber_mode(user_id)
        is_mkt  = is_market_subscriber(user_id)
        is_ark  = is_ark_subscriber(user_id)

        sports_status = f"✅ 구독 중 ({MODE_LABELS.get(mode, mode)})" if mode else "❌ 미구독"
        market_status = "✅ 구독 중" if is_mkt else "❌ 미구독"
        ark_status    = "✅ 구독 중" if is_ark  else "❌ 미구독"

        msg = (
            "**📋 내 구독 현황**\n"
            "\n"
            f"⚽ **경기 알림** (토트넘/F1): {sports_status}\n"
            f"📊 **시황 브리핑** (09:00/15:30/나스닥): {market_status}\n"
            f"🦆 **ARK 매매 내역** (07:00): {ark_status}\n"
            "\n"
            "`/bbup` — 구독 추가  |  `/bbdown` — 전체 해제"
        )
        await interaction.response.send_message(msg, ephemeral=True)

    @bot.tree.command(name="bbinjury", description="토트넘 현재 부상/출장정지 선수 현황")
    async def bbinjury(interaction: discord.Interaction):
        if not await ensure_server_channel(interaction):
            return
        try:
            await interaction.response.defer(thinking=True)
        except (discord.NotFound, discord.HTTPException):
            return
        try:
            injuries = await scrape_injuries()
            await interaction.followup.send(format_injury_message(injuries))
        except Exception as e:
            await reply_error(interaction, e)

    @app_commands.default_permissions(administrator=True)
    @bot.tree.command(name="bbtest", description="[관리자] 전체 커맨드 일괄 테스트")
    async def bbtest(interaction: discord.Interaction):
        if interaction.guild and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ 관리자 전용", ephemeral=True)
            return
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except (discord.NotFound, discord.HTTPException):
            return

        async def _run(label: str, coro):
            try:
                result = await coro
                return f"**[BBTEST용 {label}]**\n{result}"
            except Exception as e:
                return f"**[BBTEST용 {label}]** ❌ {type(e).__name__}: {e}"

        # /bbtt
        async def _bbtt():
            spurs_bytes, recent = await asyncio.gather(
                fetch_ics_bytes_cached(SPURS_ICS_URL),
                fetch_spurs_recent_matches(1),
            )
            parts = []
            if recent:
                parts.append(format_previous_result(recent[0]))
            ev = find_next_event(parse_events(spurs_bytes))
            if ev:
                t = ev["start_kst"].strftime("%Y-%m-%d (%a) %H:%M")
                parts.append(f"⚽ **다음 경기**\n**{ev['summary']}**\n시작: {t} (KST)")
            return "\n\n".join(parts) or "일정 없음"

        # /bbf1
        async def _bbf1():
            f1_bytes = await fetch_ics_bytes_cached(F1_ICS_URL)
            gp_name, sessions = find_next_gp_sessions(parse_events(f1_bytes))
            return fmt_bbf1(gp_name, sessions) if gp_name else "F1 일정 없음"

        # /bbmk
        async def _bbmk():
            data = await fetch_market_data()
            return format_market_message(data, "BBTEST 즉시 조회")

        # /bbark
        async def _bbark():
            data = await fetch_ark_trades()
            return format_ark_message(data)

        tests = [
            ("/bbtt",  _bbtt()),
            ("/bbf1",  _bbf1()),
            ("/bbmk",  _bbmk()),
            ("/bbark", _bbark()),
        ]

        for label, coro in tests:
            msg = await _run(label, coro)
            # Discord 메시지 2000자 제한 대응
            if len(msg) > 1900:
                msg = msg[:1900] + "\n…(생략)"
            await interaction.followup.send(msg, ephemeral=True)

    @bot.tree.command(name="bbhelp", description="사용 가능한 모든 명령어를 보여줍니다")
    async def bbhelp(interaction: discord.Interaction):
        if not await ensure_server_channel_or_dm(interaction):
            return

        mode = get_subscriber_mode(interaction.user.id)
        sports_status = f"구독 중 ({MODE_LABELS.get(mode, mode)})" if mode else "미구독"
        market_status = "구독 중" if is_market_subscriber(interaction.user.id) else "미구독"
        ark_status    = "구독 중" if is_ark_subscriber(interaction.user.id)    else "미구독"

        msg = (
            "**📋 BBS 봇 명령어 목록**\n"
            "\n"
            "**토트넘 일정**\n"
            "`/bbtt` — 다음 경기 일정 + 상대 전적 (라인업 확정 시 포함)\n"
            "`/bblineup` — 다음 경기 양 팀 풀 라인업\n"
            "\n"
            "**F1 일정**\n"
            "`/bbf1` — 다음 GP 전체 세션 일정\n"
            "\n"
            "**시황 / 투자**\n"
            "`/bbmk` — 환율·지수·코인·원자재 즉시 조회\n"
            "`/bbark` — ARK 전 펀드 최근 거래일 매매 내역\n"
            "\n"
            "**알림 구독 (DM)**\n"
            "`/bbup [종목]` — 경기 알림 구독 (전체 / 토트넘만 / F1만 / 시황 / ARK)\n"
            "`/bbdown` — 모든 구독 해제\n"
            "`/bblist` — 내 구독 현황 확인\n"
            "`/bbdm` — 구독 중인 알림 지금 즉시 DM으로 받기\n"
            "\n"
            "**서버 설정 (관리자 전용)**\n"
            "`/bbset` — 현재 채널을 봇 전용 채널로 설정\n"
            "\n"
            "**자동 알림 (채널)**\n"
            "⚽ 토트넘 오피셜 라인업 — 킥오프 75분 전부터 자동 감지\n"
            "📊 경기 결과 + 득점자 + 다음 3경기 — 경기 종료 후 자동 발송\n"
            "\n"
            f"내 경기 구독: **{sports_status}**\n"
            f"내 시황 구독: **{market_status}**\n"
            f"내 ARK 구독:  **{ark_status}**"
        )
        await interaction.response.send_message(msg, ephemeral=True)
