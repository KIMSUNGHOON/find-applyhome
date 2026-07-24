# Footer Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 페이지 footer에 청약홈 데이터 출처, 공개 GitHub 저장소, 개발자 프로필을 안전하고 절제된 형태로 표시한다.

**Architecture:** 기존 `public/index.html`의 footer markup과 동일 파일의 CSS만 확장한다. Node built-in test가 최종 HTML 계약을 검증하며, 애플리케이션 로직·캐시 API·Redis schema에는 손대지 않는다.

**Tech Stack:** HTML5, existing vanilla CSS, Node.js built-in test runner, Python `unittest`

## Global Constraints

- 데이터 출처 URL은 `https://www.applyhome.co.kr/rs/rsa/selectResaleListView.do`다.
- 저장소 URL은 `https://github.com/KIMSUNGHOON/find-applyhome`이다.
- 개발자 표시는 `Seonghun Kim · @KIMSUNGHOON`, 링크는 `https://github.com/KIMSUNGHOON`이다.
- 이메일은 표시하지 않는다.
- 외부 링크는 `target="_blank"`와 `rel="noopener noreferrer"`를 모두 사용한다.
- 기존 footer의 hairline, 어두운 배경, `caption` 계층과 모바일 레이아웃을 유지한다.
- 별도 About band, 카드, 배지, 아이콘, 애니메이션, 새 색상·서체·의존성은 추가하지 않는다.
- 캐시 API, freshness 정책, Redis schema, 검색·스캔·CSV 동작은 변경하지 않는다.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `public/index.html` | footer content, link semantics, restrained responsive styling |
| `tests/test_frontend_cache.mjs` | rendered HTML contract for copy, URLs, and external-link safety |
| `README.md` | final observed Node test count only |

### Task 1: Footer provenance, safe links, and regression verification

**Files:**
- Modify: `public/index.html:155-162,210-212`
- Modify: `tests/test_frontend_cache.mjs`
- Modify: `README.md:130`

**Interfaces:**
- Consumes: existing `indexHtml` fixture in `tests/test_frontend_cache.mjs`, existing `footer.caption` visual language
- Produces: three public provenance links with fixed copy and secure external-link attributes

- [ ] **Step 1: Write the failing footer contract test**

Append the following test to `tests/test_frontend_cache.mjs` before editing production HTML:

```javascript
test("footer는 출처 저장소 개발자를 안전한 외부 링크로 표시한다", () => {
  const start = indexHtml.indexOf('<footer class="caption">');
  const end = indexHtml.indexOf("</footer>", start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const footer = indexHtml.slice(start, end + "</footer>".length);

  const expected = [
    ["https://www.applyhome.co.kr/rs/rsa/selectResaleListView.do",
      "청약홈 「분양권 정보(전매제한 등)」"],
    ["https://github.com/KIMSUNGHOON/find-applyhome",
      "KIMSUNGHOON/find-applyhome"],
    ["https://github.com/KIMSUNGHOON",
      "Seonghun Kim · @KIMSUNGHOON"],
  ];

  for (const [href, label] of expected) {
    const escaped = href.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const anchor = footer.match(new RegExp(`<a[^>]+href="${escaped}"[^>]*>`));
    assert.ok(anchor, `missing footer link: ${href}`);
    assert.match(anchor[0], /target="_blank"/);
    assert.match(anchor[0], /rel="noopener noreferrer"/);
    assert.match(footer, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }

  assert.match(footer, /공개 데이터를 조회합니다\. 참고용으로만 활용하세요\./);
  assert.doesNotMatch(footer, /sunghoonk@gmail\.com/);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
node --test --test-name-pattern="footer는" tests/test_frontend_cache.mjs
```

Expected: the new test fails because the repository and developer links are absent; unrelated tests are skipped by the name filter.

- [ ] **Step 3: Add the minimal footer markup**

Replace the current footer body in `public/index.html` with:

```html
<footer class="caption">
  <p class="footer-source">
    데이터 출처:
    <a href="https://www.applyhome.co.kr/rs/rsa/selectResaleListView.do"
       target="_blank" rel="noopener noreferrer">청약홈 「분양권 정보(전매제한 등)」</a>의
    공개 데이터를 조회합니다. 참고용으로만 활용하세요.
  </p>
  <div class="footer-meta">
    <span>저장소 <a href="https://github.com/KIMSUNGHOON/find-applyhome"
      target="_blank" rel="noopener noreferrer">KIMSUNGHOON/find-applyhome</a></span>
    <span>개발자 <a href="https://github.com/KIMSUNGHOON"
      target="_blank" rel="noopener noreferrer">Seonghun Kim · @KIMSUNGHOON</a></span>
  </div>
</footer>
```

Do not add email, Upstash, Vercel, Redis, or internal deployment information.

- [ ] **Step 4: Add minimal responsive footer styling**

Immediately after the existing `footer` rule in `public/index.html`, add:

```css
  .footer-source { margin: 0; }
  footer a {
    color: var(--body-strong);
    text-decoration-color: var(--hairline);
    text-underline-offset: 3px;
  }
  footer a:hover { color: var(--on-dark); text-decoration-color: currentColor; }
  footer a:focus-visible { outline: 1px solid var(--on-dark); outline-offset: 3px; }
  .footer-meta {
    display: flex; flex-wrap: wrap; gap: 8px 24px;
    margin-top: 10px;
  }
```

These rules reuse existing tokens, retain native semantics, and wrap without a new breakpoint.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run:

```bash
node --test --test-name-pattern="footer는" tests/test_frontend_cache.mjs
```

Expected: 1 matching test passes; other tests are reported skipped by the name filter.

- [ ] **Step 6: Run frontend syntax and full Node verification**

Run:

```bash
node --check public/cache.mjs
sed -n '/<script type="module">/,/<\/script>/p' public/index.html | sed '1d;$d' | node --check --input-type=module
node --test tests/*.mjs
```

Expected: both syntax commands exit 0; all 41 Node tests pass.

- [ ] **Step 7: Update the documented observed Node count**

In `README.md`, replace:

```text
프런트엔드 테스트는 40건을 실행한다.
```

with:

```text
프런트엔드 테스트는 41건을 실행한다.
```

Leave the documented Python count at 124 with 2 live tests skipped.

- [ ] **Step 8: Run full Python, fail-open, static, and security verification**

Run:

```bash
python3 -m unittest discover -s tests -v
env -u UPSTASH_REDIS_REST_URL -u UPSTASH_REDIS_REST_TOKEN \
  python3 -m unittest tests.test_server_search -v
python3 -m py_compile api/_cache.py api/_lib.py api/cache.py
python3 -m json.tool vercel.json
git diff --check
rg -n 'UPSTASH_REDIS_REST_TOKEN|UPSTASH_REDIS_REST_URL' public
rg -n 'Bearer [A-Za-z0-9_-]{16,}|upstash\.io' api public tests README.md
```

Expected:

- Python: 124 tests pass with 2 opt-in live tests skipped.
- fail-open server: 7 tests pass with both Upstash variables unset.
- compile and JSON validation exit 0.
- diff check has no output.
- both security scans have no matches. Because `rg` exits 1 for no matches, treat that exit code as the expected clean result.

- [ ] **Step 9: Commit and push the footer unit**

Run:

```bash
git add public/index.html tests/test_frontend_cache.mjs README.md
git commit -m "feat: footer에 출처와 개발자 정보 추가"
git push origin feat/vercel-deploy
```

Expected: one implementation commit is created, the worktree is clean, and the remote feature branch reaches the same HEAD. Do not create, reopen, merge, or otherwise mutate a pull request.

- [ ] **Step 10: Verify deployment status without exposing credentials**

Run:

```bash
gh api repos/KIMSUNGHOON/find-applyhome/commits/HEAD/status
```

Replace `HEAD` with the committed full SHA before executing. Expected: Vercel status becomes `success` and provides the protected Preview deployment target. Do not print or retrieve Upstash secrets. If the Preview remains SSO-protected and no authenticated browser/CLI surface is available, record A/B cache and rendered footer smoke as an explicit external verification gap.

---

## Completion Criteria

- Exact source, repository, and developer links appear in the footer.
- Every external link has `target="_blank"` and `rel="noopener noreferrer"`.
- No email or cache/deployment credential is present in public files.
- Footer remains secondary, responsive, keyboard-visible, and consistent with the existing visual system.
- 41 Node tests and 124 Python tests pass; 2 live Python tests remain intentionally skipped.
- Vercel build succeeds or the precise external blocker is recorded.
