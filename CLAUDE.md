# BBS Bot — Claude 작업 가이드

## 프로젝트 개요
Python + discord.py 기반 스포츠 알림 봇.
토트넘 경기 일정(ICS)과 F1 일정(ICS)을 파싱해 DM 알림 + 채널 자동 발송.

## 파일 구조

```
bot.py          봇 초기화, on_ready, 3개 루프 (notify/lineup/result)
commands.py     슬래시 커맨드 setup() 함수 — bot 인스턴스 받아 등록
config.py       환경변수 로드(bss.env) + 상수 정의
utils/          유틸 패키지 (아래 참고)
  __init__.py   모든 서브모듈 re-export (외부 import는 여기서)
  storage.py    JSON 상태 관리 (구독자, 알림 기록, 서버 채널 설정)
  ics.py        ICS fetch/파싱, 이벤트 탐색, F1 세션 분류, fmt_* 포맷
  football_data.py  football-data.org API 함수 + 캐시
  formatters.py 디스코드 메시지 포맷 함수 (라인업/결과/폼/H2H)
```

## 데이터 소스

| 소스 | 용도 | 설정 위치 |
|-----|------|---------|
| ICS (SPURS_ICS_URL) | 토트넘 경기 일정 | bss.env |
| ICS (F1_ICS_URL) | F1 세션 일정 | bss.env |
| football-data.org | 라인업/결과/순위/H2H/최근전적 | bss.env (FOOTBALL_DATA_TOKEN) |

football-data.org 토트넘 팀 ID: **73**. 비공식 API 아님 — 공식 무료 플랜 (분당 10요청).

## 슬래시 커맨드

| 커맨드 | 기능 |
|-------|------|
| `/bbtt` | 이전 결과 + 다음 경기 + 최근 5경기 폼 + H2H (라인업 확정 시 포함) |
| `/bblineup` | 다음 경기 양 팀 풀 라인업 |
| `/bbf1` | 다음 F1 GP 전체 세션 일정 |
| `/bbup [종목]` | DM 알림 구독 (all/spurs/f1) |
| `/bbdown` | 구독 해제 |
| `/bbtest` | DM 수신 테스트 |
| `/bbset` | 서버 전용 채널 설정 (관리자) |
| `/bbhelp` | 명령어 목록 + 구독 상태 |

## 자동 루프 (300초 간격)

- **notify_loop**: D-1(+H2H) / M-30(+라인업) / M-10(+라인업) DM 발송
- **lineup_loop**: 킥오프 -10~75분 사이 라인업 확정 시 채널 발송
- **result_loop**: 킥오프 후 3시간 이내 경기, FINISHED 상태 감지 시 채널+DM 발송

## 상태 파일 (런타임 생성, git 제외)

| 파일 | 내용 |
|-----|------|
| notified.json | DM 발송 완료 키 기록 (중복 방지) |
| subscribers.json | 구독자 {userId: mode} |
| guild_settings.json | 서버별 채널 ID |
| lineup_sent.json | 라인업 채널 발송 기록 |
| result_sent.json | 결과 채널 발송 기록 |

## 캐시 구조 (인메모리, 재시작 시 초기화)

| 캐시 변수 | 위치 | TTL |
|---------|------|-----|
| `_ics_cache` | ics.py | 240초 |
| `_fd_match_cache` | football_data.py | 240초 |
| `_recent_matches_cache` | football_data.py | 600초 |
| `_h2h_cache` | football_data.py | 3600초 |

## 주요 설계 결정

- lineup "확정" 판단: `startingXI` 비어있지 않으면 확정 (football-data.org 명시적 플래그 없음)
- result "종료" 판단: `match["status"] == "FINISHED"`
- 순위 조회: PL 등 리그 대회만 지원 (`LEAGUE_COMPETITION_CODES`)
- FA Cup / League Cup: API 미지원 가능 → 라인업/결과 없을 수 있음
- 부상자 정보: football-data.org 무료 플랜 미제공 → `/bblineup`에 없음

## 작업 시 주의사항

- `bss.env`는 git에 포함 안 됨 — 토큰 직접 수정 필요
- `commands.py`의 `setup(bot)` 함수가 bot.tree에 커맨드 등록 → bot.py에서 호출
- 상태 파일은 `ensure_json_files()`가 on_ready에서 자동 생성
- `cleanup_old_state()`가 on_ready에서 7일 이상 된 기록 자동 삭제
