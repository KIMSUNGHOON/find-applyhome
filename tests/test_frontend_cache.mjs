import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as cacheModule from "../public/cache.mjs";
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

test("페이지 scanComplex는 검증된 cache-first orchestration을 호출한다", () => {
  assert.match(indexHtml, /<script type="module">/);
  assert.match(indexHtml, /runCacheFirstRefresh,/);
  const scan = indexHtml.slice(
    indexHtml.indexOf("async function scanComplex"),
    indexHtml.indexOf('el("scan-button").addEventListener'),
  );
  assert.match(scan, /await runCacheFirstRefresh\(\{/);
});

test("cache-first orchestration은 저장 상태를 먼저 적용하고 새 topology로 정리한다", async () => {
  assert.equal(typeof cacheModule.runCacheFirstRefresh, "function");
  const body = structuredClone(snapshot);
  body.cache = "stale";
  body.meta = {
    total: 2,
    dongs: [{ name: "101", hos: ["201", "999"], grid: null }],
    supply: [],
  };
  body.units = [
    { dong: "101", ho: "201", status: "info", fields: {} },
    { dong: "101", ho: "999", status: "empty", fields: {} },
  ];
  body.refresh.topology = true;
  body.refresh.units = [{ dong: "101", ho: "202" }];

  const state = { meta: null, units: new Map(), cache: null, aborted: false };
  const events = [];
  const requested = [];
  await cacheModule.runCacheFirstRefresh({
    state,
    loadSnapshot: async () => body,
    fetchTopology: async () => {
      events.push("fetch-topology");
      return {
        total: 2,
        dongs: [{ name: "101", hos: ["201", "202"], grid: null }],
        supply: null,
      };
    },
    fetchSupply: async () => [],
    fetchUnit: async (job) => {
      requested.push(job);
      return { ...job, status: "empty", fields: {} };
    },
    runJobs: async (jobs, worker) => Promise.all(jobs.map(worker)),
    onStored: () => {
      events.push("stored");
      assert.equal(state.units.size, 2);
      assert.ok(state.units.has(unitKey("101", "999")));
    },
    onTopology: () => {
      events.push("topology");
      assert.equal(state.units.size, 1);
      assert.ok(!state.units.has(unitKey("101", "999")));
    },
    onUnit: (unit) => events.push(`unit:${unit.ho}`),
  });

  assert.deepEqual(events, ["stored", "fetch-topology", "topology", "unit:202"]);
  assert.deepEqual(requested, [{ dong: "101", ho: "202" }]);
  assert.deepEqual([...state.units.keys()].sort(), [
    unitKey("101", "201"), unitKey("101", "202"),
  ]);
});

test("cache 조회 실패는 현재 topology 전체를 직접 갱신한다", async () => {
  const state = { meta: null, units: new Map(), cache: null, aborted: false };
  const requested = [];
  let result;
  await assert.doesNotReject(async () => {
    result = await cacheModule.runCacheFirstRefresh({
      state,
      loadSnapshot: async () => { throw new Error("cache offline"); },
      fetchTopology: async () => ({
        total: 2,
        dongs: [{ name: "101", hos: ["201", "202"], grid: null }],
        supply: null,
      }),
      fetchSupply: async () => [],
      fetchUnit: async (job) => {
        requested.push(job);
        return { ...job, status: "info", fields: {} };
      },
      runJobs: async (jobs, worker) => Promise.all(jobs.map(worker)),
    });
  });

  assert.equal(result.snapshot.cache, "disabled");
  assert.deepEqual(requested, [
    { dong: "101", ho: "201" }, { dong: "101", ho: "202" },
  ]);
  assert.equal(state.units.size, 2);
});

test("빈 topology 갱신도 prune 뒤 화면 replay를 요청한다", async () => {
  const body = structuredClone(snapshot);
  body.cache = "stale";
  body.meta = {
    total: 1,
    dongs: [{ name: "101", hos: ["999"], grid: null }],
    supply: [],
  };
  body.units = [{ dong: "101", ho: "999", status: "empty", fields: {} }];
  body.refresh.topology = true;
  body.refresh.units = [];
  const state = { meta: null, units: new Map(), cache: null, aborted: false };
  let replayed = 0;

  const result = await cacheModule.runCacheFirstRefresh({
    state,
    loadSnapshot: async () => body,
    fetchTopology: async () => ({ total: 0, dongs: [], supply: null }),
    fetchSupply: async () => [],
    fetchUnit: async () => assert.fail("empty topology has no unit work"),
    runJobs: async (jobs, worker) => Promise.all(jobs.map(worker)),
    onTopology: () => {
      replayed += 1;
      assert.equal(state.units.size, 0);
    },
  });

  assert.equal(result.status, "empty");
  assert.equal(replayed, 1);
});
