# BBS - BetterBotSpurs

토트넘 홋스퍼 + F1 경기 알림 디스코드 봇

---

## 기능

- 토트넘 경기 **24시간 전 / 30분 전 / 10분 전** DM 알림
- 30분 전 / 10분 전 DM에 **공식 선발 라인업** 포함
- **F1 세션 알림** (프리 프랙티스 / 예선 / 스프린트 / 본경기 구분)
- 경기 종료 후 **결과 자동 채널 발송**
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
| `/bbup` | DM 알림 구독 (토트넘 / F1 / 전체) |
| `/bbdown` | DM 알림 구독 해제 |
| `/bbtest` | DM 테스트 발송 |
| `/bbhelp` | 명령어 전체 안내 |

---

## 파일 구조

```
bot.py          — 봇 진입점, on_ready, 알림 루프
commands.py     — 슬래시 커맨드
config.py       — 환경변수, 상수
utils/
  __init__.py   — re-export (외부 import 진입점)
  storage.py    — JSON 상태 관리
  ics.py        — ICS 파싱 + F1 헬퍼
  football_data.py — football-data.org API + 캐시
  formatters.py — 메시지 포맷 함수
run.bat         — 윈도우 실행 스크립트
```

---

## 설치 및 실행

```bash
# 패키지 설치
pip install -r requirements.txt

# 실행
python bot.py
# 또는 윈도우에서 run.bat 더블클릭
```

---

## 환경변수 설정 (bss.env)

프로젝트 루트에 `bss.env` 파일 생성:

```env
DISCORD_TOKEN=your_discord_bot_token
SPURS_ICS_URL=https://...ics    # 토트넘 경기 ICS 캘린더 URL
F1_ICS_URL=https://...ics       # F1 일정 ICS 캘린더 URL
FOOTBALL_DATA_TOKEN=your_token  # football-data.org 무료 API 토큰
GUILD_ID=                       # (선택) 특정 서버에만 커맨드 등록 시 서버 ID
```

> `football-data.org` 무료 토큰 발급: https://www.football-data.org/client/register

---

## 운영 가이드

### 첫 실행 순서
1. `bss.env` 작성 후 봇 실행
2. 디스코드 서버에서 `/bbset` 실행 → 알림 채널 지정 (관리자 전용)
3. 사용자들이 `/bbup` 으로 DM 구독

### 알림 정책

| 알림 종류 | DM (bbup 구독자) | 채널 (bbset 설정) |
|---------|:---:|:---:|
| D-1 경기 예고 + 상대 전적 | ✅ | ❌ |
| 30분 전 + 라인업(확정 시) | ✅ | ❌ |
| 10분 전 + 라인업(확정 시) | ✅ | ❌ |
| 라인업 자동 발표 | ✅ | ✅ |
| 경기 결과 + 득점자 | ✅ | ✅ |

### 상태 파일 자동 생성
봇 시작 시 아래 파일이 없으면 자동 생성됨. 직접 만들 필요 없음.
```
notified.json / subscribers.json / guild_settings.json
lineup_sent.json / result_sent.json
```

### football-data.org 제약
- 무료 플랜: 분당 10요청
- 라인업 데이터: 공식 발표 시점(킥오프 약 1시간 전) 이후 반영
- FA Cup / League Cup: 무료 플랜 미지원 → 해당 경기 라인업/결과 없을 수 있음
- 리그 순위: Premier League만 지원

---

## 패치 노트

> **Phase 1** v0.1~v0.4 — GPT 개발 (2026-03-04 ~ 2026-03-09)
> **Phase 2** v0.5~v0.9 — Claude 개발 (2026-03-10)
> **Phase 3** v1.0~ — Claude 개발 (2026-03-11~)

---

### Phase 3 — Claude (2026-03-11)

#### v1.3 (2026-03-16)
- **시황 가시성 개선**: 색상 점(🟢🟡⚪🟠🔴) 시스템 추가
  - 증시·원자재: 변화율 기준 (±1% / ±0.2%)
  - 코인: 기준 완화 (±2% / ±0.5%)
  - VIX: 역방향 (<15 🟢, <20 🟡, <30 🟠, ≥30 🔴)
  - 공포탐욕: 등급별 (극공🔴→극탐🔵)
  - 기준금리: 동결⚪ / 인상🔴 / 인하🟢
- **`notify_loop` 리팩터**: D-1/M-30/M-10 개별 if 블록 → slots 리스트 패턴
- **PATCHNOTES.txt 삭제** (README에 통합)

#### v1.2 (2026-03-16)
- **시황 브리핑** 기능 추가 (`/bbmk`, `bbup market`)
  - 코스피 개장(09:00) / 마감(15:30) / 나스닥 개·폐장 시 자동 DM
  - 환율(USD·USDT·JPY·CNY·DXY) / 증시(KOSPI·KOSDAQ·닛케이·NASDAQ) / VIX·공포탐욕지수
  - 기준금리(연방기금·한국은행) / 금·은·WTI / BTC·ETH·**USDT** 시총
  - 주말 발송 스킵
  - 연방기금 FRED fetch 실패 시 config fallback 추가
- **ARK ETF 매매 내역** 기능 추가 (`/bbark`, `bbup ark`)
  - 매일 07:00 KST 전일 매매 내역 자동 DM
  - 주말 발송 스킵
- **경기 결과** 채널 발송 제거 → 구독자 DM 전용
- **라인업 감지** 버그 수정: 킥오프 이후에도 +75분까지 감지 (`find_lineup_window_match`)
- `/bbdm` interaction 만료(404) 버그 수정: `defer()` 최우선 실행
- `/bbdm` 시황·ARK fetch 병렬화 (`asyncio.gather`)
- **코드 최적화**: `_send_dms` helper, `reply_error` helper, ARK fetch 단일 gather
- `print()` → `logger` 전환 (market.py, ark.py)

#### v1.1
- `/bbtt` 상대팀 현황 + **토트넘 기준 EPL 순위표 (±3팀)** 동시 표시
- `/bbtt` 상대현황/순위/라인업/H2H 4개 API 병렬 호출로 응답 속도 개선
- `notify_loop` ICS fetch 병렬화 (`asyncio.gather`)
- `bot.py` `import asyncio` 누락 버그 수정 (D-1 알림 안정성)
- 미사용 함수 `fetch_spurs_standings_position` 제거

#### v1.0
- **Sofascore → football-data.org 교체** (비공식 API 의존 제거, 공식 무료 플랜)
- `/bbtime` → `/bbtt` 리네임 + 기능 확장
  - 이전 경기 결과 표시
  - 최근 5경기 폼 (승무패 + 이모지)
  - 상대 전적 H2H (최근 5경기)
  - 라인업 확정 시 자동 포함
- `/bblineup` 신규: 홈/어웨이 양 팀 풀 라인업 + 등번호 + 포메이션
- 라인업 메시지에 **등번호 + 포메이션** 추가
- 결과 메시지에 **득점자 표시** (토트넘 / 상대팀 구분)
- D-1 DM 알림에 **상대 전적 H2H** 자동 첨부
- `logging` 도입 (print → 레벨별 로그)
- `utils/` 패키지 분리 (storage / ics / football_data / formatters)
- API 캐시 추가 (최근경기 10분, H2H 1시간)
- `requirements.txt` 추가
- `.gitignore` 보강 (상태 JSON + 로그 파일)
- `CLAUDE.md` 추가 (프로젝트 구조 문서)

---

### Phase 2 — Claude (2026-03-10)

#### v0.9
- bot.py 1000줄 → config / utils / commands / bot 4파일 분리
- presence: Sofascore last 호출 제거, ICS 기반 다음 일정만 표시
- F1 상태창에 세션 타입 표시 (FP1 / 예선 / 본경기 등)
- 팀명 자동 단축 처리 (Atletico Madrid → Atletico 등)
- /bblast 제거 (Sofascore 403 오류로 사용 불가)

#### v0.8
- /bblast 커맨드 추가 및 제거 (Sofascore 403 차단)

#### v0.7
- 봇 상태창(presence)에 다음 토트넘 + F1 일정 자동 표시

#### v0.6
- 멀티서버 지원 (guild_settings.json)
- 글로벌 슬래시 커맨드 전환
- /bbhelp 커맨드 추가

#### v0.5
- DM 발송 시점 변경: 24시간 / 30분 / 10분 전
- 30분 / 10분 전 DM에 라인업 포함
- F1 세션 타입 구분 (프랙티스 / 예선 / 스프린트 / 본경기)
- /bbf1, /bbtime 커맨드 추가
- /bbup 구독 모드 선택 (토트넘만 / F1만 / 전체)
- 경기 결과 자동 채널 발송 (result_loop)

---

### Phase 1 — GPT (2026-03-04 ~ 2026-03-09)

#### v0.4
- Sofascore API 라인업 조회 기능
- 경기 1시간 전 DM에 라인업 포함

#### v0.3
- F1 ICS 캘린더 파싱 및 DM 알림 추가

#### v0.2
- /bbup, /bbdown 커맨드
- 토트넘 경기 DM 알림 (24시간 / 1시간 / 킥오프 전)

#### v0.1
- 초기 봇 구성 (Python + discord.py, venv, run.bat)
