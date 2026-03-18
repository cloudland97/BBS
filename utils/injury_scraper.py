"""premierinjuries.com Playwright 부상/출장정지 스크래퍼."""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

_injury_cache: dict | None = None   # {"data": list[dict], "ts": float}
INJURY_CACHE_TTL = 6 * 3600        # 6시간


async def scrape_injuries() -> list[dict]:
    """토트넘 부상/출장정지 선수 목록 반환.
    각 항목: {"name": str, "position": str, "injury": str, "return_date": str, "status": str}
    """
    global _injury_cache
    now = time.monotonic()
    if _injury_cache and now - _injury_cache["ts"] < INJURY_CACHE_TTL:
        return _injury_cache["data"]

    from utils.playwright_manager import get_browser

    url = "https://www.premierinjuries.com/injury-table.php"
    injuries = []

    try:
        browser = await get_browser()
        page = await browser.new_page(extra_http_headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)
            content = await page.content()
        finally:
            await page.close()
    except Exception as e:
        logger.error("injury page 로드 실패: %s %s", type(e).__name__, e)
        return []

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, "html.parser")

        # 팀 섹션 탐색: 텍스트에 "Tottenham" 포함된 헤더 row 찾기
        spurs_section = False
        rows = soup.find_all("tr")
        for row in rows:
            text = row.get_text(separator=" ", strip=True)
            # 팀 헤더 행 감지
            if any(kw in text for kw in ["Tottenham", "Tottenham Hotspur"]):
                spurs_section = True
                continue
            # 다른 팀 헤더 행 도달 시 종료
            if spurs_section:
                tds = row.find_all("td")
                if not tds or len(tds) < 3:
                    # 헤더 행이거나 구분선 → 팀 경계 확인
                    th = row.find("th")
                    if th and th.get_text(strip=True) and "Tottenham" not in th.get_text():
                        break
                    continue
                # 선수 행 파싱
                cells = [td.get_text(strip=True) for td in tds]
                if len(cells) >= 4:
                    injuries.append({
                        "name":        cells[0] if len(cells) > 0 else "",
                        "position":    cells[1] if len(cells) > 1 else "",
                        "injury":      cells[2] if len(cells) > 2 else "",
                        "return_date": cells[3] if len(cells) > 3 else "",
                        "status":      cells[4] if len(cells) > 4 else "",
                    })

    except Exception as e:
        logger.error("injury 파싱 실패: %s %s", type(e).__name__, e)
        return []

    _injury_cache = {"data": injuries, "ts": now}
    logger.info("부상 스크래핑 완료: %d명", len(injuries))
    return injuries


def format_injury_message(injuries: list[dict]) -> str:
    if not injuries:
        return "✅ 현재 부상/출장정지 선수가 없습니다."
    lines = ["🏥 **토트넘 부상/출장정지 현황**", ""]
    for p in injuries:
        ret = p.get("return_date") or "미정"
        status = p.get("status") or ""
        inj = p.get("injury") or ""
        pos = p.get("position") or ""
        line = f"• **{p['name']}** ({pos}) — {inj}"
        if ret:
            line += f" | 복귀: {ret}"
        if status:
            line += f" `{status}`"
        lines.append(line)
    lines.append("")
    lines.append("*출처: premierinjuries.com*")
    return "\n".join(lines)
