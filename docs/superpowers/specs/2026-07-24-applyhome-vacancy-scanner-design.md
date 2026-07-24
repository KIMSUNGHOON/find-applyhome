# 청약홈 미계약 세대 스캐너 — 설계

작성일: 2026-07-24

## 1. 배경

청약홈 「분양권 정보(전매제한 등) 안내」 페이지(`https://www.applyhome.co.kr/rs/rsa/selectResaleListView.do`)는
단지를 고른 뒤 **동과 호수를 하나씩 드롭다운으로 지정해야만** 해당 세대의 분양권 정보를 볼 수 있다.
세대 수가 수백인 단지에서 전체를 확인하려면 수백 번의 클릭이 필요하다.

이때 분양권 정보가 등록되지 않은 세대를 조회하면 청약홈이 다음 경고창을 띄운다
(페이지 인라인 스크립트, `selectResaleListView.do` 응답 1823행):

```js
alert("해당 [동:" + dongNo + ", 호:" + hoNo + "]에 대한 분양권 세부 정보가 없습니다.\n" +
      "단지의 전매제한 기간은 대표화면을 참고하시기 바랍니다.");
```

이 경고창이 뜨는 세대는 실무적으로 **미계약·부적격 처리로 계약이 체결되지 않은 세대**로 해석된다.
본 도구는 이 확인 작업을 전수 자동화한다.

### 1.1 사전 검증 결과 (2026-07-24 실측)

대상 페이지의 내부 API 4종이 인증 없이 동작함을 확인했다.

| 엔드포인트 | 메서드 | 입력 | 출력 |
|---|---|---|---|
| `/rs/rsa/selectResaleListView.do` | POST | `suplyAreaCode`, `siggList`, `houseNm`, `pageIndex` | 단지 목록 HTML |
| `/rs/rsa/selectDongList.do` | POST | `houseManageNo`, `pblancNo` | `{donglist:[{DONG_SN, DONG_NM}]}` |
| `/rs/rsa/selectHoList.do` | POST | `houseManageNo`, `pblancNo`, `dongsn` | `{holist:[{HO_SN, HO_CO}]}` |
| `/rs/rsa/selectResalePblancDetail.do` | POST | `houseManageNo`, `pblancNo`, `dongNo`, `hoNo` | 상세 HTML (팝업 본문) |

실측 사례 — **상봉 센트럴 아이파크**(`houseManageNo=2025000439`) 101동:

- 호 목록 119호 전수 조회에 19.5초 소요 (건당 0.16초, 직렬)
- 정보 있음 109호 / **정보 없음 10호** → `305, 502, 603, 1105, 1401, 1404, 1405, 2004, 2302, 2303`

호 목록에 존재하는 세대라도 상세 정보가 비어 있는 경우가 실재하며, 이것이 위 경고창의 조건이다.

## 2. 목표와 비목표

### 목표

- 단지명으로 검색해 대상 단지를 고른다.
- 그 단지의 **전 동·전 호를 전수 스캔**해 "정보 없음" 세대를 한 화면에 보여준다.
- 정보가 있는 세대는 상세 필드를 함께 수집해 확인할 수 있게 한다.
- 진행 상황을 실시간으로 보여준다.

### 비목표 (YAGNI)

- 지역(시도/시군구) 전체 일괄 스캔
- 변동 감시 및 알림
- 네이버 부동산·검색 링크 연동
- 데이터베이스, 로그인, 외부 배포
- 청약홈 계정을 요구하는 기능 일체

## 3. 판정 규칙

본 도구의 핵심이며, **청약홈 자체 스크립트와 동일한 조건**을 사용한다.

`selectResalePblancDetail.do` 응답에서 `id="houseManageNo"` 요소의 텍스트를 읽는다.

| 조건 | 판정 | 표기 |
|---|---|---|
| 텍스트가 빈 문자열 | `empty` | 정보없음 (미계약·부적격 추정) |
| 텍스트가 있음 | `info` | 정보있음 + 상세 15개 필드 |
| 요청 실패 / 파싱 불가 | `error` | 조회 실패 (재시도 대상) |

### 3.1 해석의 한계를 UI에 명시한다

`empty`는 "청약홈에 분양권 정보가 등록되지 않음"이라는 사실만을 의미한다.
미계약·부적격 외에 **사업주체가 계약 건을 아직 등록하지 않은 경우**에도 동일하게 비어 보인다.
따라서 도구는 사실(`정보없음`)을 표기하고 해석(`미계약·부적격 추정`)은 추정으로 병기하며,
결과 화면 상단에 다음 문구를 고정 노출한다.

> 이 결과는 청약홈에 분양권 정보가 등록되지 않은 세대입니다.
> 미계약·부적격 세대일 가능성이 높으나, 사업주체의 등록 지연일 수도 있으므로 참고용으로만 활용하세요.

## 4. 아키텍처

```
브라우저 (바닐라 JS · 단일 HTML)
   │
   │  localhost:8765
   ▼
로컬 서버 (Python 3.14 표준 라이브러리)
   ├ GET /                                        static/index.html
   ├ GET /api/search?name=&area=&sigungu=&page=   단지 검색       → JSON
   ├ GET /api/scan?hm=&pb=                        전수 스캔       → SSE 스트림
   ├ GET /api/unit?hm=&pb=&dong=&ho=&token=       세대 1건 재조회 → JSON
   └ GET /api/export?token=                       직전 스캔 결과  → CSV
   │
   │  HTTPS
   ▼
applyhome.co.kr
```

브라우저에서 청약홈으로 직접 요청하면 CORS에 막히므로 로컬 서버가 프록시 역할을 한다.

### 4.1 기술 선택

Python 3.14 **표준 라이브러리만** 사용한다 (`http.server`, `urllib.request`, `concurrent.futures`, `re`, `csv`, `json`).

- 설치 절차 없이 `python3 app.py` 한 줄로 실행된다.
- 하는 일이 정적 파일 서빙 + API 프록시 + 스트리밍뿐이라 프레임워크가 필요 없다.
- 개인용 로컬 도구이므로 `http.server`의 프로덕션 부적합성은 문제되지 않는다.
- 서버는 `127.0.0.1`에만 바인딩한다.

## 5. 모듈 구조

| 파일 | 책임 | 의존 |
|---|---|---|
| `applyhome.py` | 청약홈 API 4종 호출 + 응답 파싱 | 표준 라이브러리만 |
| `grid.py` | 호수 문자열 → 층·라인 격자 산출 (순수 함수) | 없음 |
| `scanner.py` | 단지 1개 전수 스캔, 동시성 제어, 진행 콜백 | `applyhome.py`, `grid.py` |
| `server.py` | HTTP 라우팅, SSE, CSV 생성 | `scanner.py` |
| `app.py` | 진입점 (서버 기동, 브라우저 자동 열기) | `server.py` |
| `static/index.html` | UI 전체 (검색·그리드·상세·CSV 버튼) | — |
| `tests/` | 파싱·판정 테스트 + fixture | `applyhome.py` |

파싱은 네트워크와 분리한다. 저장된 응답 fixture만으로 파싱·판정 전체를 테스트할 수 있어야 한다.

### 5.1 `applyhome.py` 인터페이스

```python
@dataclass(frozen=True)
class Complex:
    house_manage_no: str    # data-hmno
    pblanc_no: str          # data-pbno
    name: str               # data-honm
    notice_date: str        # 공고일
    winner_date: str        # 당첨자 발표일
    resale_limit: str       # 전매제한 요약 (공급유형별 문자열)

@dataclass(frozen=True)
class Dong:
    sn: int                 # DONG_SN — selectHoList 호출용
    name: str               # DONG_NM — selectResalePblancDetail 호출용

@dataclass(frozen=True)
class Ho:
    sn: int                 # HO_SN
    no: str                 # HO_CO

@dataclass(frozen=True)
class UnitDetail:
    dong: str
    ho: str
    status: str             # 'info' | 'empty' | 'error'
    fields: dict[str, str]  # status == 'info' 일 때만 채워짐

def search_complexes(name: str = "", area: str = "", sigungu: str = "",
                     page: int = 1) -> tuple[list[Complex], int]: ...
def list_dongs(hm: str, pb: str) -> list[Dong]: ...
def list_hos(hm: str, pb: str, dong_sn: int) -> list[Ho]: ...
def fetch_detail(hm: str, pb: str, dong_name: str, ho_no: str) -> UnitDetail: ...
```

`fetch_detail`이 수집하는 `fields` 키 15종 (라벨 기준 파싱):

```
주택관리번호, 주택명, 주택형, 공고일, 동수, 호수, 당첨자 발표일,
계약체결일, 추가입주 계약체결일, 입주예정, 공급유형, 지역,
특이사항, 전매제한, 분양금액(만원)
```

상세 응답은 `<td>라벨</td><td>값</td>` 쌍이 순차 배열된 구조다.
위치 인덱스가 아니라 **라벨 문자열로 값을 찾는다** — 청약홈이 행 순서를 바꿔도 깨지지 않게 한다.

`DONG_NM`(예: `"1001"`)과 `DONG_SN`(예: `1`)은 다른 값이다.
`selectHoList.do`에는 `DONG_SN`을, `selectResalePblancDetail.do`에는 `DONG_NM`을 넘겨야 한다.

### 5.2 `scanner.py` 인터페이스

```python
def scan_complex(hm: str, pb: str,
                 on_event: Callable[[str, dict], None],
                 stop: threading.Event) -> None: ...
```

호출 순서:

1. `list_dongs(hm, pb)` → 동 목록. 비어 있으면 `error` 이벤트로 "분양권 정보 미등록" 전달 후 종료.
2. 동별 `list_hos(...)` → 전체 `(동, 호)` 작업 목록 확정.
3. `meta` 이벤트로 총 세대 수와 동·호 구조를 먼저 전달 (프론트가 빈 그리드를 미리 그린다).
4. `ThreadPoolExecutor(max_workers=4)`로 `fetch_detail` 실행, 완료되는 대로 `unit` 이벤트 전달.
   10건마다 `progress` 이벤트를 함께 보낸다.
5. 전부 끝나면 `done` 이벤트.

`stop` 이벤트가 set되면 진행 중인 작업만 마치고 중단한다. set되는 경우는 두 가지다 —
SSE write 실패로 브라우저 연결이 끊긴 것을 감지했을 때, 그리고 사용자가 UI의 중단 버튼을 눌러
SSE 연결을 닫았을 때(같은 경로로 감지된다).

## 6. SSE 이벤트 규격

`GET /api/scan?hm=&pb=` 는 `text/event-stream`을 반환한다.

| event | data |
|---|---|
| `meta` | `{"name": str, "total": int, "dongs": [{"name": str, "hos": [str]}]}` |
| `unit` | `{"dong": str, "ho": str, "status": "info"\|"empty"\|"error", "fields": {...}}` |
| `progress` | `{"done": int, "total": int}` — 10건마다 |
| `done` | `{"total": int, "info": int, "empty": int, "error": int, "elapsed": float, "token": str}` |
| `error` | `{"message": str}` |

`done`의 `token`으로 `/api/export?token=...`을 호출해 CSV를 받는다.
스캔 결과는 서버 메모리에 마지막 1건만 보관한다.

## 7. 청약홈 서버 부하 관리

공공 사이트이므로 보수적으로 접근한다.

- 동시 요청 **최대 4개** (`ThreadPoolExecutor(max_workers=4)`)
- 요청 간 최소 간격 **0.1초** (워커별 sleep)
- 실패 시 지수 백오프 재시도 **최대 3회** (0.5s → 1s → 2s)
- 정상 `User-Agent`, `Referer: https://www.applyhome.co.kr/rs/rsa/selectResaleListView.do` 전송
- 타임아웃 20초

예상 소요: 312세대 기준 약 15~20초.

## 8. 에러 처리

| 상황 | 처리 |
|---|---|
| 개별 세대 조회 실패 (재시도 3회 소진) | `status: "error"`로 표기하고 스캔 계속. 완료 후 "조회 실패 N건 다시 시도" 버튼 노출. 버튼은 실패한 세대만 `/api/unit`으로 하나씩 다시 부르고, 보관 중인 스캔 결과도 갱신해 이어 받는 CSV에 반영한다 |
| 동/호 목록 응답이 JSON으로 파싱되지 않음 | 넷퍼넬(대기열) 또는 점검 페이지로 간주. `error` 이벤트 후 스캔 중단, 안내 문구 표시 |
| 동 목록이 빈 배열 | "이 단지는 아직 분양권 정보가 등록되지 않았습니다" 안내 |
| 검색 결과 0건 | "검색 결과가 없습니다" 안내 |
| 브라우저 연결 끊김 | SSE write 실패를 감지해 `stop` 이벤트 set, 워커 정리 |

## 9. UI 사양 (`static/index.html`)

단일 HTML 파일, 바닐라 JS, 외부 리소스 없음.

**검색 영역** — 단지명 입력(선택적으로 시도 필터) → 결과를 라디오 목록으로 표시.
각 항목에 단지명·주택관리번호·공고일·당첨자 발표일을 함께 보여준다. 페이지당 10건, 더 보기 방식.

**스캔 영역** — `[전체 스캔]` 버튼, 진행률 바(`done / total`), 경과 시간, 중단 버튼.

**결과 그리드** — 동별 블록. 가로축은 라인, 세로축은 층.

층과 라인은 호수 문자열에서 산출한다. **마지막 두 자리가 라인, 그 앞이 층**이다.
`"305"` → 3층 05라인, `"1105"` → 11층 05라인, `"201"` → 2층 01라인.

`■ 정보있음` / `● 정보없음` / `× 실패`로 칠하고, 범례에 각 건수를 표시한다.
호수가 세 자리 미만이거나 숫자가 아닌 세대가 하나라도 있는 동은 격자 산출을 포기하고
**단순 나열 목록으로 자동 대체**한다.

**상세 패널** — 칸을 클릭하면 그 세대의 15개 필드를 표로 보여준다.

**정보없음 목록** — 그리드 아래에 표로 나열한다. 이것이 사용자의 최종 산출물이다.

컬럼은 `동 / 호 / 주택형(참고)`다.
**`empty` 응답에는 값이 하나도 실려 오지 않는다** — 라벨만 있고 주택형·공급유형 칸이 전부 비어 있다.
따라서 주택형은 **같은 동·같은 라인(호수 끝 두 자리)의 `info` 세대에서 빌려와** 참고값으로 보여주고,
헤더에 `주택형(참고)`라고 명시한다. 같은 라인에 `info` 세대가 하나도 없으면 빈칸으로 둔다.

**고정 안내 문구** — 3.1절의 추정 관련 안내를 결과 영역 상단에 항상 노출한다.

**CSV 내보내기** — 컬럼: `동, 호, 판정, 주택형, 공급유형, 공고일, 당첨자 발표일, 계약체결일, 입주예정, 전매제한, 분양금액(만원)`.
Excel 호환을 위해 UTF-8 BOM을 붙인다.

## 10. 테스트 전략

`tests/`에 실제 응답을 fixture로 저장하고 네트워크 없이 검증한다.

| 테스트 | fixture | 검증 내용 |
|---|---|---|
| 단지 목록 파싱 | 서울 1페이지 HTML | 10건 추출, `hm`/`pb`/단지명/공고일 일치, 총건수 168 |
| 동 목록 파싱 | `selectDongList` JSON | `DONG_SN`/`DONG_NM` 매핑 |
| 호 목록 파싱 | `selectHoList` JSON | 호 개수와 값 |
| 상세 파싱 (정보있음) | 장위 푸르지오 마크원 1001동 201호 | `status == "info"`, 15개 필드 값 일치 |
| 상세 파싱 (정보없음) | 존재하지 않는 호수 응답 | `status == "empty"` |
| 라벨 순서 변경 내성 | 행 순서를 뒤섞은 fixture | 값이 여전히 정확히 매핑됨 |
| 층·라인 격자 산출 (정상) | `["201","305","1105"]` | 각각 (2층,01) (3층,05) (11층,05)로 산출 |
| 층·라인 격자 산출 (대체) | `["1","A2","305"]` 등 불규칙 | 격자 포기하고 나열 모드로 대체 |

**회귀 테스트 (네트워크 필요, 기본 skip)** — 상봉 센트럴 아이파크(`2025000439`) 101동 스캔 시
119세대 중 `empty` 10건이며 호수가 `305, 502, 603, 1105, 1401, 1404, 1405, 2004, 2302, 2303`과 일치.
2026-07-24 실측값이므로 청약홈 데이터가 갱신되면 달라질 수 있다. `--live` 플래그로만 실행한다.

## 11. 네이버 근거 조사 (2026-07-24 완료)

"정보없음 팝업 = 미계약·부적격"이라는 해석이 실제로 통용되는지 확인했다. **통용된다.**

네이버 블로그 글 두 건에서 같은 방법이 확인된다.

- 2025-08-29 — 판정 문구가 정확히 일치한다:
  > "'분양권 세부 정보가 없습니다.' 이렇게 팝업이 뜨면 계약이 안된거"
- 2025-09-17 (`m.blog.naver.com/startify/224012177936`) — 접근 경로를 명시한다:
  > "청약홈 → 청약소통방 → 분양권정보(전매제한 등) → apt선택"

이 도구의 판정 규칙(3절)은 청약홈 스크립트의 조건을 그대로 쓰므로, 위 커뮤니티 방법을 전수 자동화한 것과 같다.

**다만 3.1절의 한계는 그대로 유효하다.** 커뮤니티 글들은 "팝업 = 미계약"으로 단정하지만,
사업주체의 등록 지연 가능성을 배제한 근거는 어디에도 없다. 안내 문구는 현행대로 유지한다.

### 조사 방법에 대한 기록

`blog.naver.com`, `m.blog.naver.com`, `cafe.naver.com`은 크롤러와 브라우저 확장 양쪽에서 차단된다
(웹 검색 도구는 user agent 차단, Chrome 확장은 사이트 권한 차단). 네이버 본문은 읽을 수 없었고,
**구글 검색 결과의 스니펫**으로 위 인용을 확보했다. 추후 재조사 시 같은 경로를 쓰면 된다.

## 12. 파일 배치

```
applyhome/
├ app.py
├ server.py
├ scanner.py
├ grid.py
├ applyhome.py
├ README.md
├ static/
│  └ index.html
├ tests/
│  ├ fixtures/
│  └ test_*.py
└ docs/superpowers/specs/
   └ 2026-07-24-applyhome-vacancy-scanner-design.md
```
