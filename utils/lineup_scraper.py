"""BBC Sport Playwright 라인업 스크래퍼.

킥오프 61분 전에 BBC Sport에서 라인업을 미리 스크래핑해서 캐싱.
기존 30분전/10분전 DM 알림에서 캐시 데이터를 사용.
"""

import asyncio
import logging
import re
import unicodedata
from datetime import datetime

from config import KST

logger = logging.getLogger(__name__)

# key: ICS uid (예: "4833814-8586@fotmob.com")
# value: {"home_xi": [...], "away_xi": [...], "home_formation": str,
#         "away_formation": str, "home_name": str, "away_name": str,
#         "kickoff_kst": datetime}
_lineup_cache: dict = {}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_ORDINAL_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)")
_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def _normalize(text: str) -> str:
    """소문자 + 악센트 제거 (Atlético → atletico)."""
    return unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode()


def _opponent_match(opponent_lower: str, page_text: str) -> bool:
    """상대팀 이름 퍼지 매칭: 악센트 정규화 후 핵심 단어 포함 여부 확인."""
    norm_page = _normalize(page_text)
    norm_opp = _normalize(opponent_lower)
    if norm_opp in norm_page:
        return True
    # 단어별로 확인 (2글자 이상 단어 하나라도 포함되면 매칭)
    words = [w for w in norm_opp.split() if len(w) >= 3]
    return any(w in norm_page for w in words)


def _parse_bbc_date(text: str) -> tuple[int, int] | None:
    """'Sunday 16th March' -> (day=16, month=3). 실패 시 None."""
    text_lower = text.lower()
    day_match = _ORDINAL_RE.search(text_lower)
    if not day_match:
        return None
    day = int(day_match.group(1))
    for month_name, month_num in _MONTH_MAP.items():
        if month_name in text_lower:
            return (day, month_num)
    return None


def _parse_player_line(text: str) -> list[dict]:
    """'Number1, Forster, GK' 패턴에서 선수 목록 추출."""
    players = []
    pattern = re.compile(r"Number(\d+),\s*(.+?),\s*(\w+)")
    for m in pattern.finditer(text):
        players.append({
            "number": int(m.group(1)),
            "name": m.group(2).strip(),
            "position": m.group(3).strip(),
        })
    return players


def _parse_lineup_text(raw_text: str) -> dict | None:
    """MatchLineupsContainer 텍스트에서 양팀 라인업 파싱."""
    if not raw_text:
        return None

    # 팀명 추출
    home_name_match = re.search(r"home team,\s*(.+?)(?:\.|,|Starting)", raw_text, re.IGNORECASE)
    away_name_match = re.search(r"away team,\s*(.+?)(?:\.|,|Starting)", raw_text, re.IGNORECASE)
    home_name = home_name_match.group(1).strip() if home_name_match else ""
    away_name = away_name_match.group(1).strip() if away_name_match else ""

    # 포메이션 추출
    formation_pattern = re.compile(r"Formation:\s*([\d\s\-]+)", re.IGNORECASE)
    formations = formation_pattern.findall(raw_text)
    home_formation = formations[0].replace(" ", "").replace("-", "-") if len(formations) >= 1 else ""
    away_formation = formations[1].replace(" ", "").replace("-", "-") if len(formations) >= 2 else ""

    # 포메이션 공백 정리: "4-2-3-1" 형태로
    def clean_formation(f: str) -> str:
        parts = [p.strip() for p in f.split("-") if p.strip()]
        return "-".join(parts)

    home_formation = clean_formation(home_formation)
    away_formation = clean_formation(away_formation)

    # 홈/어웨이 섹션 분리 (away team 기준으로 분할)
    away_split = re.split(r"away team,", raw_text, maxsplit=1, flags=re.IGNORECASE)
    home_section = away_split[0] if len(away_split) >= 1 else raw_text
    away_section = away_split[1] if len(away_split) >= 2 else ""

    # Starting lineup 섹션 추출
    def extract_starting(section: str) -> str:
        match = re.search(r"Starting lineup(.+?)(?:Substitutes|$)", section, re.IGNORECASE | re.DOTALL)
        return match.group(1) if match else section

    home_starting = extract_starting(home_section)
    away_starting = extract_starting(away_section)

    home_xi = _parse_player_line(home_starting)
    away_xi = _parse_player_line(away_starting)

    if not home_xi and not away_xi:
        return None

    return {
        "home_xi": home_xi,
        "away_xi": away_xi,
        "home_formation": home_formation,
        "away_formation": away_formation,
        "home_name": home_name,
        "away_name": away_name,
    }


async def scrape_bbc_lineup(uid: str, kickoff_kst: datetime, opponent: str) -> bool:
    """BBC Sport에서 라인업 스크래핑 후 캐시 저장. 성공 시 True 반환."""
    from utils.playwright_manager import get_browser

    year_month = kickoff_kst.strftime("%Y-%m")
    fixtures_url = (
        f"https://www.bbc.com/sport/football/teams/"
        f"tottenham-hotspur/scores-fixtures/{year_month}"
    )

    kick_day = kickoff_kst.day
    kick_month = kickoff_kst.month
    opponent_lower = opponent.lower()
    match_url = None

    try:
        browser = await get_browser()
        context = await browser.new_context(user_agent=_USER_AGENT)
        page = await context.new_page()
        try:
            # 1) 일정 페이지에서 경기 URL 찾기
            await page.goto(fixtures_url)
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)

            links = await page.query_selector_all('a[href*="/sport/football/"]')
            for link in links:
                try:
                    href = await link.get_attribute("href")
                    if not href:
                        continue
                    parent = await link.evaluate_handle(
                        "el => el.closest('li') || el.closest('div') || el.parentElement"
                    )
                    parent_text = await parent.inner_text() if parent else ""
                    if not parent_text:
                        parent_text = await link.inner_text()

                    parsed = _parse_bbc_date(parent_text)
                    if not parsed:
                        continue
                    p_day, p_month = parsed
                    if p_day != kick_day or p_month != kick_month:
                        continue
                    if not _opponent_match(opponent_lower, parent_text):
                        continue

                    match_url = f"https://www.bbc.com{href}" if href.startswith("/") else href
                    break
                except Exception:
                    continue

            if not match_url:
                logger.info("BBC 일정에서 경기 URL 찾지 못함: Spurs vs %s (%s)", opponent, year_month)
                return False

            # 2) 경기 페이지에서 라인업 스크래핑
            await page.goto(match_url)
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)

            container = await page.query_selector('[class*="MatchLineupsContainer"]')
            if not container:
                logger.info("BBC 라인업 컨테이너 없음: %s", match_url)
                return False

            raw_text = await container.inner_text()
            result = _parse_lineup_text(raw_text)
            if not result:
                logger.info("BBC 라인업 파싱 실패: %s", match_url)
                return False

            result["kickoff_kst"] = kickoff_kst
            _lineup_cache[uid] = result
            logger.info("BBC 라인업 캐시 저장: uid=%s, home=%s, away=%s",
                        uid, result["home_name"], result["away_name"])
            return True

        finally:
            await context.close()

    except Exception as e:
        logger.warning("BBC 라인업 스크래핑 실패: %s %s", type(e).__name__, e)
        return False


def get_cached_lineup(uid: str) -> dict | None:
    """캐시된 라인업 반환. 없으면 None."""
    return _lineup_cache.get(uid)


def clear_old_lineup_cache(cutoff_dt: datetime):
    """kickoff가 cutoff_dt보다 오래된 캐시 항목 삭제."""
    to_delete = [
        uid for uid, data in _lineup_cache.items()
        if data.get("kickoff_kst") and data["kickoff_kst"] < cutoff_dt
    ]
    for uid in to_delete:
        del _lineup_cache[uid]
    if to_delete:
        logger.info("오래된 BBC 라인업 캐시 %d건 삭제", len(to_delete))


def format_bbc_lineup_message(lineup: dict) -> str:
    """캐시된 라인업 dict -> Discord 포맷 문자열."""
    home_name = lineup.get("home_name", "Home")
    away_name = lineup.get("away_name", "Away")
    home_formation = lineup.get("home_formation", "")
    away_formation = lineup.get("away_formation", "")
    home_xi = lineup.get("home_xi", [])
    away_xi = lineup.get("away_xi", [])

    home_f_str = f" ({home_formation})" if home_formation else ""
    away_f_str = f" ({away_formation})" if away_formation else ""

    lines = ["\U0001f3df\ufe0f **BBC Sport lineup**"]

    # 홈팀
    lines += ["", f"\U0001f3e0 **{home_name}**{home_f_str}"]
    for p in home_xi:
        lines.append(f"{p['number']} {p['name']} {p['position']}")

    # 원정팀
    lines += ["", f"\u2708\ufe0f **{away_name}**{away_f_str}"]
    for p in away_xi:
        lines.append(f"{p['number']} {p['name']} {p['position']}")

    return "\n".join(lines)
