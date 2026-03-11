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
FOOTBALL_DATA_TOKEN = os.getenv("FOOTBALL_DATA_TOKEN")

GUILD = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None
KST = ZoneInfo("Asia/Seoul")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN이 비어있음. bss.env 확인!")
if not SPURS_ICS_URL:
    raise RuntimeError("SPURS_ICS_URL이 비어있음. bss.env 확인!")
if not F1_ICS_URL:
    raise RuntimeError("F1_ICS_URL이 비어있음. bss.env 확인!")
if not FOOTBALL_DATA_TOKEN:
    raise RuntimeError("FOOTBALL_DATA_TOKEN이 비어있음. bss.env 확인!")

# =========================================================
# CONSTANTS
# =========================================================
FOOTBALL_DATA_TEAM_ID = 73  # Tottenham Hotspur (football-data.org)
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"

# 리그 대회 코드 목록 (순위 조회 가능한 대회만)
LEAGUE_COMPETITION_CODES = ("PL", "BL1", "SA", "PD", "FL1")

ICS_CACHE_TTL = 240        # ICS 캐시 유효시간 (초)
FD_MATCH_CACHE_TTL = 240   # football-data 경기 캐시 유효시간 (초)
STATE_CLEANUP_DAYS = 7

# =========================================================
# FILE PATHS
# =========================================================
STATE_PATH = "notified.json"
SUB_PATH = "subscribers.json"
GUILD_SETTINGS_PATH = "guild_settings.json"
LINEUP_PATH = "lineup_sent.json"
RESULT_PATH = "result_sent.json"
