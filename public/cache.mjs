export const POLL_DELAYS_MS = [500, 1000, 2000];

export function unitKey(dong, ho) {
  return `${dong}\u0000${ho}`;
}

export function mergeUnits(target, units) {
  for (const unit of units || []) target.set(unitKey(unit.dong, unit.ho), unit);
  return target;
}

export function hydrateState(state, snapshot) {
  state.meta = snapshot.meta;
  state.units = mergeUnits(new Map(), snapshot.units);
  state.cache = { status: snapshot.cache, checkedAt: snapshot.checked_at };
  return state;
}

export function selectUnitJobs(snapshot, jobs) {
  if (!snapshot || snapshot.cache === "disabled" || snapshot.cache === "miss") return jobs.slice();
  if (snapshot.refresh?.all_units) return jobs.slice();
  const requested = new Set((snapshot.refresh?.units || [])
    .map((unit) => unitKey(unit.dong, unit.ho)));
  if (snapshot.cache === "partial") {
    const saved = new Set((snapshot.units || []).map((unit) => unitKey(unit.dong, unit.ho)));
    return jobs.filter((job) => !saved.has(unitKey(job.dong, job.ho)) ||
      requested.has(unitKey(job.dong, job.ho)));
  }
  return jobs.filter((job) => requested.has(unitKey(job.dong, job.ho)));
}

export function jobsFromMeta(meta) {
  const jobs = [];
  for (const dong of meta?.dongs || []) {
    for (const ho of dong.hos) jobs.push({ dong: dong.name, ho });
  }
  return jobs;
}

export function pruneUnits(units, jobs) {
  const current = new Set(jobs.map((job) => unitKey(job.dong, job.ho)));
  for (const key of units.keys()) {
    if (!current.has(key)) units.delete(key);
  }
  return units;
}

const noop = () => {};

export function createOperationController(onBusyChange = noop) {
  let generation = 0;
  let activeOwner = null;

  return Object.freeze({
    begin(kind) {
      if (activeOwner) return null;
      activeOwner = Object.freeze({ generation: ++generation, kind });
      onBusyChange(true, activeOwner);
      return activeOwner;
    },
    finish(owner) {
      if (owner !== activeOwner) return false;
      activeOwner = null;
      onBusyChange(false, owner);
      return true;
    },
    owns(owner) {
      return owner === activeOwner;
    },
    isBusy() {
      return activeOwner !== null;
    },
  });
}

export async function runExclusiveOperation(controller, kind, operation) {
  const owner = controller.begin(kind);
  if (!owner) return null;
  try {
    return await operation(owner);
  } finally {
    controller.finish(owner);
  }
}

function disabledSnapshot() {
  return {
    cache: "disabled", complete: false, checked_at: null, meta: null, units: [],
    refresh: { topology: true, supply: true, all_units: true, units: [] },
    full_refresh: { allowed: true, retry_after: 0 },
  };
}

export async function runCacheFirstRefresh({
  state,
  forceFull = false,
  loadSnapshot,
  fetchTopology,
  fetchSupply,
  fetchUnit,
  runJobs,
  onStored = noop,
  onTopology = noop,
  onUnit = noop,
  onProgress = noop,
}) {
  let snapshot;
  try {
    snapshot = await loadSnapshot();
  } catch (error) {
    snapshot = disabledSnapshot();
  }
  if (snapshot.meta) {
    hydrateState(state, snapshot);
    await onStored(snapshot);
  } else {
    state.meta = null;
    state.units = new Map();
    state.cache = { status: snapshot.cache, checkedAt: snapshot.checked_at };
  }

  if (snapshot.full_refresh && !snapshot.full_refresh.allowed) {
    return { status: "blocked", snapshot, jobs: [], updated: 0 };
  }
  if (snapshot.cache === "fresh" && !forceFull) {
    return { status: "fresh", snapshot, jobs: [], updated: 0 };
  }

  const cachedSupply = state.meta?.supply ?? null;
  let topologyChanged = false;
  if (!state.meta || snapshot.refresh.topology || forceFull) {
    const nextMeta = await fetchTopology();
    if (state.aborted) {
      return { status: "aborted", snapshot, jobs: [], updated: 0 };
    }
    nextMeta.supply = cachedSupply;
    state.meta = nextMeta;
    pruneUnits(state.units, jobsFromMeta(state.meta));
    topologyChanged = true;
  }
  if (topologyChanged) await onTopology(state.meta);
  if (state.aborted) {
    return { status: "aborted", snapshot, jobs: [], updated: 0 };
  }
  if (!state.meta.total) {
    return { status: "empty", snapshot, jobs: [], updated: 0 };
  }
  if (snapshot.refresh.supply || forceFull || state.meta.supply === null) {
    try {
      const refreshed = await fetchSupply();
      if (state.aborted) {
        return { status: "aborted", snapshot, jobs: [], updated: 0 };
      }
      if (!refreshed?.refresh_failed) state.meta.supply = refreshed?.supply ?? null;
    } catch (error) {
      // 공급 정보는 부가 데이터다. 일시적 실패에는 저장된 값을 유지한다.
    }
  }

  const allJobs = jobsFromMeta(state.meta);
  const jobs = forceFull ? allJobs : selectUnitJobs(snapshot, allJobs);
  let updated = 0;
  await runJobs(jobs, async (job) => {
    const unit = await fetchUnit(job);
    if (!unit || state.aborted || unit.status === "refreshing") return unit;
    state.units.set(unitKey(unit.dong, unit.ho), unit);
    await onUnit(unit);
    if (state.aborted) return unit;
    updated += 1;
    await onProgress({ updated, total: jobs.length });
    return unit;
  });

  return {
    status: state.aborted ? "aborted" : "complete",
    snapshot,
    jobs,
    updated,
  };
}

export async function pollSharedSnapshot(load, accept, wait =
  (delay) => new Promise((resolve) => setTimeout(resolve, delay)), isAborted = () => false) {
  for (const delay of POLL_DELAYS_MS) {
    if (isAborted()) return null;
    await wait(delay);
    if (isAborted()) return null;
    let snapshot;
    try {
      snapshot = await load();
    } catch (error) {
      continue;
    }
    if (isAborted()) return null;
    if (snapshot && accept(snapshot)) return snapshot;
  }
  return null;
}

function clientUnitError(job) {
  return { dong: job.dong, ho: job.ho, status: "error", fields: {} };
}

function snapshotUnit(snapshot, job) {
  return (snapshot?.units || []).find((unit) =>
    unit.dong === job.dong && unit.ho === job.ho);
}

export async function resolveUnitRequest({
  job,
  previous = null,
  loadUnit,
  loadSnapshot,
  wait,
  isAborted = () => false,
}) {
  if (isAborted()) return null;
  let fresh;
  try {
    fresh = await loadUnit(job);
  } catch (error) {
    return isAborted() ? null : (previous || clientUnitError(job));
  }
  if (isAborted()) return null;
  if (!fresh) return previous || clientUnitError(job);
  const refreshing = fresh.http_status === 202 || fresh.refreshing ||
    fresh.status === "refreshing";
  if (!refreshing) return fresh;

  const previousCheckedAt = previous?.checked_at || 0;
  const found = await pollSharedSnapshot(
    loadSnapshot,
    (snapshot) => {
      const unit = snapshotUnit(snapshot, job);
      return Boolean(unit && (unit.checked_at || 0) > previousCheckedAt);
    },
    wait,
    isAborted,
  );
  if (isAborted()) return null;
  return snapshotUnit(found, job) || previous || clientUnitError(job);
}

export function formatCheckedAt(value) {
  if (!value) return "";
  return new Date(value * 1000).toLocaleString("ko-KR", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
}
