# BBS - 봉봉서포트

스포츠 경기 알림 · 글로벌 시황 브리핑 · ARK ETF 매매 내역 · 뉴스 발송을 제공하는 디스코드 봇

---

## 기능 요약

**스포츠**
- 토트넘 경기 **24시간 전 / 30분 전 / 10분 전** DM 알림
- 30분 전 / 10분 전 DM에 **공식 선발 라인업** 포함
- **F1 세션 알림** (프리 프랙티스 / 예선 / 스프린트 / 본경기 구분)
- 경기 중 **실시간 골 알림** DM
- 경기 종료 후 **결과 + 득점자** 자동 DM

**시황**
- 글로벌 시황 브리핑 (환율·증시·코인·원자재·VIX·공포탐욕지수·기준금리)
- 코스피 개장(09:00) / 마감(15:30) / 나스닥 개·폐장 시 자동 DM
- 한국증시만 / 미국증시만 / 전체 구독 선택 가능

**ARK ETF**
- ARK 전 펀드 포트폴리오 Top 20 (market value 기준)
- 최근 2거래일 매매 내역 + 평단가 포함
- 매일 07:00 KST 자동 DM

**뉴스 / 운영**
- 봉봉뉴스: 관리자가 발행하면 구독자 전체 DM 발송
- 봇 상태창에 **다음 토트넘 + F1 일정** 표시
- **멀티서버** 지원

---

## 커맨드

| 커맨드 | 설명 |
|--------|------|
| `/bbset` | 알림 채널 지정 (관리자용) |
| `/bbtt` | 이전 결과 + 다음 경기 + 최근 폼 + H2H |
| `/bblineup` | 다음 경기 양 팀 풀 라인업 |
| `/bbf1` | F1 다음 GP 전체 세션 일정 |
| `/bbmk` | 글로벌 시황 즉시 조회 (환율·증시·코인·원자재) |
| `/bbark` | ARK 전 펀드 포트폴리오 Top 20 + 최근 2거래일 매매 내역 |
| `/bbup` | DM 알림 구독 (토트넘 / F1 / 시황 / ARK / 봉봉뉴스 / 전체) |
| `/bbdown` | DM 알림 전체 해제 |
| `/bbdm` | 구독 중인 알림 즉시 DM 수신 |
| `/bblist` | 내 구독 현황 확인 |
| `/bbnews` | 봉봉뉴스 전체 구독자 DM 발송 (관리자용) |
| `/bbuplist` | 카테고리별 구독자 목록 확인 (관리자용) |
| `/bbhelp` | 명령어 전체 안내 |

---

## 파일 구조

```
bot.py              — 봇 진입점, on_ready, 알림 루프
commands.py         — 슬래시 커맨드
config.py           — 환경변수, 상수
utils/
  __init__.py       — re-export (외부 import 진입점)
  storage.py        — JSON 상태 관리
  ics.py            — ICS 파싱 + F1 헬퍼
  football_data.py  — football-data.org API + 캐시
  formatters.py     — 메시지 포맷 함수
  market.py         — 시황 데이터 fetch + 포맷
  ark.py            — ARK ETF 데이터 fetch + 포맷
  bongnews.py       — 봉봉뉴스 구독 관리
  lineup_scraper.py — BBC Sport 라인업 스크래핑
  playwright_manager.py — Playwright 브라우저 싱글턴
run.bat             — Windows 전용 실행 스크립트 (로그 자동 저장)
```

---

## 설치 및 실행

```bash
pip install -r requirements.txt

# Linux / macOS
python bot.py

# Windows — run.bat 더블클릭 (로그 logs/bot_YYYY-MM-DD.txt 자동 저장)
```

---

## 환경변수 설정 (bss.env)

```env
DISCORD_TOKEN=your_discord_bot_token
SPURS_ICS_URL=https://...ics
F1_ICS_URL=https://...ics
FOOTBALL_DATA_TOKEN=your_token
GUILD_ID=                        # (선택) 특정 서버에만 커맨드 등록 시
```

> `football-data.org` 무료 토큰 발급: https://www.football-data.org/client/register

---

## 운영 가이드

### 첫 실행
1. `bss.env` 작성 후 봇 실행
2. `/bbset` 으로 알림 채널 지정 (관리자)
3. `/bbup` 으로 구독

### 스포츠 알림 정책

| 알림 종류 | DM | 채널 |
|---------|:---:|:---:|
| D-1 경기 예고 + 상대 전적 | ✅ | ❌ |
| 30분 전 + 라인업(확정 시) | ✅ | ❌ |
| 10분 전 + 라인업(확정 시) | ✅ | ❌ |
| 라인업 자동 발표 | ✅ | ✅ |
| 실시간 골 알림 | ✅ | ❌ |
| 경기 결과 + 득점자 | ✅ | ❌ |

### 시황 알림 정책

| 시간 | 알림 | 대상 구독 |
|------|------|---------|
| 09:00 KST | 코스피 개장 브리핑 | market / market_kr / all |
| 15:30 KST | 코스피 마감 브리핑 | market / market_kr / all |
| 나스닥 개장 | 미국증시 브리핑 | market / market_us / all |
| 나스닥 마감 | 미국증시 브리핑 | market / market_us / all |

### ARK 알림 정책
- 매일 07:00 KST, 평일만 발송
- 포트폴리오 Top 20 (market value 기준) + 최근 2거래일 매매 내역

### 데이터 제약
- football-data.org 무료 플랜: 분당 10요청
- 라인업: 킥오프 약 1시간 전 이후 반영
- FA Cup / League Cup: 라인업·결과 없을 수 있음
- 부상자 정보: 무료 플랜 미제공

### 상태 파일 (자동 생성)
```
notified.json / subscribers.json / guild_settings.json
lineup_sent.json / result_sent.json
ark_notified.json / ark_subscribers.json
market_notified.json / market_subscribers.json
bongnews_subscribers.json
```

---

## 최근 변경사항

#### v1.6 (2026-03-20)
- ARK Top 20 순위 기준 market value로 변경, % 제거·주식수 복원
- bbark / bbdm / 정기 알림 출력 형식 통일
- `get_user` 우선 패턴 적용 (API 요청 최소화)

#### v1.5 (2026-03-19)
- 봉봉뉴스 구독·발송 기능 추가 (`/bbnews`, `/bbuplist`)
- 시황 구독 세분화: `market_kr` / `market_us` 분리

전체 변경 이력 → [CHANGELOG.md](CHANGELOG.md)
