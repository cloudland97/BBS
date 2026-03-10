import discord
from discord import app_commands

from config import SPURS_SOFASCORE_TEAM_ID
from utils import (
    add_subscriber,
    fetch_ics_bytes_cached,
    find_next_event,
    find_next_gp_sessions,
    fmt_bbf1,
    fmt_next,
    f1_session_label,
    get_guild_channel_id,
    get_subscriber_mode,
    parse_events,
    remove_subscriber,
    set_guild_channel,
)
from config import SPURS_ICS_URL, F1_ICS_URL


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
