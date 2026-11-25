/** localStorage에 남는 설정 · 전적.
 *
 * 설정은 `itda.settings.v1`, 전적은 `itda.record.v1` 에 쌓는다.
 * 이전 이름(끝말봇·한방봇)으로 배포하던 시절의 키는 아래 LEGACY에 한 번만 옮겨 와서,
 * 그때 쌓인 설정·전적을 잃지 않는다(옮긴 뒤에도 예전 키는 건드리지 않는다).
 *
 * 내 단어장 기능은 없앴다. 아주 예전 버전이 이 기기에 남긴 커스텀 키는
 * 읽지도 지우지도 않고 그냥 둔다(값이 무엇이든 앱 동작에 영향이 없다).
 *
 * 전적은 난이도 번호(1~5)로 쌓는다. 그사이 없어진 하드코어 모드가 남긴 `3:hc` 행이
 * localStorage에 있어도 읽지 않고 그대로 둔다(값이 무엇이든 앱 동작에 영향이 없다).
 */

const KEY_SETTINGS = 'itda.settings.v1';
const KEY_RECORD = 'itda.record.v1';

/** 리브랜딩 전 이름들. 최근 이름이 앞이다(잇다 → 끝말봇 → 한방봇). */
const LEGACY_NAMES = ['kkeutmalbot', 'hanbang'];

/** 제한 시간: 최소 1초, 그 위로는 5초 단위(1·5·10·…·50). */
export const TIME_MIN = 1;
export const TIME_MAX = 50;
export const TIME_STEP = 5;

/** 슬라이더가 설 수 있는 값들. 1초 다음부터는 5초 간격이다. */
export const TIME_VALUES = [1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50];

export const DEFAULT_SETTINGS = {
  level: 2,
  timeLimit: 15,
  first: 'me',      // 'me' | 'bot'
  volume: 100,      // 효과음 음량 0~100(%). 0이면 무음
  dark: false,      // 다크모드(수제 우드 톤을 어둡게)
  mercy: false,     // 배려모드: 첫 5수 한방 금지
};

/** 저장된 제한 시간을 슬라이더가 설 수 있는 값(1·5·10·…·50)으로 맞춘다.
 *
 * 1초는 그대로 두고, 5~50초는 가장 가까운 5초로 당긴다(12 → 10, 33 → 35).
 * 1초와 가까운 2는 1초, 3~4는 5초로 올린다(둥근 값이 같으면 위쪽 5초).
 * 0 이하·51 이상·숫자가 아닌 값은 fallback(기본 15초)로 시작한다.
 */
export function normalizeTimeLimit(value, fallback = DEFAULT_SETTINGS.timeLimit) {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n) || n < TIME_MIN || n > TIME_MAX) return fallback;
  if (n === TIME_MIN) return TIME_MIN;
  return Math.max(TIME_MIN, Math.min(TIME_MAX, Math.round(n / TIME_STEP) * TIME_STEP));
}

/** 슬라이더를 움직일 때 들어온 값을 허용 값(1·5·10·…·50) 중 가장 가까운 값으로 당긴다.
 *
 * 드래그·클릭은 0~50 어느 값이든 들어올 수 있어, 0 이하는 최소 1초로 올리고
 * 2~4초는 1초 또는 5초 중 가까운 쪽(3·4 → 5)으로 붙인다. 범위 위쪽·숫자가 아닌
 * 값만 fallback 을 쓴다. 저장값을 읽을 때는 이 함수 대신 normalizeTimeLimit 을 쓴다.
 */
export function snapTimeLimit(value, fallback = DEFAULT_SETTINGS.timeLimit) {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n) || n > TIME_MAX) return fallback;
  if (n <= TIME_MIN) return TIME_MIN;
  return Math.max(TIME_MIN, Math.round(n / TIME_STEP) * TIME_STEP);
}

/** 제한 시간을 허용 값 한 칸씩 옮긴다(키보드 좌우 화살표). dir 은 -1·+1. */
export function stepTimeLimit(value, dir) {
  const cur = normalizeTimeLimit(value, DEFAULT_SETTINGS.timeLimit);
  const i = TIME_VALUES.indexOf(cur);
  const next = Math.max(0, Math.min(TIME_VALUES.length - 1, i + Math.sign(dir || 0)));
  return TIME_VALUES[next];
}

const clampInt = (value, min, max, fallback) => {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
};

function readJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const value = JSON.parse(raw);
    return value && typeof value === 'object' ? value : fallback;
  } catch {
    return fallback;
  }
}

function writeJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* 저장 공간이 막혀 있어도 게임은 계속된다 */
  }
}

/** 예전 이름으로 쌓인 설정·전적을 지금 키로 한 번 옮겨 온다. */
export function migrateLegacy() {
  try {
    // 설정: 지금 키가 비어 있으면 최근 이름부터 그대로 가져온다.
    if (localStorage.getItem(KEY_SETTINGS) == null) {
      for (const name of LEGACY_NAMES) {
        const oldRaw = localStorage.getItem(`${name}.settings.v1`);
        if (oldRaw != null) {
          localStorage.setItem(KEY_SETTINGS, oldRaw);
          break;
        }
      }
    }

    // 전적: 행마다 판수(plays)가 더 많은 쪽을 쓴다. 예전 키를 옮겨 와 이어 둔
    // 값과 겹쳐도 같은 대국을 두 번 세지 않는다.
    const legacyRecords = LEGACY_NAMES
      .map((name) => readJSON(`${name}.record.v1`, null))
      .filter(Boolean);
    if (!legacyRecords.length) return;
    const record = readJSON(KEY_RECORD, {});
    let changed = false;
    for (const legacy of legacyRecords) {
      for (const [key, row] of Object.entries(legacy)) {
        if (!row || typeof row !== 'object') continue;
        const mine = record[key];
        if (!mine || (row.plays || 0) > (mine.plays || 0)) {
          record[key] = { ...row };
          changed = true;
        }
      }
    }
    if (changed) writeJSON(KEY_RECORD, record);
  } catch {
    /* 저장 공간이 막혀 있으면 새 키로 시작한다 */
  }
}

export function loadSettings() {
  const saved = readJSON(KEY_SETTINGS, {});
  const settings = { ...DEFAULT_SETTINGS };
  // 4단계 시절에 저장한 설정(level 1~4)도 그대로 읽는다. 5단계가 늘었을 뿐 번호는 같다.
  if ([1, 2, 3, 4, 5].includes(saved.level)) settings.level = saved.level;
  // 예전에는 10·15·20초만 저장했고, 그 뒤 5~50초 5초 단위를 거쳤다.
  // 지금은 1초 또는 5초 단위만 쓰므로 가장 가까운 허용 값으로 맞춘다.
  if (saved.timeLimit != null) {
    settings.timeLimit = normalizeTimeLimit(saved.timeLimit, DEFAULT_SETTINGS.timeLimit);
  }
  if (saved.first === 'me' || saved.first === 'bot') settings.first = saved.first;
  // 음량: 저장된 volume 이 있으면 그 값, 없으면 예전 효과음 켬/끔에서 옮겨 온다(false → 0%).
  if (typeof saved.volume === 'number' && Number.isFinite(saved.volume)) {
    settings.volume = clampInt(saved.volume, 0, 100, DEFAULT_SETTINGS.volume);
  } else if (saved.sound === false) {
    settings.volume = 0;
  } else if (saved.sound === true) {
    settings.volume = 100;
  }
  // 2026-11-25: 흑백모드(monochrome)를 없애고 다크모드(dark)로 바꿨다.
  // 예전에 흑백을 켜 두었던 기기는 흑백이 아니라 기본(라이트)으로 시작한다.
  if (typeof saved.dark === 'boolean') settings.dark = saved.dark;
  if (typeof saved.mercy === 'boolean') settings.mercy = saved.mercy;
  return settings;
}

export function saveSettings(settings) {
  writeJSON(KEY_SETTINGS, {
    level: settings.level,
    timeLimit: normalizeTimeLimit(settings.timeLimit, DEFAULT_SETTINGS.timeLimit),
    first: settings.first,
    volume: clampInt(settings.volume, 0, 100, DEFAULT_SETTINGS.volume),
    dark: Boolean(settings.dark),
    mercy: Boolean(settings.mercy),
  });
}

/** 전적 키: 난이도 번호. */
export function recordKey(level) {
  return String(level);
}

/** 전적: { [level]: { wins, losses, bestCombo, bestScore, plays } } */
export function loadRecord() {
  return readJSON(KEY_RECORD, {});
}

export function saveRecord(record) {
  writeJSON(KEY_RECORD, record);
}

export function recordResult(record, level, outcome) {
  const key = recordKey(level);
  const row = record[key] || { wins: 0, losses: 0, bestCombo: 0, bestScore: 0, plays: 0 };
  row.plays = (row.plays || 0) + 1;
  if (outcome.win) row.wins += 1;
  else row.losses += 1;
  row.bestCombo = Math.max(row.bestCombo || 0, outcome.bestCombo || 0);
  row.bestScore = Math.max(row.bestScore || 0, outcome.bestScore || 0);
  record[key] = row;
  saveRecord(record);
  return record;
}
