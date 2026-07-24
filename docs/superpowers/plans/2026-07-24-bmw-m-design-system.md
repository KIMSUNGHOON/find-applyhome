# BMW M 디자인 시스템 적용 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 스캐너 UI 를 BMW M 마케팅 사이트의 시각 언어(순흑 캔버스, heavy/light 타이포 대비, radius 0, M 삼색 스트라이프)로 교체한다. 기능은 하나도 바꾸지 않는다.

**Architecture:** `static/index.html` 한 파일만 바꾼다. CSS 를 토큰 기반으로 전면 교체하고, HTML 골격을 밴드 구조로 재구성하며, JS 렌더링 함수가 만들어내는 마크업의 클래스명을 새 시스템에 맞춘다. JS 의 계산·집계·이벤트 로직은 손대지 않는다.

**Tech Stack:** 바닐라 HTML/CSS/JS. 웹폰트 없음. 파이썬 변경 없음.

선행 스펙: `docs/superpowers/specs/2026-07-24-bmw-m-design-system-design.md`

## Global Constraints

- **파이썬 파일을 한 줄도 고치지 않는다.** `applyhome.py`, `grid.py`, `scanner.py`, `server.py`, `app.py` 는 그대로다.
- **기존 테스트 86건이 그대로 통과해야 한다** (라이브 2건 skip). 깨지면 범위를 벗어난 것이다.
- **기능 변경 금지.** 스캔 로직, 판정, 라인→타입 유추, 교차 검증, CSV, 재시도, 중단이 모두 이전과 동일하게 동작해야 한다.
- **웹폰트 CDN 금지.** 폰트 스택은 `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Apple SD Gothic Neo", sans-serif`.
- **인라인 hex 금지.** 모든 색은 CSS 변수를 참조한다.
- **radius 0 전면 적용.** 이 화면에는 원형 아이콘 버튼이 없어 `rounded.full` 예외가 발생하지 않는다.
- **본문 weight 는 300 을 넘지 않고, 디스플레이는 700 아래로 내리지 않는다.**
- **라이트 모드 제거.** `@media (prefers-color-scheme: dark)` 블록을 모두 없앤다. BMW M 은 라이트 모드 표면이 없다.
- 한글에는 대문자가 없다. 한글은 weight + 자간으로, 영문·숫자 라벨(`SCAN`, `SEARCH`, `CSV`, `84A`)만 대문자 + 1.5px 트래킹.

## 토큰 표 (Task 1 에서 정의, 이후 전 Task 가 참조)

```
--canvas          #000000    --on-dark      #ffffff
--surface-soft    #0d0d0d    --body-strong  #e6e6e6
--surface-card    #1a1a1a    --body         #bbbbbb
--surface-elev    #262626    --muted        #7e7e7e
--cell-idle       #141414    --hairline     #3c3c3c

--m-blue-light    #0066b1    --data-empty    #e22718
--m-blue-dark     #1c69d4    --data-special  #1c69d4
--m-red           #e22718    --data-general  #6e6e6e
                             --data-error    #f4b400
```

## File Structure

| 파일 | 변경 |
|---|---|
| `static/index.html` | CSS 전면 교체, HTML 골격 재구성, 렌더링 함수의 마크업 조정 |

다른 파일은 건드리지 않는다.

---

### Task 1: 토큰·타이포·골격

**Files:**
- Modify: `static/index.html` (`<style>` 블록 전체 = 7~78행, `<body>` 골격 = 80~112행)

**Interfaces:**
- Consumes: 없음
- Produces: CSS 변수 전체, 유틸 클래스 `.label`(14px/700/1.5px 대문자), `.caption`(12px/400/0.5px muted), `.hide`. 밴드 구조 `<section class="band">`. 버튼 클래스 `.btn`, 입력 클래스 `.input`. Task 2·3 이 이 클래스들을 쓴다

- [ ] **Step 1: `<style>` 블록을 통째로 교체한다**

`static/index.html` 의 `<style>` 부터 `</style>` 까지(7~78행)를 아래로 바꾼다:

```html
<style>
  :root {
    --canvas:#000000; --surface-soft:#0d0d0d; --surface-card:#1a1a1a;
    --surface-elev:#262626; --cell-idle:#141414; --hairline:#3c3c3c;
    --on-dark:#ffffff; --body-strong:#e6e6e6; --body:#bbbbbb; --muted:#7e7e7e;
    --m-blue-light:#0066b1; --m-blue-dark:#1c69d4; --m-red:#e22718;
    --data-empty:#e22718; --data-special:#1c69d4; --data-general:#6e6e6e; --data-error:#f4b400;
    --band:96px;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--canvas); color: var(--body);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Apple SD Gothic Neo", sans-serif;
    font-weight: 300; font-size: 16px; line-height: 1.5;
  }

  /* M 삼색 — 브랜드 마커 전용. 버튼이나 표면 채우기로 쓰지 않는다. */
  .m-stripe {
    height: 4px;
    background: linear-gradient(90deg,
      var(--m-blue-light) 0 33.33%, var(--m-blue-dark) 33.33% 66.66%, var(--m-red) 66.66% 100%);
  }

  .wrap { padding: 0 40px; }
  .band { padding-top: var(--band); }
  .band:first-of-type { padding-top: 56px; }

  h1 { margin: 0; font-size: 56px; font-weight: 700; line-height: 1.0;
       letter-spacing: -0.5px; color: var(--on-dark); }
  h2 { margin: 0 0 24px; font-size: 32px; font-weight: 700; line-height: 1.15;
       letter-spacing: -0.3px; color: var(--on-dark); }
  h3 { margin: 0 0 12px; font-size: 20px; font-weight: 700; color: var(--on-dark); }
  .lead { margin: 16px 0 0; font-size: 16px; font-weight: 300; color: var(--body); max-width: 720px; }

  /* 영문·숫자 라벨 전용. 한글에는 대문자가 없어 굵기와 자간으로 처리한다. */
  .label { font-size: 14px; font-weight: 700; letter-spacing: 1.5px;
           text-transform: uppercase; color: var(--on-dark); }
  .step { display: flex; align-items: baseline; gap: 12px; margin-bottom: 24px; }
  .step-no { font-size: 14px; font-weight: 700; letter-spacing: 1.5px; color: var(--muted); }
  .step-name { font-size: 14px; font-weight: 700; letter-spacing: 1.5px; color: var(--on-dark); }
  .caption { font-size: 12px; font-weight: 400; letter-spacing: 0.5px; color: var(--muted); }
  .status { font-size: 14px; font-weight: 300; color: var(--body); }
  .hide { display: none !important; }

  .btn {
    appearance: none; background: transparent; color: var(--on-dark);
    border: 1px solid var(--on-dark); border-radius: 0;
    height: 48px; padding: 0 32px;
    font-family: inherit; font-size: 14px; font-weight: 700; letter-spacing: 1.5px;
    text-transform: uppercase; cursor: pointer;
  }
  .btn[disabled] { opacity: .35; cursor: default; }

  .input, select.input {
    appearance: none; background: var(--surface-card); color: var(--on-dark);
    border: 1px solid var(--hairline); border-radius: 0;
    height: 48px; padding: 0 16px;
    font-family: inherit; font-size: 16px; font-weight: 300;
  }
  .input:focus { outline: none; border-color: var(--on-dark); }
  select.input { padding-right: 32px; }

  .row { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }

  /* 검색 결과 — category-tab. 라디오는 숨기고 좌측 2px 바로 선택을 나타낸다. */
  #results { margin-top: 24px; max-height: 300px; overflow-y: auto; }
  .pick { display: block; padding: 12px 0 12px 14px; border-left: 2px solid transparent;
          border-bottom: 1px solid var(--hairline); color: var(--body); cursor: pointer; }
  .pick input { position: absolute; opacity: 0; pointer-events: none; }
  .pick.on { border-left-color: var(--on-dark); color: var(--on-dark); }
  .pick-name { font-size: 16px; font-weight: 700; }
  .pick-meta { display: block; margin-top: 2px; font-size: 12px; font-weight: 300;
               letter-spacing: 0.5px; color: var(--muted); }

  .notice { border-left: 2px solid var(--data-error); background: var(--surface-soft);
            padding: 16px 20px; font-size: 14px; font-weight: 300; color: var(--body-strong);
            max-width: 980px; }

  /* spec-cell 그리드 */
  .specs { display: grid; gap: 1px; background: var(--hairline);
           grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); border: 1px solid var(--hairline); }
  .spec { background: var(--surface-soft); padding: 24px; }
  .spec-val { font-size: 32px; font-weight: 700; line-height: 1; color: var(--on-dark); }
  .spec-sub { margin-top: 4px; font-size: 12px; font-weight: 300; color: var(--muted); }
  .spec-key { margin-top: 12px; font-size: 14px; font-weight: 700; letter-spacing: 1.5px;
              color: var(--body); }
  .spec.total { background: var(--surface-card); }
  .spec-warn { margin-bottom: 16px; border-left: 2px solid var(--data-error);
               background: var(--surface-soft); padding: 12px 16px;
               font-size: 14px; font-weight: 300; color: var(--body-strong); }

  /* 격자 — 이 화면의 주인공 */
  #grids { display: flex; flex-wrap: wrap; gap: 40px; align-items: flex-start; }
  .dong { margin: 0; }
  table.grid { border-collapse: separate; border-spacing: 2px; }
  table.grid th { font-size: 12px; font-weight: 300; color: var(--muted); padding: 0 2px 4px; }
  table.grid th.type { font-size: 14px; font-weight: 700; letter-spacing: 1.5px;
                       color: var(--body); padding: 0 2px 6px; }
  /* 호수가 아예 없는 자리는 <td> 가 비어 있다 (.cell 요소 자체가 없다).
     청약홈 미등록 = 조합원·임대 물량이라는 의미 있는 정보이므로 td:empty 에 직접 색을 준다. */
  table.grid td:empty { background: var(--cell-idle); }
  .cell { width: 30px; height: 24px; border: 0; border-radius: 0; padding: 0;
          background: var(--cell-idle); cursor: pointer; line-height: 1;
          font-family: inherit; font-size: 11px; font-weight: 700; color: transparent; }
  .cell.info    { background: var(--data-general); color: var(--on-dark); }
  .cell.info.supply-s { background: var(--data-special); }
  .cell.info.supply-g { background: var(--data-general); }
  .cell.empty   { background: var(--data-empty); color: transparent; }
  .cell.error   { background: var(--data-error); color: transparent; }
  .flat { display: flex; flex-wrap: wrap; gap: 2px; }
  .flat .cell { width: 52px; color: var(--on-dark); }

  .legend { flex-basis: 100%; margin-top: 8px; font-size: 12px; font-weight: 400;
            letter-spacing: 0.5px; color: var(--muted); }
  .swatch { display: inline-block; width: 10px; height: 10px; vertical-align: -1px;
            margin: 0 4px 0 16px; }
  .legend > span:first-child .swatch, .legend .swatch:first-child { margin-left: 0; }

  /* 목록 */
  table.list { border-collapse: collapse; width: 100%; max-width: 820px; }
  table.list th { text-align: left; padding: 8px 12px 8px 0; border-bottom: 1px solid var(--hairline);
                  font-size: 14px; font-weight: 700; letter-spacing: 1.5px; color: var(--muted); }
  table.list td { padding: 8px 12px 8px 0; border-bottom: 1px solid var(--hairline);
                  font-size: 14px; font-weight: 300; color: var(--body-strong); }

  .actions { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; margin-bottom: 24px; }
  .link { color: var(--on-dark); text-decoration: none; font-size: 14px; font-weight: 700;
          letter-spacing: 1.5px; text-transform: uppercase; border-bottom: 1px solid var(--on-dark);
          padding-bottom: 2px; }

  /* 상세 — 화면 하단 고정 */
  #detail:not(:empty) { position: sticky; bottom: 0; background: var(--surface-card);
            border-top: 1px solid var(--hairline); padding: 16px 40px;
            max-height: 34vh; overflow-y: auto; margin-top: var(--band); }
  #detail .dt { font-size: 20px; font-weight: 700; color: var(--on-dark); }
  #detail .fields { display: grid; gap: 2px 24px; margin-top: 8px;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
  #detail .fields div { font-size: 14px; font-weight: 300; color: var(--body-strong); }
  #detail .fields span { display: inline-block; min-width: 116px; font-size: 12px;
            font-weight: 400; letter-spacing: 0.5px; color: var(--muted); }

  footer { margin-top: var(--band); border-top: 1px solid var(--hairline);
           padding: 32px 40px 64px; }

  @media (max-width: 768px) {
    .wrap, #detail:not(:empty), footer { padding-left: 20px; padding-right: 20px; }
    h1 { font-size: 36px; }
    h2 { font-size: 24px; }
    :root { --band: 56px; }
  }
</style>
```

- [ ] **Step 2: `<body>` 골격을 밴드 구조로 교체한다**

`<h1>` 부터 `<div id="detail"></div>` 까지(80~112행)를 아래로 바꾼다:

```html
<div class="m-stripe"></div>

<div class="wrap">

<section class="band">
  <h1>청약홈 미계약 세대 스캐너</h1>
  <p class="lead">단지를 고르면 전 동·전 호의 분양권 정보 등록 여부를 한 번에 확인합니다.</p>
</section>

<section class="band">
  <div class="step"><span class="step-no">01</span><span class="step-name">단지 찾기</span></div>
  <form id="search-form" class="row">
    <input id="q" class="input" placeholder="단지명 (예: 상봉 센트럴)" size="26" autofocus>
    <select id="area" class="input">
      <option value="">시도 전체</option>
    </select>
    <button type="submit" class="btn">Search</button>
  </form>
  <div id="results"></div>
  <div id="search-status" class="status" style="margin-top:12px"></div>
  <button id="more" class="btn hide" type="button" style="margin-top:16px">More</button>
</section>

<section class="band">
  <div class="step"><span class="step-no">02</span><span class="step-name">스캔</span></div>
  <div class="row">
    <button id="scan-button" class="btn" disabled>Scan</button>
    <button id="stop-button" class="btn hide">Stop</button>
    <span id="progress" class="status"></span>
  </div>
</section>

<section class="band hide" id="notice-band">
  <div class="notice" id="notice">
    이 결과는 청약홈에 분양권 정보가 등록되지 않은 세대입니다.
    미계약·부적격 세대일 가능성이 높으나, 사업주체의 등록 지연일 수도 있으므로 참고용으로만 활용하세요.
  </div>
</section>

<section class="band" id="summary-band"><div id="summary"></div></section>
<section class="band"><div id="grids"></div></section>
<section class="band"><div id="empty-list"></div></section>

</div>

<div id="detail"></div>

<footer class="caption">
  청약홈 「분양권 정보(전매제한 등)」 페이지의 공개 데이터를 조회합니다. 참고용으로만 활용하세요.
</footer>
```

- [ ] **Step 3: 안내 배너 토글 대상을 밴드로 바꾼다**

`onMeta` 첫 줄의 `el("notice").classList.remove("hide");` 를 아래로 바꾼다.
배너 자체가 아니라 밴드를 토글해야 96px 여백이 함께 사라진다:

```javascript
  el("notice-band").classList.remove("hide");
```

스캔 시작 시 감추는 쪽도 맞춘다. `scan-button` 클릭 핸들러의 `el("notice").classList.add("hide");` 를 바꾼다:

```javascript
  el("notice-band").classList.add("hide");
```

- [ ] **Step 4: 브라우저에서 골격을 확인한다**

```bash
python3 app.py
```

Expected:
- 페이지 최상단에 파랑→파랑→빨강 4px 스트라이프가 보인다
- 배경이 순흑, 타이틀이 56px 굵은 흰 글씨
- `01 단지 찾기` / `02 스캔` 단계 라벨이 대문자 자간으로 보인다
- `SEARCH` / `SCAN` 버튼이 사각형 외곽선 버튼이다
- 입력창이 어두운 회색 사각형이고, 클릭하면 테두리가 흰색으로 바뀐다

- [ ] **Step 5: 커밋**

```bash
git add static/index.html
git commit -m "feat: BMW M 토큰·타이포·밴드 골격 적용"
```

---

### Task 2: 폼·검색 결과·격자

**Files:**
- Modify: `static/index.html` (`renderResults`, `makeCell`, `buildGridTable`, `buildFlatList`, `renderLegend`)

**Interfaces:**
- Consumes: Task 1 의 `.pick` / `.pick-name` / `.pick-meta` / `.cell` / `.legend` / `.swatch` 클래스
- Produces: 없음 (화면)

- [ ] **Step 1: 검색 결과를 category-tab 스타일로 바꾼다**

`renderResults` 의 `body.complexes.forEach((item) => { ... });` 블록 전체를 아래로 교체한다:

```javascript
  body.complexes.forEach((item) => {
    const label = document.createElement("label");
    label.className = "pick";

    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "complex";
    radio.addEventListener("change", () => {
      document.querySelectorAll(".pick.on").forEach((n) => n.classList.remove("on"));
      label.classList.add("on");
      state.complex = item;
      el("scan-button").disabled = false;
    });

    const name = document.createElement("span");
    name.className = "pick-name";
    name.textContent = item.name;

    const meta = document.createElement("span");
    meta.className = "pick-meta";
    meta.textContent = `공고 ${item.notice_date} · 당첨발표 ${item.winner_date} · ${item.house_manage_no}`;

    label.append(radio, name, meta);
    el("results").append(label);
  });
```

- [ ] **Step 2: 격자 헤더의 층 라벨을 정리한다**

`buildGridTable` 안에서 층 라벨을 만드는 부분을 찾는다:

```javascript
    const th = document.createElement("th");
    th.textContent = floor + "F";
    row.append(th);
```

이대로 두면 층 라벨이 라인 번호와 같은 스타일이 된다. 아래로 바꿔 오른쪽 정렬을 준다:

```javascript
    const th = document.createElement("th");
    th.textContent = floor + "F";
    th.style.textAlign = "right";
    row.append(th);
```

- [ ] **Step 3: 범례를 새 클래스로 바꾼다**

`renderLegend` 의 `legend.innerHTML = ...` 대입문을 아래로 교체한다:

```javascript
  legend.innerHTML =
    `<span class="swatch" style="background:var(--data-special)"></span>특별공급 ${special}` +
    `<span class="swatch" style="background:var(--data-general)"></span>일반공급 ${general}` +
    (unknown ? `<span class="swatch" style="background:var(--data-general)"></span>유형미상 ${unknown}` : "") +
    `<span class="swatch" style="background:var(--data-empty)"></span>정보없음 ${summary.empty}` +
    (summary.error ? `<span class="swatch" style="background:var(--data-error)"></span>조회실패 ${summary.error}` : "") +
    `<span class="swatch" style="background:var(--cell-idle)"></span>청약홈 미등록 (조합원·임대 등)` +
    `<br>색과 글자(특·일)는 그 세대 당첨자의 청약 유형입니다`;
```

빈 칸도 범례에 넣는다. `--cell-idle` 이 무엇을 뜻하는지 화면에서 설명되어야 한다.

- [ ] **Step 4: 브라우저에서 확인한다**

```bash
python3 app.py
```

`상봉 센트럴` 을 검색해 고르고 스캔한다.

Expected:
- 검색 결과에 라디오 동그라미가 보이지 않고, 고른 항목만 좌측에 흰 세로 바가 생기며 글자가 흰색이 된다
- 격자 칸이 사각형(모서리 둥글기 0)이고 2px 간격으로 떨어져 있다
- 미계약 칸이 빨강(`#e22718`), 특별공급이 파랑(`#1c69d4`), 일반공급이 회색(`#6e6e6e`)
- 빈 칸이 아주 어두운 회색(`#141414`)으로 자리가 보인다
- 범례에 빈 칸 설명이 포함된다

- [ ] **Step 5: 커밋**

```bash
git add static/index.html
git commit -m "feat: 검색 결과와 격자를 BMW M 스타일로 교체"
```

---

### Task 3: 현황표·목록·상세

**Files:**
- Modify: `static/index.html` (`renderSummary`, `renderEmptyList`, `renderActions`, `renderRetry`, `showDetail`)

**Interfaces:**
- Consumes: Task 1 의 `.specs` / `.spec` / `.spec-val` / `.spec-key` / `.spec-sub` / `.spec-warn` / `table.list` / `.actions` / `.link` / `.btn` / `#detail .fields`
- Produces: 없음 (최종 화면)

- [ ] **Step 1: 타입별 현황표를 spec-cell 그리드로 바꾼다**

`renderSummary` 안에서 **`const warnings = [];` 줄부터 함수의 닫는 `}` 까지**를 아래로 교체한다
(아래 코드가 `const warnings` 를 다시 선언하므로, 기존 선언을 남겨두면 중복 선언 오류가 난다).
표(`<table class="summary">`)를 버리고 spec 셀 그리드를 쓴다:

```javascript
  const warnings = [];
  const cells = sorted.map((type) => {
    const t = tally.get(type) || { scanned: 0, empty: 0 };
    const s = byType.get(type);
    if (s && s.total !== t.scanned) {
      warnings.push(`${shortType(type)} 공고 ${s.total} / 스캔 ${t.scanned}`);
    }
    const base = s ? s.total : t.scanned;
    const rate = base ? ((t.empty / base) * 100).toFixed(1) + "%" : "-";
    // 공고에 있는 타입은 서버가 계산해 보낸 값을, 스캔에서만 나온 타입은 여기서 계산한다
    const label = s ? s.short : shortType(type);
    const net = s ? s.net_area : netArea(type);
    return `<div class="spec">
      <div class="spec-val">${t.empty}</div>
      <div class="spec-sub">${base}세대 중 · ${rate}</div>
      <div class="spec-key">${label}</div>
      <div class="spec-sub">전용 ${fmtArea(net)}${s ? ` · 일반 ${s.general} / 특별 ${s.special}` : ""}</div>
    </div>`;
  });

  const totalEmpty = [...tally.values()].reduce((sum, t) => sum + t.empty, 0);
  const totalScanned = [...tally.values()].reduce((sum, t) => sum + t.scanned, 0);
  const totalSupply = supply ? supply.reduce((sum, s) => sum + s.total, 0) : totalScanned;
  const totalGeneral = supply ? supply.reduce((sum, s) => sum + s.general, 0) : 0;
  const totalSpecial = supply ? supply.reduce((sum, s) => sum + s.special, 0) : 0;
  const totalRate = totalSupply ? ((totalEmpty / totalSupply) * 100).toFixed(1) + "%" : "-";

  cells.push(`<div class="spec total">
      <div class="spec-val">${totalEmpty}</div>
      <div class="spec-sub">${totalSupply}세대 중 · ${totalRate}</div>
      <div class="spec-key">합계</div>
      <div class="spec-sub">${supply ? `일반 ${totalGeneral} / 특별 ${totalSpecial}` : "공고 대조 불가"}</div>
    </div>`);

  const warnHtml = warnings.length
    ? `<div class="spec-warn">${warnings.join(" · ")} — 라인과 타입의 대응이 단순하지 않은 단지일 수 있어
       타입별 집계가 정확하지 않을 수 있습니다.</div>`
    : "";

  el("summary").innerHTML =
    `<h2>타입별 미계약 현황</h2>` +
    `<div class="caption" style="margin:-16px 0 16px">${supply ? "공고 기준" : "공고 대조 불가 · 스캔 기준"}</div>` +
    warnHtml +
    `<div class="specs">${cells.join("")}</div>`;
}
```

각 셀은 미계약 건수를 32px 값으로 앞세운다. 이 화면에서 사용자가 찾는 숫자가 그것이다.

- [ ] **Step 2: 정보없음 목록의 제목과 표를 바꾼다**

`renderEmptyList` 의 마지막 `el("empty-list").innerHTML = ...` 대입문을 아래로 교체한다:

```javascript
  el("empty-list").innerHTML =
    `<h2>정보없음 ${empties.length}세대</h2>` +
    `<table class="list"><thead><tr><th>동</th><th>호</th><th>타입</th><th>전용</th></tr></thead>` +
    `<tbody>${rows}</tbody></table>`;
```

같은 함수의 "정보없음 세대가 없습니다" 분기도 바꾼다:

```javascript
  if (!empties.length) {
    el("empty-list").innerHTML = `<h2>정보없음 0세대</h2><p class="status">모든 세대에 분양권 정보가 등록되어 있습니다.</p>`;
    return;
  }
```

- [ ] **Step 3: CSV 링크와 재시도 버튼을 새 스타일로 바꾼다**

`renderActions` 를 아래로 교체한다:

```javascript
function renderActions(summary) {
  const bar = document.createElement("div");
  bar.className = "actions";
  if (state.token) {
    const a = document.createElement("a");
    a.className = "link";
    a.href = `/api/export?token=${state.token}`;
    a.setAttribute("download", "");
    a.textContent = "CSV Download";
    bar.append(a);
  }
  el("empty-list").prepend(bar);
  if (summary.error) renderRetry(summary, bar);
}
```

`renderRetry` 의 시그니처와 버튼 생성부를 바꾼다. 첫 두 줄과 마지막 줄을 아래로 교체한다:

```javascript
function renderRetry(summary, bar) {
  const button = document.createElement("button");
  button.className = "btn";
  button.textContent = `Retry ${summary.error}`;
```

그리고 `renderRetry` 의 마지막 줄 `el("empty-list").prepend(button);` 을 아래로 바꾼다:

```javascript
  bar.append(button);
```

`renderRetry` 안쪽 클릭 핸들러의 `button.textContent = "다시 시도하는 중…";` 은 아래로 바꾼다:

```javascript
    button.textContent = "Retrying…";
```

- [ ] **Step 4: 상세 패널 마크업을 바꾼다**

`showDetail` 의 세 개 `el("detail").innerHTML = ...` 대입문을 각각 아래로 교체한다.

조회 실패 분기:

```javascript
      el("detail").innerHTML = `<div class="dt">${dong}동 ${ho}호</div><div class="caption">조회 실패</div>`;
```

정보없음 분기:

```javascript
    el("detail").innerHTML =
      `<div class="dt">${dong}동 ${ho}호</div>` +
      `<div class="caption">정보없음 · 미계약·부적격 추정${parts.length ? " · " + parts.join(" · ") : ""}</div>`;
```

정보있음 분기 (함수 마지막):

```javascript
  el("detail").innerHTML = `<div class="dt">${dong}동 ${ho}호</div><div class="fields">${rows}</div>`;
```

- [ ] **Step 5: 브라우저에서 전체를 확인한다**

```bash
python3 app.py
```

`상봉 센트럴` 을 스캔한다.

Expected — 값은 이전과 같아야 한다:
- 현황표가 5개 타입 + 합계, 총 6개 spec 셀로 나온다
- 각 셀 맨 위 큰 숫자가 미계약 건수다 (84C 는 `6`, 합계는 `18`)
- 셀에 `84C` / `전용 84.67㎡ · 일반 23 / 특별 28` 이 들어 있다
- 경고가 뜨지 않는다
- 목록 제목이 `정보없음 18세대`, 컬럼이 `동 · 호 · 타입 · 전용`
- `CSV DOWNLOAD` 가 밑줄 링크로 보이고 눌러서 받아진다
- 칸을 클릭하면 하단에 상세가 뜬다

- [ ] **Step 6: 커밋**

```bash
git add static/index.html
git commit -m "feat: 현황표를 spec-cell 로, 목록·상세를 BMW M 스타일로 교체"
```

---

### Task 4: 검증과 문서

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: 전체
- Produces: 없음

- [ ] **Step 1: 파이썬 테스트가 그대로 통과하는지 확인한다**

Run: `python3 -m unittest discover -s tests`
Expected: PASS — 86개, skipped 2. 이 작업은 파이썬을 건드리지 않았으므로 반드시 통과해야 한다

- [ ] **Step 2: 파이썬 파일이 실제로 안 바뀌었는지 확인한다**

Run: `git diff --name-only HEAD~3 -- '*.py'`
Expected: 출력 없음 (빈 결과)

- [ ] **Step 3: 브라우저 콘솔에서 스타일 값을 검증한다**

```bash
python3 app.py
```

`상봉 센트럴` 스캔 후 개발자도구 콘솔에서 실행한다:

```javascript
const cs = (sel, prop) => getComputedStyle(document.querySelector(sel))[prop];
({
  미계약: cs('.cell.empty', 'backgroundColor'),
  특별: cs('.cell.info.supply-s', 'backgroundColor'),
  일반: cs('.cell.info.supply-g', 'backgroundColor'),
  빈칸: cs('table.grid td:empty', 'backgroundColor'),
  radius: cs('.cell', 'borderRadius'),
  본문weight: cs('body', 'fontWeight'),
  타이틀weight: cs('h1', 'fontWeight'),
  스트라이프: cs('.m-stripe', 'height'),
  칸수: [...document.querySelectorAll('.cell.empty')].length
})
```

Expected:
```
미계약: "rgb(226, 39, 24)"     특별: "rgb(28, 105, 212)"
일반: "rgb(110, 110, 110)"     빈칸: "rgb(20, 20, 20)"
radius: "0px"                  본문weight: "300"
타이틀weight: "700"            스트라이프: "4px"
칸수: 18
```

- [ ] **Step 4: 장위로 광폭 배치를 확인한다**

`장위 푸르지오` 를 스캔한다 (23개 동 1032세대, 약 1분).

Expected: 동 23개가 가로로 여러 줄에 배치되고, 현황표에 18개 타입 + 합계 셀이 나온다.
합계 셀의 보조 줄이 `일반 510 / 특별 522` 다.

- [ ] **Step 5: `README.md` 에 디자인 항목을 추가한다**

`## 구조` 절 바로 앞에 넣는다:

```markdown
## 화면

BMW M 마케팅 사이트의 디자인 시스템을 적용했다 — 순흑 캔버스, 굵은 디스플레이(700)와
가벼운 본문(300)의 대비, 모서리 없는 사각형, 상단의 M 삼색 스트라이프.

격자가 이 화면의 주인공이다. 칸 색이 세대 상태를 나타낸다.

| 칸 | 색 | 뜻 |
|---|---|---|
| 빨강 | `#e22718` | 정보없음 (미계약·부적격 추정) |
| 파랑 | `#1c69d4` | 정보있음 · 특별공급 |
| 회색 | `#6e6e6e` | 정보있음 · 일반공급 |
| 노랑 | `#f4b400` | 조회실패 |
| 아주 어두운 회색 | `#141414` | 청약홈 미등록 (조합원·임대 등 일반분양 외 물량) |

웹폰트는 쓰지 않는다. 시스템 폰트 스택으로 굵기 대비를 만들기 때문에 오프라인에서도 그대로 보인다.
```

- [ ] **Step 6: 커밋**

```bash
git add README.md
git commit -m "docs: 화면 디자인 설명 추가"
```

---

## 완료 기준

- [ ] `python3 -m unittest discover -s tests` 가 86건 통과한다 (라이브 2건 skip)
- [ ] `git diff --name-only -- '*.py'` 가 비어 있다 — 파이썬은 한 줄도 안 바뀌었다
- [ ] 페이지 최상단에 4px M 삼색 스트라이프가 있다
- [ ] 모든 요소의 border-radius 가 0px 다
- [ ] 격자 빈 칸이 `#141414` 로 자리가 보인다
- [ ] 데이터 색이 BMW 팔레트다 (미계약 `#e22718`, 특별 `#1c69d4`, 일반 `#6e6e6e`, 실패 `#f4b400`)
- [ ] 본문 weight 300, 타이틀 weight 700
- [ ] 상봉 스캔 결과가 이전과 동일하다 (242세대 / 정보없음 18건)
- [ ] CSV 를 내려받을 수 있다
- [ ] 라이트 모드 대응 CSS(`prefers-color-scheme`)가 남아 있지 않다
