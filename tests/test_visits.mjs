import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  LAST_VISIT_KEY, applyVisits, formatVisits, openStorage, readLastDate, saveLastDate,
} from "../public/visits.mjs";

const indexHtml = readFileSync(new URL("../public/index.html", import.meta.url), "utf8");

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, value),
    read: (key) => data.get(key),
  };
}

function brokenStorage() {
  return {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
  };
}

test("저장된 날짜가 없으면 빈 문자열이다", () => {
  assert.equal(readLastDate(memoryStorage()), "");
});

test("저장된 날짜를 읽는다", () => {
  const storage = memoryStorage({ [LAST_VISIT_KEY]: "2026-08-03" });
  assert.equal(readLastDate(storage), "2026-08-03");
});

test("저장소가 막혀 있어도 빈 문자열로 넘어간다", () => {
  assert.equal(readLastDate(brokenStorage()), "");
  assert.equal(saveLastDate(brokenStorage(), "2026-08-04"), false);
});

test("날짜를 저장한다", () => {
  const storage = memoryStorage();
  assert.equal(saveLastDate(storage, "2026-08-04"), true);
  assert.equal(storage.read(LAST_VISIT_KEY), "2026-08-04");
});

test("천 단위 쉼표를 넣어 표시한다", () => {
  assert.equal(
    formatVisits({ today: "2026-08-04", day: 12, total: 3456 }),
    "오늘 12 · 전체 3,456",
  );
});

test("숫자가 아니면 null 이다", () => {
  assert.equal(formatVisits({ today: null, day: null, total: null }), null);
  assert.equal(formatVisits(undefined), null);
});

test("셀 수 있었을 때만 날짜를 저장한다", () => {
  const storage = memoryStorage();
  const text = applyVisits(storage, { today: "2026-08-04", day: 12, total: 3456 });
  assert.equal(text, "오늘 12 · 전체 3,456");
  assert.equal(storage.read(LAST_VISIT_KEY), "2026-08-04");
});

test("세지 못했으면 날짜를 저장하지 않는다", () => {
  const storage = memoryStorage();
  assert.equal(applyVisits(storage, { today: null, day: null, total: null }), null);
  assert.equal(storage.read(LAST_VISIT_KEY), undefined);
});

test("footer 에 감춰진 방문자 span 이 있다", () => {
  const start = indexHtml.indexOf('<div class="footer-meta">');
  assert.notEqual(start, -1);
  const meta = indexHtml.slice(start, indexHtml.indexOf("</div>", start));
  assert.match(meta, /<span id="visits" class="hide">방문 <span id="visits-text"><\/span><\/span>/);
});

test("방문자 모듈을 불러와 페이지 로드 때 부른다", () => {
  assert.match(indexHtml, /from "\/visits\.mjs"/);
  assert.match(indexHtml, /\/api\/visits\?/);
});

test("저장소 접근이 막히면 null 을 돌려준다", () => {
  const blocked = { get localStorage() { throw new Error("SecurityError"); } };
  assert.equal(openStorage(blocked), null);
});

test("저장소가 없으면 읽기는 빈 문자열, 쓰기는 false 다", () => {
  assert.equal(readLastDate(null), "");
  assert.equal(saveLastDate(null, "2026-08-04"), false);
});

test("정상 창에서는 localStorage 를 그대로 돌려준다", () => {
  const storage = { getItem: () => null, setItem: () => {} };
  assert.equal(openStorage({ localStorage: storage }), storage);
});
