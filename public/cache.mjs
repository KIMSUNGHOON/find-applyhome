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
    state.meta = await fetchTopology();
    state.meta.supply = cachedSupply;
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
    state.meta.supply = await fetchSupply();
  }

  const allJobs = jobsFromMeta(state.meta);
  const jobs = forceFull ? allJobs : selectUnitJobs(snapshot, allJobs);
  let updated = 0;
  await runJobs(jobs, async (job) => {
    const unit = await fetchUnit(job);
    if (unit.status !== "refreshing") {
      state.units.set(unitKey(unit.dong, unit.ho), unit);
      await onUnit(unit);
    }
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
  (delay) => new Promise((resolve) => setTimeout(resolve, delay))) {
  for (const delay of POLL_DELAYS_MS) {
    await wait(delay);
    const snapshot = await load();
    if (accept(snapshot)) return snapshot;
  }
  return null;
}

export function formatCheckedAt(value) {
  if (!value) return "";
  return new Date(value * 1000).toLocaleString("ko-KR", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
}
