export const LAST_VISIT_KEY = "visits:last";

// 저장소가 차단된 환경에서는 window.localStorage 접근 자체가 던진다.
// getItem 이 아니라 여기가 첫 관문이라, 안쪽 try 만으로는 늦는다.
export function openStorage(win) {
  try {
    return win?.localStorage ?? null;
  } catch {
    return null;
  }
}

// 사생활 보호 모드나 저장소 차단 설정에서는 접근 자체가 예외를 던진다.
// 그때는 매번 새 방문으로 세어질 뿐, 카운터는 계속 동작해야 한다.
export function readLastDate(storage) {
  try {
    return storage?.getItem(LAST_VISIT_KEY) || "";
  } catch {
    return "";
  }
}

export function saveLastDate(storage, date) {
  if (!storage || typeof date !== "string" || !date) return false;
  try {
    storage.setItem(LAST_VISIT_KEY, date);
    return true;
  } catch {
    return false;
  }
}

export function formatVisits(payload) {
  const day = payload?.day;
  const total = payload?.total;
  if (!Number.isFinite(day) || !Number.isFinite(total)) return null;
  return `오늘 ${day.toLocaleString("ko-KR")} · 전체 ${total.toLocaleString("ko-KR")}`;
}

// 세지 못한 방문을 세었다고 기록하면, 그날 안에 Redis 가 살아나도 다시 세지 않게 된다.
// 그래서 날짜 저장은 숫자를 받아낸 경우로 한정한다.
export function applyVisits(storage, payload) {
  const text = formatVisits(payload);
  if (text === null) return null;
  saveLastDate(storage, payload.today);
  return text;
}
