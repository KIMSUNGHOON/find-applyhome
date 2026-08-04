# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

청약홈 「분양권 정보」 페이지를 전수 조회해 분양권 정보가 등록되지 않은(=미계약 추정) 세대를 찾는 도구다.
제품 설명과 판정 근거는 `README.md` 에 있다.

## 명령어

의존성이 없다. Python 은 표준 라이브러리만, 브라우저는 내장 API 만 쓴다.
빌드·린트·포매터 설정도 없다 (`requirements.txt`·`pyproject.toml`·`package.json` 모두 없음).

```bash
python3 app.py                                          # 로컬 실행 → http://127.0.0.1:8765 (브라우저 자동 열림)
python3 -m unittest discover -s tests                   # Python 145건 (라이브 2건 skip)
node --test tests/*.mjs                                 # 프런트엔드 54건
python3 -m unittest tests.test_grid -v                  # 파일 하나
python3 -m unittest tests.test_grid.BuildGridTest.test_층은_내림차순_라인은_오름차순이다   # 테스트 하나
node --test tests/test_visits.mjs                       # 프런트엔드 파일 하나
APPLYHOME_LIVE=1 python3 -m unittest tests.test_live -v # 청약홈에 실제로 붙는 회귀 테스트
```

**두 스위트를 모두 돌려야 한다.** `discover` 는 `.mjs` 를 못 보므로 Python 만 돌리면 프런트엔드 회귀를 놓친다.

라이브 테스트가 깨지면 코드가 아니라 청약홈 데이터가 갱신된 쪽을 먼저 의심하고
`tests/test_live.py` 의 `EXPECTED_EMPTY_101` 을 갱신한다.

## 아키텍처

### 계층 — 네트워크는 한 곳에만

| 파일 | 책임 |
|---|---|
| `applyhome.py` | 청약홈 호출·응답 파싱. **네트워크를 다루는 유일한 곳** |
| `grid.py` | 호수 → 층·라인 격자, 주택형 축약·전용면적 추출. 순수 함수 |
| `api/_cache.py` | Upstash Redis REST 공유 캐시. 회로 차단기·잠금·방문자 집계 |
| `api/_lib.py` | 엔드포인트 로직. `parse_qs` 결과를 받아 `(HTTP 상태, dict)` 를 돌려준다 |
| `server.py` / `api/*.py` | 전송 껍데기. 로컬 서버와 Vercel 함수가 같은 `_lib` 를 호출한다 |
| `public/index.html` | UI 전체 + **스캔 오케스트레이션** (단일 파일, HTML+CSS+JS) |
| `public/cache.mjs` · `public/visits.mjs` | 브라우저 쪽 순수 로직. DOM 을 만지지 않아 `node --test` 로 검증된다 |

`_lib` 함수는 HTTP 객체를 만지지 않는다. 그래서 서버를 띄우지 않고 `tests/test_api.py` 처럼 직접 호출해 테스트한다.

`applyhome.py` 와 `grid.py` 는 저장소 루트에 있고 `api/` 로 복제하지 않는다.
`_lib.py` 가 `sys.path` 에 루트를, `server.py` 가 `api/` 를 넣어 양쪽에서 같은 코드를 import 한다.

### 스캔 루프는 서버가 아니라 브라우저에 있다

서버 엔드포인트는 **세대 1건씩만 처리하는 무상태 조회**다. 전수 스캔의 진행·집계·중단·CSV 생성은 전부
`public/index.html` 이 한다. Vercel 서버리스가 긴 연결(SSE)을 유지하지 못하고 인스턴스 간 메모리를
공유하지 않기 때문이다 — **서버 쪽에 스캔 상태를 두는 설계로 되돌리지 말 것.**

동시성 제어도 브라우저에 있다 (`CONCURRENCY`, `runPool`). 여기에 `setTimeout` 요청 간격을
넣지 말 것 — 브라우저가 백그라운드 탭 타이머를 1초로 묶어 스캔이 4배 느려진다 (실측 15초 → 62초).

### 새 엔드포인트를 추가할 때 (세 곳 + 정적 자원이면 네 곳)

1. `api/_lib.py` 에 `(status, dict)` 를 돌려주는 함수
2. `_lib.ROUTES` 에 경로 등록
3. `api/<name>.py` 껍데기 — **소문자 `handler` 클래스 필수** (Vercel 규약)
4. 새 `.mjs` 를 추가한다면 **`server.py` 에 정적 서빙 분기도 더한다**

4번을 빠뜨리면 로컬에서 404 가 나고, ES 모듈 import 가 404 면 `<script type="module">` **전체**가
죽어서 검색·스캔·CSV 까지 멈춘다. `tests/test_server_search.py` 의
`test_index가_import하는_모듈이_모두_서빙된다` 가 이 부류를 잡는다.

### Vercel 규약

- `api/` 의 `.py` 파일 하나가 함수 하나가 된다. `_` 로 시작하는 파일은 함수로 변환되지 않는다
  (`_lib.py`·`_cache.py` 가 그래서 공용 코드다)
- `public/` 은 정적으로 자동 서빙된다. **로컬 `server.py` 는 자동이 아니라 하드코딩 분기다**
- 설정은 `vercel.json`. Redis 는 `UPSTASH_REDIS_REST_URL`·`UPSTASH_REDIS_REST_TOKEN` 두 환경변수로 붙는다

## 이 코드베이스의 규칙

**파싱은 위치가 아니라 라벨 기준으로.** `_label_pairs` 가 `라벨, 값` 순서로 늘어선 `<td>` 목록에서
라벨로 값을 찾는다. 청약홈이 행 순서를 바꿔도 깨지지 않게 하려는 것이니 인덱스 접근으로 되돌리지 말 것.

**판정 기준은 청약홈 스크립트와 동일하게.** 상세 응답의 `id="houseManageNo"` 텍스트가 비면 `empty`(정보없음)다.
손으로 동·호수를 찍는 것과 결과가 같아야 한다는 것이 이 도구의 신뢰 근거다.

**개별 실패가 전수 스캔을 멈추면 안 된다.** `_lib.unit` 은 조회가 실패해도 `200` + `status="error"` 를
돌려주고, `_lib.pblanc` 은 `supply=None`, `_lib.visits` 는 세 값을 모두 `None` 으로 삼킨다.
캐시와 카운터도 마찬가지로 실패하면 조용히 degrade 한다 — 새 엔드포인트도 이 원칙을 따른다.

**Redis 키는 서버 시계·서버 상수에서만 만든다.** 클라이언트가 보낸 값이 키 조립에 들어가면 안 된다
(`count_visit` 의 `last` 가 비교에만 쓰이는 이유). `_part()` 로 길이·제어문자를 검증하고 URL 인코딩한다.

**KST 는 고정 +9 로 계산한다.** Vercel 함수는 UTC 로 돈다. 그냥 두면 한국 사용자에게 "오늘" 이
오전 9시에 바뀐다. 한국은 서머타임이 없어 `datetime.timezone(timedelta(hours=9))` 가 정확하다.

**청약홈은 공공 사이트다.** 동시 요청 수와 재시도(`applyhome.RETRIES`, 0.5s → 1s → 2s 백오프)를
보수적으로 잡아 두었다. 늘리지 말 것.

**한국어로 쓴다.** docstring·주석·테스트 메서드 이름(`test_한글_문장`)·UI 문구·에러 메시지 전부.
주석은 "무엇"이 아니라 "왜"를 적는다 (기존 주석들이 그렇게 되어 있다).

**테스트는 저장된 응답이나 대역으로.** `tests/fixtures/` 의 실제 청약홈 HTML·JSON 을 쓰고,
Redis 는 `FakeTransport` 대역이 파이프라인 명령을 그대로 기록한다. 네트워크를 타는 것은 `test_live.py` 뿐이다.
프런트엔드 테스트는 `index.html` 을 텍스트로 읽어 마크업 계약을 검증하기도 한다.

## 로컬 개발에서 알아둘 것

**로컬에는 Redis 가 없는 것이 정상이다.** `python3 app.py` 로 띄우면 공유 캐시는 `disabled` 로
직접 조회하고, footer 의 방문자 수는 **보이지 않는다.** 고장이 아니다.

## 문서 규약

기능 하나마다 설계 문서와 단계별 계획을 남긴다.

- `docs/superpowers/specs/YYYY-MM-DD-<슬러그>-design.md` — 배경·대안 비교·결정·받아들인 부정확성
- `docs/superpowers/plans/YYYY-MM-DD-<슬러그>.md` — 체크박스 단위 구현 단계

동작을 바꾸면 `README.md` 의 해당 서술도 함께 고친다. 특히 `### 공유 캐시 연결` 절의
저장 내용 고지와 `## 테스트` 절의 건수는 코드와 어긋나기 쉬우니 실측값으로 갱신한다.
