import os
from zoneinfo import ZoneInfo

import discord
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
    "Origin": "https://www.sofascore.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
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
