# Vercel 배포 — 설계

작성일: 2026-07-24
선행 스펙: [2026-07-24-applyhome-vacancy-scanner-design.md](2026-07-24-applyhome-vacancy-scanner-design.md)

## 1. 배경

지금 이 도구는 `python3 app.py` 로 로컬에서만 돌아간다. 대상 사용자는 청약 관심자이지 개발자가 아니다.

- Windows 에는 Python 이 없다. 설치하고 PATH 를 잡고 터미널을 여는 것부터 막힌다
- macOS 에서 `python3` 를 치면 Xcode 명령행 도구 설치 창이 뜬다. 수 GB 다
- 그 전에 터미널을 열 줄 모르는 사람이 대부분이다

브라우저에서 URL 만 열면 쓸 수 있어야 한다.

### 1.1 왜 서버가 반드시 필요한가

브라우저에서 청약홈을 직접 호출하면 CORS 에 막힌다. 청약홈은 `Access-Control-Allow-Origin` 을 주지 않는다.
**이것이 지금 로컬 Python 서버가 존재하는 이유이며, 정적 호스팅(GitHub Pages)만으로는 불가능한 이유다.**

### 1.2 플랫폼 선택

| | 첫 접속 대기 | 판단 |
|---|---|---|
| Render 무료 | 15분 유휴 후 잠들어 **30~60초** | 비개발자 대상에는 치명적. 그 전에 창을 닫는다 |
| Hugging Face Spaces | 48시간 유휴 후 잠듦 | 신규 계정은 Docker Space 생성에 유료 플랜을 요구한다는 보고가 있어 불확실 |
| **Vercel Hobby** | **없음** (서버리스) | 개인 용도 무료. 이것으로 간다 |

## 2. 서버리스가 강제하는 구조 변경

Vercel 함수는 **오래 열려 있는 연결을 유지하지 못하고, 인스턴스 간 메모리를 공유하지 않는다.**
지금 구조의 두 부분이 그대로는 동작하지 않는다.

| 지금 | 문제 | 대응 |
|---|---|---|
| `/api/scan` 이 SSE 로 15~64초 연결 유지 | 서버리스 함수 실행 시간과 충돌 | **스캔 루프를 브라우저로 옮긴다.** 세대마다 짧은 요청 |
| `/api/export` 가 전역 `SCANS` 딕셔너리에서 결과를 꺼냄 | 인스턴스가 매번 달라 딕셔너리가 비어 있다 | **CSV 를 브라우저에서 만든다.** 이미 모든 결과를 갖고 있다 |

```
지금:   브라우저 ──SSE 1개 연결(64초)──> 서버 ──242회──> 청약홈
바꾼 뒤: 브라우저 ──242개 짧은 요청(각 1초)──> 서버 ──1회씩──> 청약홈
```

동시성 제어(동시 3개, 요청 완료 후 다음 요청)가 서버에서 브라우저로 이동한다.

## 3. Vercel Python 런타임 규약

확인한 사실이다.

- `api/` 디렉토리의 `.py` 파일이 각각 하나의 함수가 된다
- 각 파일은 `BaseHTTPRequestHandler` 를 상속한 **`handler`** 클래스를 정의해야 한다
  (현재 `server.py` 의 `Handler` 와 같은 구조라 이식이 수월하다)
- **`_` 로 시작하는 파일은 함수로 변환되지 않는다.** 공통 코드를 `api/_lib.py` 에 두면 된다
- `public/` 의 파일은 정적으로 자동 서빙된다
- 의존성이 없으므로 `requirements.txt` 는 두지 않는다

## 4. 파일 구조

```
api/
  _lib.py        공통 — 응답 헬퍼, 쿼리 파싱, 엔드포인트 로직
  search.py      GET /api/search
  dongs.py       GET /api/dongs      (신설)
  hos.py         GET /api/hos        (신설)
  unit.py        GET /api/unit
  pblanc.py      GET /api/pblanc     (신설)
applyhome.py     청약홈 파싱 — 그대로
grid.py          격자·타입 축약 — 그대로
server.py        로컬 실행용. 같은 로직을 라우팅
app.py           로컬 진입점
public/
  index.html     UI (static/ 에서 이동)
vercel.json      빌드 설정
```

`applyhome.py` 와 `grid.py` 는 저장소 루트에 남긴다. `api/_lib.py` 가 `sys.path` 에 루트를 추가해 import 한다.
`server.py` 와 Vercel 함수가 **같은 파싱 코드를 공유**해야 하므로 복제하지 않는다.

두 파일은 `vercel.json` 의 `excludeFiles` 에 들어가지 않으므로 함수 번들에 포함된다.
제외 대상은 테스트·문서·fixture 뿐이다.

**`scanner.py` 는 제거한다.** 스캔 오케스트레이션이 브라우저로 완전히 이동하므로 쓰이는 곳이 없다.
남겨두면 죽은 코드가 된다.

## 5. API

모두 `GET` 이며 JSON 을 반환한다.

| 엔드포인트 | 쿼리 | 응답 |
|---|---|---|
| `/api/search` | `name`, `area`, `sigungu`, `page` | `{complexes: [...], total: int}` |
| `/api/dongs` | `hm`, `pb` | `{dongs: [{sn: int, name: str}]}` |
| `/api/hos` | `hm`, `pb`, `sn` | `{hos: [str], grid: {...}\|null}` |
| `/api/unit` | `hm`, `pb`, `dong`, `ho` | `{dong, ho, status, fields}` |
| `/api/pblanc` | `hm`, `pb` | `{supply: [...]}` 또는 `{supply: null}` |

### 5.1 동·호 조회를 왜 두 엔드포인트로 나누는가

`scanner.scan_complex` 앞부분은 동 목록을 받고 **동마다** 호 목록을 받는다.
이것을 한 함수에 넣으면 동 개수만큼 청약홈을 순차 호출하게 된다.
장위(23개 동)는 24회라 3~4초지만, 동이 더 많은 단지에서는 서버리스 실행 시간 제한에 걸릴 수 있다.

**한 요청이 청약홈을 한 번만 부르도록 나눈다.** 각 함수가 1초 안에 끝나 어떤 제한에도 걸리지 않는다.

- `/api/dongs` → 동 목록 (청약홈 1회)
- `/api/hos` → 그 동의 호 목록 + `grid.build_grid` 결과 (청약홈 1회)

브라우저가 `/api/dongs` 를 먼저 부르고, 이어서 동마다 `/api/hos` 를 동시 3개로 부른다.
전체 작업 목록은 그 결과를 모아 만든다.

동 목록이 비면 `{"dongs": []}` 를 반환한다. 브라우저가 "아직 분양권 정보 미등록" 을 표시한다.
`grid` 는 호수 체계가 불규칙해 격자화할 수 없으면 `null` 이다 (지금과 같은 규칙).

### 5.2 오류 응답

청약홈 호출이 실패하면 `502` 와 `{"message": "..."}` 를 반환한다.
대기열(넷퍼넬) 응답은 `applyhome.BlockedError` 로 잡혀 같은 형태로 나간다.

`/api/unit` 만 예외다. 개별 세대 실패는 스캔을 멈추지 않아야 하므로
`200` 과 `{"status": "error"}` 를 반환한다. 브라우저가 실패 칸으로 표시하고 계속 진행한다.

## 6. 브라우저 스캔 루프

`scanner.py` 가 하던 일을 그대로 옮긴다.

```
1. /api/dongs 로 동 목록을 받는다
2. 동마다 /api/hos 를 동시 3개로 불러 호 목록과 격자를 받고, 빈 격자를 그린다
3. /api/pblanc 로 공고 정보를 받는다 (실패해도 스캔은 진행)
4. 전체 (동, 호) 목록에 대해 동시 3개로 /api/unit 을 호출한다
   - 각 워커는 현재 요청이 끝나야 다음 요청을 보낸다
   - 결과가 오는 대로 칸을 칠하고 진행률을 갱신한다
5. 끝나면 현황표·목록·범례를 그린다
```

2단계와 4단계가 같은 동시성 제어를 쓰므로, **작업 목록과 워커 함수를 받는 공용 러너 하나**로 구현한다.
같은 코드를 두 번 쓰지 않는다.

중단 버튼은 `state.aborted` 플래그를 세운다. 진행 중인 최대 3개 요청만 마무리하고 새 요청은 시작하지 않는다.

### 6.1 CSV

브라우저가 `state.units` 를 그대로 갖고 있으므로 서버가 필요 없다.
`Blob` 으로 만들어 `URL.createObjectURL` 로 내려받는다.

컬럼은 지금과 같다. Excel 호환을 위해 **UTF-8 BOM(`﻿`)을 앞에 붙인다.**
`server.build_csv` 의 컬럼 정의와 판정 라벨을 JS 로 옮긴다.

## 7. 청약홈 부하

서버리스는 상태가 없어 IP 별 제한을 걸기 어렵다. 현실적으로 할 수 있는 것은 두 가지다.

- 브라우저에서 **동시 3개**만 유지하고, 각 요청이 끝나야 다음 요청을 보낸다
- 고정 타이머는 두지 않는다. 백그라운드 탭의 타이머 제한 때문에 스캔이 15초에서 62초로 느려지는 것을 방지한다
- README 와 화면에 그 이유를 남긴다

완벽한 통제는 아니다. 다만 청약홈이 인증 없이 공개하는 조회 API 이고,
정상 사용 시 부하는 사람이 손으로 클릭하는 것과 같은 총량이다.

## 8. 로컬 실행 유지

`python3 app.py` 는 계속 동작한다. `server.py` 가 `api/_lib.py` 의 같은 로직을 라우팅하고
`public/index.html` 을 서빙한다. 프론트엔드는 배포본과 완전히 동일한 파일이다.

로컬과 배포본이 다른 코드를 타면 한쪽만 고치는 사고가 난다.

## 9. 테스트

구조가 바뀌는 부분의 테스트는 사라지고, 파싱 자산은 그대로 남는다.

| 파일 | 현재 | 이후 |
|---|---|---|
| `test_parse_list.py` | 5 | **5 유지** |
| `test_parse_dongho.py` | 7 | **7 유지** |
| `test_parse_detail.py` | 9 | **9 유지** |
| `test_grid.py` | 13 | **13 유지** |
| `test_pblanc.py` | 13 | **13 유지** |
| `test_server_search.py` | 6 | 유지하되 **수정**. `server.Handler` 가 `api/_lib.py` 로직을 라우팅하도록 바뀌므로 import 경로가 달라진다 |
| `test_scanner.py` | 13 | **삭제** — 모듈 제거 |
| `test_server_scan.py` | 5 | **삭제** — SSE 제거 |
| `test_export.py` | 13 | **축소** — `build_csv` 가 JS 로 가므로 `/api/unit` 테스트만 남긴다 |
| `test_live.py` | 2 | 유지. 스캔 루프 대신 `applyhome` 을 직접 호출해 같은 값을 검증 |
| 신규 `test_api.py` | — | `/api/dongs`, `/api/hos`, `/api/pblanc` 응답 형태 |

**핵심 파싱 47건(list 5 + dongho 7 + detail 9 + grid 13 + pblanc 13)은 손실 없이 유지된다.**

라이브 회귀 테스트는 `scanner.scan_complex` 를 쓰던 것을
`applyhome.list_dongs` → `list_hos` → `fetch_detail` 직접 호출로 바꾼다.
검증 값(상봉 101동 정보없음 10건)은 그대로다.

## 10. 배포 절차

1. 저장소에 `vercel.json` 과 `api/` 를 커밋하고 GitHub 에 푸시한다
2. 사용자가 vercel.com 에 가입하고 GitHub 저장소를 연결한다
3. 이후 푸시할 때마다 자동 배포된다

**CLI 인증이 없어 대신 배포해 줄 수는 없다.** 사용자가 웹에서 연결해야 한다.

`vercel.json`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "functions": {
    "api/**/*.py": {
      "excludeFiles": "{tests/**,docs/**,**/test_*.py}"
    }
  }
}
```

테스트와 문서, fixture 를 함수 번들에서 제외한다. fixture HTML 만 100KB 가 넘는다.

## 11. 비목표

- 사용자 계정, 즐겨찾기, 알림
- 서버측 결과 저장 (서버리스라 상태를 둘 곳이 없고, 필요하지도 않다)
- Render·HF Spaces 동시 지원 — 하나만 제대로 한다
