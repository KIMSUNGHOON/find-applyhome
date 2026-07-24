import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as cacheModule from "../public/cache.mjs";
import {
  POLL_DELAYS_MS, createOperationController, formatCheckedAt, hydrateState,
  mergeUnits, pollSharedSnapshot, runExclusiveOperation, selectUnitJobs, unitKey,
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

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("진행 중인 scan은 두 번째 scan의 load와 pool을 시작하지 않는다", async () => {
  const controller = createOperationController();
  const loadStarted = deferred();
  const releaseLoad = deferred();
  let loads = 0;
  let pools = 0;

  const first = runExclusiveOperation(controller, "scan", async () => {
    loads += 1;
    loadStarted.resolve();
    await releaseLoad.promise;
    pools += 1;
    return "first";
  });
  await loadStarted.promise;

  const second = await runExclusiveOperation(controller, "scan", async () => {
    loads += 1;
    pools += 1;
    return "second";
  });

  assert.equal(second, null);
  assert.equal(loads, 1);
  assert.equal(pools, 0);
  releaseLoad.resolve();
  assert.equal(await first, "first");
  assert.equal(pools, 1);
});

test("이전 generation의 늦은 완료는 새 operation을 다시 활성화하지 않는다", async () => {
  const busyStates = [];
  const controller = createOperationController((busy) => busyStates.push(busy));
  const oldOwner = controller.begin("scan");
  assert.ok(oldOwner);
  assert.equal(controller.finish(oldOwner), true);
  const newOwner = controller.begin("retry");
  assert.ok(newOwner);

  await Promise.resolve();
  assert.equal(controller.finish(oldOwner), false);
  assert.equal(controller.isBusy(), true);
  assert.equal(controller.owns(newOwner), true);
  assert.deepEqual(busyStates, [true, false, true]);
});

test("scan이 대기 중이면 retry operation도 시작하지 않는다", async () => {
  const controller = createOperationController();
  const scanStarted = deferred();
  const releaseScan = deferred();
  let retries = 0;
  const scan = runExclusiveOperation(controller, "scan", async () => {
    scanStarted.resolve();
    await releaseScan.promise;
  });
  await scanStarted.promise;

  const retry = await runExclusiveOperation(controller, "retry", async () => {
    retries += 1;
  });
  assert.equal(retry, null);
  assert.equal(retries, 0);
  releaseScan.resolve();
  await scan;
});

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

test("getJson은 JSON 해석이 실패한 202도 HTTP 상태로 반환한다", async () => {
  const fetch = async () => ({
    ok: false,
    status: 202,
    json: async () => { throw new SyntaxError("invalid JSON"); },
  });
  const getJson = loadInlineFunction("getJson", { fetch });
  assert.deepEqual(await getJson("/api/unit", { dong: "101", ho: "201" }), {
    http_status: 202,
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

function completeSnapshot(units) {
  return {
    cache: "partial",
    checked_at: 11,
    meta: { total: 1, dongs: [{ name: "101", hos: ["201"], grid: null }], supply: [] },
    units,
    refresh: { topology: false, supply: false, all_units: false, units: [] },
    full_refresh: { allowed: true, retry_after: 0 },
  };
}

test("본문이 빈 202도 경합으로 보고 최신 공유 호실을 반환한다", async () => {
  assert.equal(typeof cacheModule.resolveUnitRequest, "function");
  const job = { dong: "101", ho: "201" };
  const fresh = { ...job, status: "info", fields: {}, checked_at: 11 };
  const result = await cacheModule.resolveUnitRequest({
    job,
    loadUnit: async () => ({ http_status: 202 }),
    loadSnapshot: async () => completeSnapshot([fresh]),
    wait: async () => {},
  });
  assert.equal(result, fresh);
});

test("200 refreshing은 stale·무관 snapshot을 건너뛰고 최신 일치 호실만 반환한다", async () => {
  const job = { dong: "101", ho: "201" };
  const previous = { ...job, status: "empty", fields: {}, checked_at: 10 };
  const newer = { ...job, status: "info", fields: {}, checked_at: 11 };
  const unrelated = { dong: "102", ho: "301", status: "info", fields: {}, checked_at: 99 };
  const responses = [
    completeSnapshot([previous, unrelated]),
    completeSnapshot([unrelated]),
    completeSnapshot([newer]),
  ];
  let loads = 0;
  const result = await cacheModule.resolveUnitRequest({
    job,
    previous,
    loadUnit: async () => ({ ...previous, refreshing: true, http_status: 200 }),
    loadSnapshot: async () => { loads += 1; return responses.shift(); },
    wait: async () => {},
  });
  assert.equal(result, newer);
  assert.equal(loads, 3);
});

test("poll 중 cache 조회 실패는 해당 시도만 비우고 다음 최신 결과를 받는다", async () => {
  const job = { dong: "101", ho: "201" };
  const fresh = { ...job, status: "info", fields: {}, checked_at: 11 };
  let loads = 0;
  const result = await cacheModule.resolveUnitRequest({
    job,
    loadUnit: async () => ({ ...job, status: "refreshing", fields: {}, http_status: 202 }),
    loadSnapshot: async () => {
      loads += 1;
      if (loads === 1) throw new Error("cache offline");
      return completeSnapshot([fresh]);
    },
    wait: async () => {},
  });
  assert.equal(result, fresh);
  assert.equal(loads, 2);
});

test("poll 소진 시 기존 호실을 그대로 반환한다", async () => {
  const job = { dong: "101", ho: "201" };
  const previous = { ...job, status: "empty", fields: {}, checked_at: 10 };
  const result = await cacheModule.resolveUnitRequest({
    job,
    previous,
    loadUnit: async () => ({ http_status: 202 }),
    loadSnapshot: async () => completeSnapshot([previous]),
    wait: async () => {},
  });
  assert.equal(result, previous);
});

test("poll 소진 시 기존값이 없는 호실만 client error를 반환한다", async () => {
  const job = { dong: "101", ho: "201" };
  const result = await cacheModule.resolveUnitRequest({
    job,
    loadUnit: async () => ({ http_status: 202 }),
    loadSnapshot: async () => completeSnapshot([]),
    wait: async () => {},
  });
  assert.deepEqual(result, {
    dong: "101", ho: "201", status: "error", fields: {},
  });
});

test("poll wait에서 중단되면 snapshot을 읽지 않고 null을 반환한다", async () => {
  let aborted = false;
  let loads = 0;
  const found = await pollSharedSnapshot(
    async () => { loads += 1; return completeSnapshot([]); },
    () => false,
    async () => { aborted = true; },
    () => aborted,
  );
  assert.equal(found, null);
  assert.equal(loads, 0);
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
  assert.match(indexHtml, /resolveUnitRequest,/);
  assert.match(indexHtml, /isAborted:\s*\(\)\s*=>\s*state\.aborted/);
  assert.match(indexHtml, /renderRetry[\s\S]*fetchResolvedUnit\(/);
  assert.match(indexHtml, /scanComplex\(\{ forceFull: true \}\)/);
  assert.match(indexHtml, /runExclusiveOperation\(operationController,\s*"scan"/);
  assert.match(indexHtml, /runExclusiveOperation\(operationController,\s*"retry"/);
  assert.match(indexHtml, /id="progress" class="status" role="status" aria-live="polite" aria-atomic="true"/);
  assert.match(indexHtml, /id="cache-status" class="caption" role="status" aria-live="polite" aria-atomic="true"/);
  assert.equal(
    indexHtml.match(/data-operation-region aria-busy="false"/g)?.length,
    3,
  );
  assert.match(indexHtml, /querySelectorAll\("\[data-operation-region\]"\)/);
});

test("저장 결과에서 operation 중 렌더된 action은 모두 disabled다", () => {
  const created = [];
  const bar = { append: (...nodes) => created.push(...nodes) };
  const list = { prepend: (node) => assert.equal(node, bar) };
  const document = {
    createElement: (tag) => tag === "div" ? bar : {
      className: "",
      textContent: "",
      disabled: false,
      dataset: {},
      addEventListener: () => {},
    },
  };
  const operationController = { isBusy: () => true };
  const renderRetry = loadInlineFunction("renderRetry", {
    document,
    operationController,
    retryFailedUnits: () => {},
  });
  const renderActions = loadInlineFunction("renderActions", {
    document,
    downloadCsv: () => {},
    operationController,
    scanComplex: () => {},
    el: () => list,
    renderRetry,
  });

  renderActions({ error: 1 });
  assert.equal(created.length, 3);
  assert.ok(created.every((button) => button.disabled));
  assert.ok(created.every((button) => button.dataset.operationAction === "true"));
});

test("owner가 끝날 때만 action과 결과 aria-busy를 다시 활성화한다", () => {
  const regions = Array.from({ length: 3 }, () => ({ busy: "false" }));
  regions.forEach((region) => {
    region.setAttribute = (name, value) => {
      assert.equal(name, "aria-busy");
      region.busy = value;
    };
  });
  const scanButton = { disabled: false };
  const stopButton = {
    hidden: true,
    classList: { toggle: (name, force) => {
      assert.equal(name, "hide");
      stopButton.hidden = force;
    } },
  };
  const action = { disabled: false };
  const radio = { disabled: false };
  const document = {
    querySelectorAll: (selector) => ({
      "[data-operation-region]": regions,
      "[data-operation-action]": [action],
      'input[name="complex"]': [radio],
    })[selector],
  };
  const setOperationBusy = loadInlineFunction("setOperationBusy", {
    document,
    state: { complex: {} },
    el: (id) => id === "scan-button" ? scanButton : stopButton,
  });
  const controller = createOperationController(setOperationBusy);

  const oldOwner = controller.begin("scan");
  assert.ok(regions.every((region) => region.busy === "true"));
  assert.equal(scanButton.disabled, true);
  assert.equal(stopButton.hidden, false);
  assert.equal(action.disabled, true);
  assert.equal(radio.disabled, true);

  assert.equal(controller.finish(oldOwner), true);
  const newOwner = controller.begin("retry");
  assert.equal(controller.finish(oldOwner), false);
  assert.equal(action.disabled, true);
  assert.ok(regions.every((region) => region.busy === "true"));

  assert.equal(controller.finish(newOwner), true);
  assert.equal(scanButton.disabled, false);
  assert.equal(stopButton.hidden, true);
  assert.equal(action.disabled, false);
  assert.equal(radio.disabled, false);
  assert.ok(regions.every((region) => region.busy === "false"));
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
      fetchSupply: async () => ({ supply: [], refresh_failed: false }),
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

test("cached supply는 명시된 일시적 refresh 실패 때 보존된다", async () => {
  const body = structuredClone(snapshot);
  body.cache = "stale";
  body.meta.supply = [{ type: "084A", total: 10 }];
  body.refresh.supply = true;
  body.refresh.units = [];
  const state = { meta: null, units: new Map(), cache: null, aborted: false };

  await cacheModule.runCacheFirstRefresh({
    state,
    loadSnapshot: async () => body,
    fetchTopology: async () => assert.fail("cached topology must be reused"),
    fetchSupply: async () => ({ supply: null, refresh_failed: true }),
    fetchUnit: async () => assert.fail("no unit refresh requested"),
    runJobs: async (jobs, worker) => Promise.all(jobs.map(worker)),
  });

  assert.deepEqual(state.meta.supply, [{ type: "084A", total: 10 }]);
});

test("cached supply는 refresh 호출이 throw해도 보존된다", async () => {
  const body = structuredClone(snapshot);
  body.cache = "stale";
  body.meta.supply = [{ type: "084A", total: 10 }];
  body.refresh.supply = true;
  body.refresh.units = [];
  const state = { meta: null, units: new Map(), cache: null, aborted: false };

  await cacheModule.runCacheFirstRefresh({
    state,
    loadSnapshot: async () => body,
    fetchTopology: async () => assert.fail("cached topology must be reused"),
    fetchSupply: async () => { throw new Error("upstream timeout"); },
    fetchUnit: async () => assert.fail("no unit refresh requested"),
    runJobs: async (jobs, worker) => Promise.all(jobs.map(worker)),
  });

  assert.deepEqual(state.meta.supply, [{ type: "084A", total: 10 }]);
});

test("confirmed null supply는 cached supply를 교체한다", async () => {
  const body = structuredClone(snapshot);
  body.cache = "stale";
  body.meta.supply = [{ type: "084A", total: 10 }];
  body.refresh.supply = true;
  body.refresh.units = [];
  const state = { meta: null, units: new Map(), cache: null, aborted: false };

  await cacheModule.runCacheFirstRefresh({
    state,
    loadSnapshot: async () => body,
    fetchTopology: async () => assert.fail("cached topology must be reused"),
    fetchSupply: async () => ({ supply: null, refresh_failed: false }),
    fetchUnit: async () => assert.fail("no unit refresh requested"),
    runJobs: async (jobs, worker) => Promise.all(jobs.map(worker)),
  });

  assert.equal(state.meta.supply, null);
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

test("호실 poll wait 중 중단하면 Map·render·progress를 건드리지 않는다", async () => {
  const body = structuredClone(snapshot);
  body.meta = {
    total: 1,
    dongs: [{ name: "101", hos: ["202"], grid: null }],
    supply: [],
  };
  body.units = [];
  body.refresh.units = [{ dong: "101", ho: "202" }];
  const state = { meta: null, units: new Map(), cache: null, aborted: false };
  let rendered = 0;
  let progressed = 0;

  const result = await cacheModule.runCacheFirstRefresh({
    state,
    loadSnapshot: async () => body,
    fetchTopology: async () => assert.fail("cached topology must be reused"),
    fetchSupply: async () => assert.fail("cached supply must be reused"),
    fetchUnit: (job) => cacheModule.resolveUnitRequest({
      job,
      loadUnit: async () => ({ http_status: 202 }),
      loadSnapshot: async () => assert.fail("abort after wait must skip snapshot load"),
      wait: async () => { state.aborted = true; },
      isAborted: () => state.aborted,
    }),
    runJobs: async (jobs, worker) => Promise.all(jobs.map(worker)),
    onUnit: () => { rendered += 1; },
    onProgress: () => { progressed += 1; },
  });

  assert.equal(result.status, "aborted");
  assert.equal(state.units.size, 0);
  assert.equal(rendered, 0);
  assert.equal(progressed, 0);
  assert.equal(result.updated, 0);
});

test("polled 호실은 cache-first owner가 Map·render·progress를 한 번만 반영한다", async () => {
  const body = structuredClone(snapshot);
  body.meta = {
    total: 1,
    dongs: [{ name: "101", hos: ["202"], grid: null }],
    supply: [],
  };
  body.units = [];
  body.refresh.units = [{ dong: "101", ho: "202" }];
  const fresh = { dong: "101", ho: "202", status: "info", fields: {}, checked_at: 11 };
  const state = { meta: null, units: new Map(), cache: null, aborted: false };
  let rendered = 0;
  let progressed = 0;
  const result = await cacheModule.runCacheFirstRefresh({
    state,
    loadSnapshot: async () => body,
    fetchTopology: async () => assert.fail("cached topology must be reused"),
    fetchSupply: async () => assert.fail("cached supply must be reused"),
    fetchUnit: (job) => cacheModule.resolveUnitRequest({
      job,
      loadUnit: async () => ({ http_status: 202 }),
      loadSnapshot: async () => completeSnapshot([fresh]),
      wait: async () => {},
    }),
    runJobs: async (jobs, worker) => Promise.all(jobs.map(worker)),
    onUnit: () => { rendered += 1; },
    onProgress: () => { progressed += 1; },
  });
  assert.equal(state.units.get(unitKey("101", "202")), fresh);
  assert.equal(rendered, 1);
  assert.equal(progressed, 1);
  assert.equal(result.updated, 1);
});

test("호실 load 뒤 중단되어도 Map·render·progress를 건드리지 않는다", async () => {
  const body = structuredClone(snapshot);
  body.meta = {
    total: 1,
    dongs: [{ name: "101", hos: ["202"], grid: null }],
    supply: [],
  };
  body.units = [];
  body.refresh.units = [{ dong: "101", ho: "202" }];
  const state = { meta: null, units: new Map(), cache: null, aborted: false };
  let releaseUnit;
  let markStarted;
  const pendingUnit = new Promise((resolve) => { releaseUnit = resolve; });
  const started = new Promise((resolve) => { markStarted = resolve; });
  let rendered = 0;
  let progressed = 0;
  const running = cacheModule.runCacheFirstRefresh({
    state,
    loadSnapshot: async () => body,
    fetchTopology: async () => assert.fail("cached topology must be reused"),
    fetchSupply: async () => assert.fail("cached supply must be reused"),
    fetchUnit: async () => { markStarted(); return pendingUnit; },
    runJobs: async (jobs, worker) => Promise.all(jobs.map(worker)),
    onUnit: () => { rendered += 1; },
    onProgress: () => { progressed += 1; },
  });

  await started;
  state.aborted = true;
  releaseUnit({ dong: "101", ho: "202", status: "info", fields: {} });
  const result = await running;
  assert.equal(result.status, "aborted");
  assert.equal(state.units.size, 0);
  assert.equal(rendered, 0);
  assert.equal(progressed, 0);
  assert.equal(result.updated, 0);
});

test("onUnit은 이전 status·공급 class와 text·title을 완전히 교체한다", () => {
  const classes = new Set(["cell", "error", "supply-s"]);
  const cell = {
    classList: {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
    },
    textContent: "특",
    title: "old",
  };
  const onUnit = loadInlineFunction("onUnit", {
    document: { getElementById: () => cell },
    cellId: () => "c-101-201",
    SUPPLY_MARK: { "특별공급": "특", "일반공급": "일" },
    SUPPLY_CLASS: { "특별공급": "supply-s", "일반공급": "supply-g" },
    shortType: () => "84A",
  });

  onUnit({
    dong: "101", ho: "201", status: "info",
    fields: { "주택형": "084.8422A", "공급유형": "일반공급" },
  });
  assert.deepEqual([...classes].sort(), ["cell", "info", "supply-g"]);
  assert.equal(cell.textContent, "일");
  assert.equal(cell.title, "101동 201호 · 84A · 일반공급");

  onUnit({ dong: "101", ho: "201", status: "empty", fields: {} });
  assert.deepEqual([...classes].sort(), ["cell", "empty"]);
  assert.equal(cell.textContent, "");
  assert.equal(cell.title, "101동 201호");
});

test("onUnit은 비객체 fields를 빈 객체로 취급해 렌더링을 계속한다", () => {
  const classes = new Set(["cell", "info", "supply-s"]);
  const cell = {
    classList: {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
    },
    textContent: "특",
    title: "old",
  };
  const onUnit = loadInlineFunction("onUnit", {
    document: { getElementById: () => cell },
    cellId: () => "c-101-201",
    SUPPLY_MARK: { "특별공급": "특", "일반공급": "일" },
    SUPPLY_CLASS: { "특별공급": "supply-s", "일반공급": "supply-g" },
    shortType: () => "84A",
  });

  for (const fields of [null, [], "invalid"]) {
    assert.doesNotThrow(() => onUnit({
      dong: "101", ho: "201", status: "empty", fields,
    }));
    assert.equal(cell.textContent, "");
    assert.equal(cell.title, "101동 201호");
  }
});

test("직접 retry 결과는 Map 뒤 onUnit과 전체 onDone 순서로 반영한다", async () => {
  const failed = { dong: "101", ho: "201", status: "error", fields: {} };
  const fresh = {
    dong: "101", ho: "201", status: "info",
    fields: { "주택형": "084.8422A", "공급유형": "일반공급" },
  };
  const state = {
    complex: { house_manage_no: "hm", pblanc_no: "pb" },
    meta: { total: 1 },
    units: new Map([[unitKey("101", "201"), failed]]),
    aborted: false,
  };
  const events = [];
  const progress = { textContent: "완료 · 1세대 · 실패 1건" };
  const operationController = createOperationController();
  const retryFailedUnits = loadInlineFunction("retryFailedUnits", {
    state,
    unitKey,
    operationController,
    runExclusiveOperation,
    fetchResolvedUnit: async () => fresh,
    onUnit: (unit) => {
      assert.equal(state.units.get(unitKey(unit.dong, unit.ho)), fresh);
      events.push("unit");
    },
    summarize: () => ({ total: 1, info: 1, empty: 0, error: 0, elapsed: "1.0" }),
    completionStatus: (summary) => `완료 · 실패 ${summary.error}건`,
    el: () => progress,
    onDone: (summary) => events.push(`done:${summary.error}`),
  });

  const updated = await retryFailedUnits({ elapsed: "1.0", error: 1 });
  assert.equal(state.units.get(unitKey("101", "201")), fresh);
  assert.deepEqual(events, ["unit", "done:0"]);
  assert.equal(updated.error, 0);
  assert.equal(progress.textContent, "완료 · 실패 0건");
});

test("bare CR이 든 CSV cell을 quote해 한 data row를 유지한다", () => {
  const csvCell = loadInlineFunction("csvCell");
  assert.equal(csvCell("첫줄\r둘째줄"), '"첫줄\r둘째줄"');

  const state = {
    units: new Map([["unit", {
      dong: "101",
      ho: "201",
      status: "info",
      fields: { "주택형": "084.8422A", "공급유형": "일반\r공급" },
    }]]),
  };
  const CSV_HEADER = [
    "동", "호", "타입", "판정", "주택형", "공급유형", "공고일",
    "당첨자 발표일", "계약체결일", "입주예정", "전매제한", "분양금액(만원)",
  ];
  const buildCsv = loadInlineFunction("buildCsv", {
    CSV_HEADER,
    STATUS_LABEL: { info: "정보있음" },
    state,
    unitFields: (unit) => unit.fields,
    shortType: () => "84A",
    csvCell,
  });
  const csv = buildCsv().slice(1);
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let index = 0; index < csv.length; index += 1) {
    const char = csv[index];
    if (char === '"' && quoted && csv[index + 1] === '"') {
      cell += '"';
      index += 1;
    } else if (char === '"') {
      quoted = !quoted;
    } else if (char === "," && !quoted) {
      row.push(cell);
      cell = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && csv[index + 1] === "\n") index += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }

  assert.equal(rows.length, 2);
  assert.equal(rows[1].length, CSV_HEADER.length);
  assert.equal(rows[1][5], "일반\r공급");
});

test("server full-refresh 거부는 후속 작업 없이 retry_after를 노출한다", async () => {
  const body = structuredClone(snapshot);
  body.full_refresh = { allowed: false, retry_after: 37 };
  const state = { meta: null, units: new Map(), cache: null, aborted: false };
  const result = await cacheModule.runCacheFirstRefresh({
    state,
    forceFull: true,
    loadSnapshot: async () => body,
    fetchTopology: async () => assert.fail("blocked full refresh must not fetch topology"),
    fetchSupply: async () => assert.fail("blocked full refresh must not fetch supply"),
    fetchUnit: async () => assert.fail("blocked full refresh must not fetch units"),
    runJobs: async () => assert.fail("blocked full refresh must not start jobs"),
  });
  assert.equal(result.status, "blocked");
  assert.equal(result.snapshot.full_refresh.retry_after, 37);
  assert.equal(result.updated, 0);
});
