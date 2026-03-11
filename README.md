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

# 환경변수 설정 (bss.env)
DISCORD_TOKEN=your_token_here
SPURS_ICS_URL=...
F1_ICS_URL=...
FOOTBALL_DATA_TOKEN=your_football_data_token

# 실행
python bot.py
# 또는 윈도우에서 run.bat 더블클릭
```

---

## 패치 노트

> **Phase 1** v0.1~v0.4 — GPT 개발 (2026-03-04 ~ 2026-03-09)
> **Phase 2** v0.5~v0.9 — Claude 개발 (2026-03-10)
> **Phase 3** v1.0~ — Claude 개발 (2026-03-11~)

---

### Phase 3 — Claude (2026-03-11)

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
