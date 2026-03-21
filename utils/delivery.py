"""Discord 전송 인프라 — DM, 채널 발송, 메시지 분할.

bot.py의 루프/커맨드에서 직접 Discord API를 호출하지 않도록
전송 로직을 한 곳에 집약한다.
"""

import logging

import discord

logger = logging.getLogger(__name__)


def split_message(msg: str, limit: int = 1900) -> list[str]:
    """메시지를 limit자 이하 청크로 분할.
    코드블록(```) 안에서 분할 시 블록을 닫고 다음 청크에서 다시 열어 렌더링 깨짐 방지."""
    if len(msg) <= limit:
        return [msg]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    in_code = False
    for line in msg.split("\n"):
        line_len = len(line) + 1
        if line.startswith("```"):
            in_code = not in_code
        if current_len + line_len > limit and current:
            if in_code:
                # 코드블록 내 분할: 현재 블록 닫고 새 청크에서 다시 열기
                current.append("```")
                chunks.append("\n".join(current))
                current = ["```"]
                current_len = 4
            else:
                chunks.append("\n".join(current))
                current, current_len = [], 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


async def send_dms(bot: discord.Client, uids: list[int], msg: str, label: str) -> None:
    """구독자 목록에 DM 발송. 2000자 초과 시 자동 분할. 실패 시 warning 로그."""
    chunks = split_message(msg)
    for uid in uids:
        try:
            user = bot.get_user(uid) or await bot.fetch_user(uid)
            for chunk in chunks:
                await user.send(chunk)
        except Exception as e:
            logger.warning("%s DM 실패 (%s): %s %s", label, uid, type(e).__name__, e)


async def send_to_channels(bot: discord.Client, msg: str) -> None:
    """guild_settings에 등록된 모든 서버 채널에 메시지 발송."""
    from utils.storage import load_guild_settings

    guild_settings = load_guild_settings()
    for guild_id_str, settings in guild_settings.items():
        ch_id = settings.get("channel_id")
        if not ch_id:
            continue
        try:
            ch = bot.get_channel(ch_id)
            if ch is None:
                ch = await bot.fetch_channel(ch_id)
            await ch.send(msg)
        except Exception as e:
            logger.warning("채널 발송 실패 (%s): %s %s", guild_id_str, type(e).__name__, e)
