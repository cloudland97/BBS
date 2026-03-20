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
BOK_API_KEY = os.getenv("BOK_API_KEY", "")  # ecos.bok.or.kr 발급 (선택)

GUILD = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None
KST = ZoneInfo("Asia/Seoul")
ET  = ZoneInfo("America/New_York")

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

YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

ARK_ETFS       = ["ARKK", "ARKW", "ARKG", "ARKQ", "ARKF", "ARKX"]
ARK_ALERT_TIME = "07:00"

# 기준금리 — 변경 시 수동 업데이트 (한은: 연 8회, Fed: 연 8회 FOMC)
BOK_RATE = 2.75   # 한국은행 기준금리 (%, 2025-02-25 인하)
FED_RATE = 4.50   # 연방기금 상단 목표율 (%, 2025-01-29 동결) — FRED fetch 실패 시 fallback

# =========================================================
# FILE PATHS
# =========================================================
STATE_PATH           = "notified.json"
SUB_PATH             = "subscribers.json"
GUILD_SETTINGS_PATH  = "guild_settings.json"
LINEUP_PATH          = "lineup_sent.json"
RESULT_PATH          = "result_sent.json"
MARKET_SUB_PATH      = "market_subscribers.json"
MARKET_NOTIFIED_PATH = "market_notified.json"
ARK_SUB_PATH         = "ark_subscribers.json"
ARK_NOTIFIED_PATH    = "ark_notified.json"
BONGNEWS_SUB_PATH    = "bongnews_subscribers.json"
