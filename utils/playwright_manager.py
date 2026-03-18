"""Playwright 브라우저 싱글턴 관리.

봇 수명 동안 브라우저 인스턴스를 하나만 유지.
스크래퍼는 get_browser()로 공유 브라우저를 받아 새 page만 생성/해제.
"""

import logging

logger = logging.getLogger(__name__)

_playwright = None
_browser = None


async def init_browser():
    """봇 시작 시 한 번 호출 — Playwright + Chromium 시작."""
    global _playwright, _browser
    try:
        from playwright.async_api import async_playwright as _ap
        _playwright = await _ap().start()
        _browser = await _playwright.chromium.launch(headless=True)
        logger.info("Playwright 브라우저 시작 완료")
    except Exception as e:
        logger.error("Playwright 초기화 실패: %s %s", type(e).__name__, e)


async def get_browser():
    """공유 브라우저 반환. 미초기화 또는 연결 끊김 시 재시작."""
    global _browser
    if _browser is None or not _browser.is_connected():
        logger.warning("Playwright 브라우저 재시작")
        await init_browser()
    return _browser


async def close_browser():
    """봇 종료 시 호출 — 브라우저 + Playwright 정리."""
    global _playwright, _browser
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None
    logger.info("Playwright 브라우저 종료")
