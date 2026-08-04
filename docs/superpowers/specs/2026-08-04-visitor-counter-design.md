# Visitor Counter Design

작성일: 2026-08-04
선행 스펙: [2026-07-24-shared-scan-cache-design.md](2026-07-24-shared-scan-cache-design.md)

## Goal

이 도구를 지금까지 몇 명이 썼고 오늘은 몇 명이 왔는지 페이지에서 볼 수 있게 한다.
숫자는 결과 화면보다 앞서지 않으며, 스캔 동작에 어떤 영향도 주지 않는다.

## Counting Rule

화면에 보이는 값은 두 개다 — **오늘 방문자**와 **누적 방문자**.

1회로 치는 기준은 **브라우저당 하루 1회**다. 브라우저는 마지막으로 카운트된 날짜를
`localStorage["visits:last"]` 에 적어두고, 페이지 로드 때 그 값을 서버에 보낸다.
서버가 자기가 아는 KST 오늘과 비교해 다르면 1을 더하고, 같으면 현재 값만 돌려준다.

새로고침이나 스캔 중 재시도로 숫자가 부풀지 않는다. 라벨이 `방문` 인 이상 페이지뷰가 아니라
사람 수에 가까운 값이어야 한다는 판단이다.

## Data Flow and Contract

요청은 페이지 로드당 한 번, 왕복 한 번이다.

```
GET /api/visits?last=2026-08-03
  → 200 {"today": "2026-08-04", "day": 12, "total": 3456}

GET /api/visits?last=2026-08-04
  → 200 {"today": "2026-08-04", "day": 12, "total": 3456}
```

브라우저는 **`total` 이 숫자로 왔을 때만** 응답의 `today` 를 `localStorage` 에 저장한다.
Redis 가 죽어 세지 못한 방문을 세었다고 기록하면, 그날 안에 Redis 가 살아나도 다시 세지 않게 된다.

서버가 날짜의 유일한 출처이므로 브라우저 시계가 틀어져 있어도 집계가 어긋나지 않는다.

### Redis schema

| 키 | 만료 | 내용 |
|---|---|---|
| `visits:total` | 없음 | 누적 방문자 |
| `visits:day:YYYY-MM-DD` | 48시간 | 그날의 방문자. 지난 날짜는 저절로 사라진다 |

날짜 키는 `visit_day_key(date)` 가 만든다. 인자는 `kst_date()` 가 돌려준 값만 받는다.

파이프라인은 신규·재방문 구분 없이 **항상 같은 모양**이다. `n` 만 달라진다.

```
INCRBY visits:total            n
INCRBY visits:day:<KST 오늘>   n
EXPIRE visits:day:<KST 오늘>   172800
```

`n` 은 `last` 가 KST 오늘과 같으면 `0`, 아니면 `1` 이다. `INCRBY 0` 은 값을 바꾸지 않고
현재 값만 돌려주므로 읽기와 쓰기가 한 경로로 합쳐진다. `EXPIRE` 를 매번 걸어 오늘 키의
수명을 마지막 접촉 기준 48시간으로 유지한다.

### Key safety

**Redis 키는 서버 시계에서만 나온다.** 클라이언트가 보낸 `last` 는 서버의 KST 오늘과
문자열 비교에만 쓰이고 키 조립에는 들어가지 않는다. `last` 에 어떤 값이 와도 키를 오염시킬 수 없고,
형식이 어긋나면 단순히 "오늘이 아님" 으로 판정되어 `n=1` 이 된다.

`last` 는 32자를 넘으면 빈 문자열로 취급하고 그 밖의 검증은 하지 않는다.
비교에만 쓰이므로 그 이상이 필요 없다.

## Time Zone

`kst_date(now)` 가 UTC epoch 를 KST 날짜 문자열로 바꾼다.
Vercel 함수는 UTC 로 돌기 때문에 그냥 두면 한국 사용자에게 "오늘" 이 오전 9시에 바뀐다.

한국은 서머타임이 없으므로 `datetime.timezone(datetime.timedelta(hours=9))` 고정 오프셋이
정확하다. 표준 라이브러리만 쓴다는 저장소 원칙에도 맞는다.

## Placement and Visual Treatment

footer 의 `.footer-meta` 안에 span 하나를 더한다. 지금 `저장소` · `개발자` 가 늘어선 그 줄이다.

```
저장소 KIMSUNGHOON/find-applyhome
개발자 Seonghun Kim · @KIMSUNGHOON
방문 오늘 12 · 전체 3,456
```

기존 `caption` 계층(12px · `--muted`)을 그대로 쓴다. 새 색·테두리·아이콘·애니메이션을 넣지 않는다.
숫자는 천 단위 구분 쉼표를 넣는다.

카운터가 메타정보라는 성격이 footer 와 맞고, `.footer-meta` 가 span 나열이라 항목이 하나 빠져도
레이아웃이 흔들리지 않는다. 히어로나 상단 바에 두면 제품 진술 자리를 카운터가 차지하게 된다.

M 삼색 스트라이프와 세대 격자가 화면의 유일한 시각적 서명으로 남는다.

## Failure Handling

**숫자를 못 구하면 아무것도 보여주지 않는다.**

| 상황 | 응답 | 화면 |
|---|---|---|
| `CACHE is None` (로컬 실행 등 env 없음) | `200` · 세 값 모두 `null` | 숨김 |
| Redis 호출 실패 · 회로 차단기 열림 | `200` · 세 값 모두 `null` | 숨김 |
| `fetch` 자체 실패 | — | 숨김 |
| `localStorage` 접근 차단 (사생활 보호 모드) | 정상 | 정상 표시 (매번 `n=1` 이 될 뿐) |

응답은 어떤 경우에도 `200` 이고 모양이 하나다. 프런트는 `total` 이 숫자인지만 본다.
span 은 처음부터 감춰진 채로 두고 숫자가 도착했을 때만 드러내므로 실패 경로에 별도 처리가 없다.

`—` 나 `0` 을 대신 띄우지 않는다. **로컬 개발에서는 Redis 가 없는 것이 정상이고**,
`python3 app.py` 로 띄울 때마다 고장난 것처럼 보이는 UI 를 만들 이유가 없다.

카운터는 스캔과 완전히 독립된 요청이며 예외를 전부 삼킨다. 카운터가 죽어도 스캔은 영향받지 않는다 —
`_lib.unit` 과 `_lib.pblanc` 이 지켜온 태도와 같다.

## Accepted Inaccuracies

표시용 숫자이므로 다음은 고치지 않는다.

- `localStorage` 를 지우거나 다른 브라우저로 오면 다시 세어진다. 보안 경계가 아니다
- JS 를 실행하는 크롤러는 매번 빈 저장소로 오므로 매번 세어진다. 거르려면 IP 나 User-Agent
  판별이 필요한데 표시용 숫자에 비해 대가가 크다. JS 를 실행하지 않는 크롤러는 요청 자체를 보내지 않는다
- Redis 에서 오늘 키가 사라진 직후 재방문자에게 `오늘 0` 이 잠깐 보일 수 있다.
  TTL 이 48시간이라 실제로는 거의 생기지 않고 다음 날 저절로 맞아떨어진다

## Files and Boundaries

| 파일 | 역할 | 구분 |
|---|---|---|
| `api/_cache.py` | `kst_date()` · `visit_day_key()` · `CacheStore.count_visit()` | 수정 |
| `api/_lib.py` | `visits(query)`, `ROUTES` 에 `/api/visits` 등록 | 수정 |
| `api/visits.py` | Vercel 진입점. 기존 진입점 5개와 같은 형태 | 추가 |
| `public/visits.mjs` | 저장된 날짜 읽기·쓰기, 표시 문자열 조립 | 추가 |
| `public/index.html` | footer span, 로드 시 호출 | 수정 |
| `README.md` | 구조표에 새 파일, 테스트 건수 실측값 | 수정 |

브라우저 쪽 순수 로직을 `visits.mjs` 로 빼는 이유는 `cache.mjs` 와 같다 — `node --test` 로
검증하기 위해서다. `index.html` 에는 DOM 을 만지는 몇 줄만 남긴다.

스캔 캐시 schema, freshness 정책, 검색·스캔·CSV 동작은 건드리지 않는다.
`visits:` 키는 `scan:v1:` 과 이름공간이 겹치지 않는다.

## Verification

**`tests/test_cache.py`** — 가짜 transport 가 받은 명령을 그대로 검사한다.

- `kst_date` 경계: UTC `2026-08-03 14:59:59` → `2026-08-03`, `15:00:00` → `2026-08-04`
- `last` 가 어제면 `INCRBY visits:total 1` · `INCRBY visits:day:<오늘> 1` · `EXPIRE … 172800`
- `last` 가 오늘이면 같은 명령에 `n` 만 `0`
- `last` 가 없거나 형식이 어긋나면 `n=1` 이고 키는 오염되지 않는다
- transport 가 `CacheUnavailable` 을 던지면 예외가 새지 않고 `None`
- Redis 가 형식이 어긋난 응답을 주면 `None`

**`tests/test_api.py`** — 서버 없이 `_lib.visits()` 를 직접 부른다.

- `CACHE is None` 이면 `200` 에 `today`·`day`·`total` 이 모두 `None`
- 정상이면 세 값이 채워진 응답
- `last` 파라미터가 없어도 동작한다

**`tests/test_visits.mjs`** (신규, `node --test`)

- 저장된 날짜 읽기 — 없으면 빈 문자열
- `localStorage` 가 예외를 던져도 빈 문자열로 넘어간다
- `{day: 12, total: 3456}` → `오늘 12 · 전체 3,456`
- `total` 이 숫자가 아니면 `null` — 호출한 쪽은 span 을 감춘 채로 둔다
- `total` 이 숫자가 아니면 `localStorage` 에 날짜를 쓰지 않는다
- `index.html` footer 에 `id="visits"` span 이 있고 기본이 감춰져 있다 —
  기존 footer 마크업 테스트와 같은 방식

전체 회귀로 `python3 -m unittest discover -s tests` 와 `node --test tests/*.mjs` 를 돌리고,
README 의 테스트 건수를 실제 결과로 갱신한다.
