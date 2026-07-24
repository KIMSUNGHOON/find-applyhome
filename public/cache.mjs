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
