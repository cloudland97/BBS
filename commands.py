import discord
from discord import app_commands

from config import SPURS_ICS_URL, F1_ICS_URL, FOOTBALL_DATA_TEAM_ID
from utils import (
    add_subscriber,
    fetch_fd_h2h,
    fetch_fd_lineups,
    fetch_ics_bytes_cached,
    fetch_spurs_recent_matches,
    find_fd_match_cached,
    find_next_event,
    find_next_gp_sessions,
    fmt_bbf1,
    fmt_next,
    f1_session_label,
    format_h2h_message,
    format_lineup_message,
    format_lineup_message_full,
    format_previous_result,
    format_recent_form,
    get_guild_channel_id,
    get_subscriber_mode,
    parse_events,
    remove_subscriber,
    set_guild_channel,
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

            # ICS + 최근 경기 API 병렬 호출
            import asyncio
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

            # football-data.org에서 경기 찾기 (라인업 + H2H용)
            fd_match = await find_fd_match_cached(spurs_ev["start_kst"])
            if fd_match:
                match_id = fd_match["id"]
                is_home = fd_match.get("homeTeam", {}).get("id") == FOOTBALL_DATA_TEAM_ID

                # 라인업 확정 시 단축 버전 표시
                lineup_data = await fetch_fd_lineups(match_id)
                side = "homeTeam" if is_home else "awayTeam"
                if lineup_data.get(side, {}).get("startingXI"):
                    msg_parts.append(format_lineup_message(fd_match, lineup_data, is_home))

                # H2H
                h2h_data = await fetch_fd_h2h(match_id)
                h2h_text = format_h2h_message(h2h_data)
                if h2h_text:
                    msg_parts.append(h2h_text)

            # 3. 최근 5경기 폼
            form_text = format_recent_form(recent_matches)
            if form_text:
                msg_parts.append(form_text)

            await interaction.followup.send("\n\n".join(msg_parts))

        except Exception as e:
            msg = f"에러: {type(e).__name__}: {e}"
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
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
            except Exception:
                pass

    @bot.tree.command(name="bblineup", description="토트넘 다음 경기 양 팀 풀 라인업을 보여줍니다")
    async def bblineup(interaction: discord.Interaction):
        if not await ensure_server_channel(interaction):
            return
        try:
            await interaction.response.defer(thinking=True)

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
            msg = f"에러: {type(e).__name__}: {e}"
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
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
            "**토트넘 일정**\n"
            "`/bbtt` — 다음 경기 일정 + 상대 전적 (라인업 확정 시 포함)\n"
            "`/bblineup` — 다음 경기 양 팀 풀 라인업\n"
            "\n"
            "**F1 일정**\n"
            "`/bbf1` — 다음 GP 전체 세션 일정\n"
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
            "📊 경기 결과 + 득점자 + 다음 3경기 — 경기 종료 후 자동 발송\n"
            "\n"
            f"내 구독 상태: **{sub_status}**"
        )
        await interaction.response.send_message(msg, ephemeral=True)
