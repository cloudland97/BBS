# CHANGELOG

> **Phase 1** v0.1~v0.4 — GPT 개발 (2026-03-04 ~ 2026-03-09)
> **Phase 2** v0.5~v0.9 — Claude 개발 (2026-03-10)
> **Phase 3** v1.0~ — Claude 개발 (2026-03-11~)

---

### Phase 3 — Claude (2026-03-11~)

#### v1.6 (2026-03-20)
- **ARK Top 20 개선**
  - 포트폴리오 순위 기준을 market value로 변경
  - % 제거, 총 주식수 복원, market value 표시 추가 ($B/$M/$K)
  - bbark / bbdm / 정기 알림 출력 형식 통일 (포트폴리오 Top 20 + 최근 2거래일 매매 내역)
- **최적화**: Yahoo Finance AUM fetch 제거 (API 요청 3N → 2N), true_weight dead code 제거
- **get_user 우선 패턴**: `_send_dms`에서 캐시 우선 조회 후 fetch fallback으로 변경

#### v1.5 (2026-03-19)
- **봉봉뉴스** 기능 추가
  - `/bbnews`: 관리자가 텍스트 입력 시 전체 구독자에게 DM 발송
  - `/bbuplist`: 카테고리별 서버 구독자 목록 확인 (관리자 전용)
  - `/bbup`에 봉봉뉴스 구독 옵션 추가
- **시황 구독 세분화**: `market_kr` (한국증시만) / `market_us` (미국증시만) 분리 지원
- **Playwright 브라우저 싱글턴**: 재사용으로 startup 비용 제거
- `cleanup` 함수 30초 루프 → `on_ready` 1회 실행으로 변경
- `sync_commands.py`, `injury_scraper.py` 제거

#### v1.4 (2026-03-18)
- **코드 품질 전반 개선**
  - `storage.py` JSON 원자적 쓰기 (`os.replace`) — 쓰다 크래시 나도 파일 보존
  - `_load_json`/`_save_json` 공용화 — market/ark 중복 제거
  - `notify_loop` 클로저 버그 수정 (기본 인자 바인딩)
  - `market_loop`/`ark_loop` 정각 매칭 → 범위 비교(±2분), 간격 60s → 30s
  - 공유 `aiohttp.ClientSession` 도입 (`on_ready` 생성, `on_close` 해제)
- **인터랙션 안정성**: `bbtt`/`bbf1`/`bblineup`/`bbmk`/`bbark` defer 만료(10062) 처리 추가
- **run.bat**: `PYTHONIOENCODING=utf-8` 설정 — 이모지/한글 로그 인코딩 오류 수정
- **GUILD_ID 제거**: 글로벌 커맨드 등록으로 전환 (전체 서버 지원)

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
  - 기준금리(연방기금·한국은행) / 금·은·WTI / BTC·ETH·USDT 시총
  - 주말 발송 스킵
- **ARK ETF 매매 내역** 기능 추가 (`/bbark`, `bbup ark`)
  - 매일 07:00 KST 전일 매매 내역 자동 DM
  - 주말 발송 스킵
- `/bbdm` interaction 만료(404) 버그 수정
- **코드 최적화**: `_send_dms` helper, `reply_error` helper, ARK fetch 단일 gather

#### v1.1
- `/bbtt` 상대팀 현황 + 토트넘 기준 EPL 순위표 (±3팀) 동시 표시
- `/bbtt` 상대현황/순위/라인업/H2H 4개 API 병렬 호출
- `notify_loop` ICS fetch 병렬화 (`asyncio.gather`)
- `bot.py` `import asyncio` 누락 버그 수정

#### v1.0
- **Sofascore → football-data.org 교체** (비공식 API 의존 제거)
- `/bbtime` → `/bbtt` 리네임 + 기능 확장 (결과/폼/H2H/라인업)
- `/bblineup` 신규: 홈/어웨이 양 팀 풀 라인업 + 등번호 + 포메이션
- `logging` 도입, `utils/` 패키지 분리, API 캐시 추가

---

### Phase 2 — Claude (2026-03-10)

#### v0.9
- bot.py 1000줄 → config / utils / commands / bot 4파일 분리
- /bblast 제거 (Sofascore 403 오류)

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
- F1 세션 타입 구분, /bbf1 · /bbtime 추가
- 경기 결과 자동 채널 발송 (result_loop)

---

### Phase 1 — GPT (2026-03-04 ~ 2026-03-09)

#### v0.4
- Sofascore API 라인업 조회 기능

#### v0.3
- F1 ICS 캘린더 파싱 및 DM 알림 추가

#### v0.2
- /bbup, /bbdown 커맨드, 토트넘 경기 DM 알림

#### v0.1
- 초기 봇 구성 (Python + discord.py, venv, run.bat)
