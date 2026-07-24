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

function functionSource(name) {
  const marker = new RegExp(`(?:async\\s+)?function\\s+${name}\\s*\\(`);
  const match = marker.exec(indexHtml);
  assert.ok(match, `${name} function must exist`);
  const start = match.index;
  const bodyStart = indexHtml.indexOf("{", start);
  let depth = 0;
  for (let index = bodyStart; index < indexHtml.length; index += 1) {
    if (indexHtml[index] === "{") depth += 1;
    if (indexHtml[index] === "}") depth -= 1;
    if (depth === 0) return indexHtml.slice(start, index + 1);
  }
  assert.fail(`${name} function must have a complete body`);
}

function loadInlineFunction(name, dependencies = {}) {
  const names = Object.keys(dependencies);
  const values = Object.values(dependencies);
  const source = functionSource(name);
  return Function(...names, `"use strict"; ${source}; return ${name};`)(...values);
}

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

test("polling이 끝까지 최신값을 못 찾으면 null이다", async () => {
  const waits = [];
  const found = await pollSharedSnapshot(
    async () => ({ checked_at: 1 }),
    () => false,
    async (delay) => waits.push(delay),
  );
  assert.equal(found, null);
  assert.deepEqual(waits, POLL_DELAYS_MS);
});

test("새 snapshot 호실이 기존 Map 값을 교체한다", () => {
  const units = new Map([[unitKey("101", "201"), { status: "empty" }]]);
  mergeUnits(units, [{ dong: "101", ho: "201", status: "info", fields: {} }]);
  assert.equal(units.get(unitKey("101", "201")).status, "info");
});

test("getJson은 202 본문과 HTTP 상태를 반환한다", async () => {
  const fetch = async () => ({
    ok: false,
    status: 202,
    json: async () => ({ status: "refreshing", refreshing: true }),
  });
  const getJson = loadInlineFunction("getJson", { fetch });
  assert.deepEqual(await getJson("/api/unit", { dong: "101", ho: "201" }), {
    status: "refreshing", refreshing: true, http_status: 202,
  });
});

test("getJson은 202 외 non-OK 응답을 거부한다", async () => {
  const fetch = async () => ({
    ok: false,
    status: 503,
    json: async () => ({ message: "잠시 후 다시 시도하세요" }),
  });
  const getJson = loadInlineFunction("getJson", { fetch });
  await assert.rejects(
    getJson("/api/unit", { dong: "101", ho: "201" }),
    /잠시 후 다시 시도하세요/,
  );
});

test("refreshing 호실은 기존 checked_at보다 최신 공유 결과만 병합한다", async () => {
  const units = new Map([[unitKey("101", "201"), {
    dong: "101", ho: "201", status: "empty", fields: {}, checked_at: 10,
  }]]);
  const state = { units };
  const rendered = [];
  const snapshots = [
    { units: [{ dong: "101", ho: "201", status: "info", fields: {}, checked_at: 10 }] },
    { units: [{ dong: "101", ho: "201", status: "info", fields: {}, checked_at: 11 }] },
  ];
  const responses = structuredClone(snapshots);
  const poll = async (load, accept) => {
    for (const _body of snapshots) {
      const loaded = await load();
      if (accept(loaded)) return loaded;
    }
    return null;
  };
  const getJson = async (_path, _params) => responses.shift();
  const resolveRefreshingUnit = loadInlineFunction("resolveRefreshingUnit", {
    pollSharedSnapshot: poll, getJson, mergeUnits, state,
    onUnit: (unit) => rendered.push(unit),
  });

  const found = await resolveRefreshingUnit("hm", "pb", { dong: "101", ho: "201" }, 10);
  assert.equal(found.checked_at, 11);
  assert.equal(state.units.get(unitKey("101", "201")).checked_at, 11);
  assert.deepEqual(rendered, [found]);
});

test("공유 결과가 없으면 기존 호실은 보존하고 최초 호실만 화면 오류가 된다", async () => {
  const previous = { dong: "101", ho: "201", status: "info", fields: {}, checked_at: 10 };
  const state = { units: new Map([[unitKey("101", "201"), previous]]) };
  const getJson = async () => ({ status: "refreshing", refreshing: true });
  const resolveRefreshingUnit = async () => null;
  const fetchResolvedUnit = loadInlineFunction("fetchResolvedUnit", {
    state, unitKey, getJson, resolveRefreshingUnit,
  });

  assert.equal(await fetchResolvedUnit("hm", "pb", previous), previous);
  state.units.clear();
  assert.deepEqual(await fetchResolvedUnit("hm", "pb", previous), {
    dong: "101", ho: "201", status: "error", fields: {},
  });
});

test("cache 상태는 저장·직접·업데이트 필요를 사용자 문구로 표시한다", () => {
  const node = { textContent: "" };
  const renderCacheStatus = loadInlineFunction("renderCacheStatus", {
    el: () => node,
    formatCheckedAt: (value) => value ? "2026. 07. 24. 12:00" : "",
  });

  renderCacheStatus({ cache: "disabled", checked_at: null });
  assert.equal(node.textContent, "공유 캐시 없이 직접 조회");
  renderCacheStatus({ cache: "fresh", checked_at: 1 });
  assert.equal(node.textContent, "저장된 결과 · 2026. 07. 24. 12:00");
  renderCacheStatus({ cache: "stale", checked_at: 1 });
  assert.equal(node.textContent, "저장된 결과 · 업데이트 필요 · 2026. 07. 24. 12:00");
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
  assert.match(scan, /fetchUnit:\s*\(job\)\s*=>\s*fetchResolvedUnit\(hm, pb, job\)/);
  assert.match(indexHtml, /renderRetry[\s\S]*fetchResolvedUnit\(/);
  assert.match(indexHtml, /scanComplex\(\{ forceFull: true \}\)/);
  assert.match(indexHtml, /id="cache-status" class="caption"/);
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

test("topology 대기 중 중단하면 저장 상태를 그대로 보존한다", async () => {
  const body = structuredClone(snapshot);
  body.cache = "stale";
  body.meta = {
    total: 1,
    dongs: [{ name: "101", hos: ["201"], grid: null }],
    supply: [],
  };
  body.units = [{ dong: "101", ho: "201", status: "info", fields: {} }];
  body.refresh.topology = true;
  body.refresh.units = [{ dong: "101", ho: "202" }];

  const state = { meta: null, units: new Map(), cache: null, aborted: false };
  let resolveTopology;
  let markTopologyStarted;
  const topologyResult = new Promise((resolve) => { resolveTopology = resolve; });
  const topologyStarted = new Promise((resolve) => { markTopologyStarted = resolve; });
  let cachedMeta;
  let cachedUnits;
  let replayed = 0;
  const running = cacheModule.runCacheFirstRefresh({
    state,
    loadSnapshot: async () => body,
    fetchTopology: async () => {
      markTopologyStarted();
      return topologyResult;
    },
    fetchSupply: async () => assert.fail("aborted scan must not fetch supply"),
    fetchUnit: async () => assert.fail("aborted scan must not fetch units"),
    runJobs: async () => assert.fail("aborted scan must not run jobs"),
    onStored: () => {
      cachedMeta = state.meta;
      cachedUnits = [...state.units.entries()];
    },
    onTopology: () => { replayed += 1; },
  });

  await topologyStarted;
  state.aborted = true;
  resolveTopology({
    total: 1,
    dongs: [{ name: "101", hos: ["202"], grid: null }],
    supply: null,
  });
  const result = await running;

  assert.equal(result.status, "aborted");
  assert.equal(state.meta, cachedMeta);
  assert.deepEqual([...state.units.entries()], cachedUnits);
  assert.equal(replayed, 0);
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
