"""
Discord 글로벌 슬래시 명령어 초기화 + 재등록 스크립트.
봇 실행 전에 1회만 실행. 완료 후 이 파일은 삭제해도 됨.
"""
import asyncio
import os
from dotenv import load_dotenv
import discord
from discord.ext import commands

load_dotenv("bss.env")
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"로그인: {bot.user}")

    # 글로벌 명령어 전체 초기화
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    print("글로벌 명령어 초기화 완료")

    await bot.close()

bot.run(TOKEN)
