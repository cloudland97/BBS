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
| `/bbtime` | 다음 토트넘 + F1 일정 확인 |
| `/bbf1` | F1 다음 GP 전체 세션 일정 |
| `/bbup` | DM 알림 구독 (토트넘 / F1 / 전체) |
| `/bbdown` | DM 알림 구독 해제 |
| `/bbtest` | DM 테스트 발송 |
| `/bbhelp` | 명령어 전체 안내 |

---

## 파일 구조

```
bot.py        — 봇 진입점, on_ready, 알림 루프
commands.py   — 슬래시 커맨드
utils.py      — ICS/Sofascore 헬퍼, 포맷 함수
config.py     — 환경변수, 상수
run.bat       — 윈도우 실행 스크립트
```

---

## 설치 및 실행

```bash
# 패키지 설치
pip install discord.py aiohttp icalendar python-dotenv

# 환경변수 설정 (bss.env)
DISCORD_TOKEN=your_token_here

# 실행
python bot.py
# 또는 윈도우에서 run.bat 더블클릭
```

---

## 패치 노트

### v0.9 (2026-03-10)
- 파일 분리: bot.py → config / utils / commands / bot 4파일 구조로 리팩터링
- 봇 상태창: Sofascore last 호출 제거, ICS 기반 다음 일정만 표시
- F1 상태창에 세션 타입 표시 (FP1 / 예선 / 본경기 등)
- 팀명 자동 단축 처리 (Atletico Madrid → Atletico 등)
- /bblast 제거 (Sofascore 403 오류로 사용 불가)
- PATCHNOTES.txt 추가

### v0.8
- /bbhelp 커맨드 추가
- 멀티서버 지원 (guild_settings.json)
- 글로벌 슬래시 커맨드 전환

### v0.7
- F1 세션 타입 구분 (프랙티스 / 예선 / 스프린트 / 본경기)
- /bbf1 커맨드 추가 (GP 전체 세션 일정)
- /bbup 구독 모드 선택 (토트넘만 / F1만 / 전체)

### v0.6
- 경기 결과 자동 채널 발송 (result_loop)
- /bbtime 커맨드 추가

### v0.5
- DM 발송 시점 변경: 24시간 / 30분 / 10분 전
- 30분 / 10분 전 DM에 라인업 포함

### v0.1 ~ v0.4
- 초기 봇 구성 (토트넘 ICS 파싱, DM 알림, venv 세팅)
