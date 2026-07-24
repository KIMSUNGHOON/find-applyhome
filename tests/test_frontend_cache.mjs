import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  POLL_DELAYS_MS, formatCheckedAt, hydrateState, mergeUnits,
  pollSharedSnapshot, selectUnitJobs, unitKey,
} from "../public/cache.mjs";

const snapshot = {
  cache: "partial",
  checked_at: 1784871000,
  meta: { total: 2, dongs: [{ name: "101", hos: ["201", "202"], grid: null }], supply: [] },
  units: [{ dong: "101", ho: "201", status: "info", fields: {}, checked_at: 1784871000 }],
  refresh: { topology: false, supply: false, all_units: false,
    units: [{ dong: "101", ho: "202" }] },
};

const indexHtml = readFileSync(new URL("../public/index.html", import.meta.url), "utf8");

test("snapshot을 기존 state 형태로 옮긴다", () => {
  const state = { meta: null, units: new Map() };
  hydrateState(state, snapshot);
  assert.equal(state.meta.total, 2);
  assert.equal(state.units.get("101\u0000201").status, "info");
});

test("partial은 저장되지 않은 호실만 선택한다", () => {
  const jobs = [{ dong: "101", ho: "201" }, { dong: "101", ho: "202" }];
  assert.deepEqual(selectUnitJobs(snapshot, jobs), [{ dong: "101", ho: "202" }]);
});

test("all_units는 현재 topology 전체를 선택한다", () => {
  const body = structuredClone(snapshot);
  body.cache = "stale";
  body.refresh.all_units = true;
  const jobs = [{ dong: "101", ho: "201" }, { dong: "101", ho: "202" }];
  assert.deepEqual(selectUnitJobs(body, jobs), jobs);
});

test("fresh는 호실 요청을 만들지 않는다", () => {
  const body = structuredClone(snapshot);
  body.cache = "fresh";
  body.refresh.units = [];
  const jobs = [{ dong: "101", ho: "201" }, { dong: "101", ho: "202" }];
  assert.deepEqual(selectUnitJobs(body, jobs), []);
});

test("stale은 서버가 지정한 호실만 선택한다", () => {
  const body = structuredClone(snapshot);
  body.cache = "stale";
  body.refresh.units = [{ dong: "101", ho: "201" }];
  const jobs = [{ dong: "101", ho: "201" }, { dong: "101", ho: "202" }];
  assert.deepEqual(selectUnitJobs(body, jobs), [{ dong: "101", ho: "201" }]);
});

test("공유 결과는 0.5, 1, 2초 순서로 polling한다", async () => {
  const waits = [];
  const bodies = [{ checked_at: 1 }, { checked_at: 2 }];
  const found = await pollSharedSnapshot(
    async () => bodies.shift(),
    (body) => body.checked_at === 2,
    async (delay) => waits.push(delay),
  );
  assert.equal(found.checked_at, 2);
  assert.deepEqual(waits, POLL_DELAYS_MS.slice(0, 2));
});

test("checked_at이 없으면 표시 문자열이 비어 있다", () => {
  assert.equal(formatCheckedAt(null), "");
  assert.equal(unitKey("101", "201"), "101\u0000201");
});

test("페이지는 저장 결과를 먼저 그리고 서버 지정 호실만 갱신한다", () => {
  assert.match(indexHtml, /<script type="module">/);
  const cacheRequest = indexHtml.indexOf('getJson("/api/cache"');
  const storedRender = indexHtml.indexOf("renderStoredSnapshot(snapshot)", cacheRequest);
  const topologyRefresh = indexHtml.indexOf("fetchTopology(hm, pb)", storedRender);
  const unitSelection = indexHtml.indexOf("selectUnitJobs(snapshot, allJobs)", topologyRefresh);
  assert.ok(cacheRequest >= 0, "cache snapshot request is wired");
  assert.ok(storedRender > cacheRequest, "stored snapshot renders after loading");
  assert.ok(topologyRefresh > storedRender, "network refresh starts after stored render");
  assert.ok(unitSelection > topologyRefresh, "server-directed unit selection is used");
  assert.match(indexHtml, /state\.units\.set\(unitKey\(unit\.dong, unit\.ho\), unit\)/);
});
