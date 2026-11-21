/** localStorage에 남는 설정 · 전적.
 *
 * 설정은 `itda.settings.v1`, 전적은 `itda.record.v1` 에 쌓는다.
 * 이전 이름(끝말봇·한방봇)으로 배포하던 시절의 키는 아래 LEGACY에 한 번만 옮겨 와서,
 * 그때 쌓인 설정·전적을 잃지 않는다(옮긴 뒤에도 예전 키는 건드리지 않는다).
 *
 * 내 단어장 기능은 없앴다. 아주 예전 버전이 이 기기에 남긴 커스텀 키는
 * 읽지도 지우지도 않고 그냥 둔다(값이 무엇이든 앱 동작에 영향이 없다).
 *
 * 전적은 난이도 번호(1~5)로 쌓고, 하드코어 대국은 같은 객체 안의 `3:hc` 처럼
 * 구분된 키에 따로 쌓는다. 그래서 예전 4단계 시절 기록도 그대로 읽힌다.
 */

const KEY_SETTINGS = 'itda.settings.v1';
const KEY_RECORD = 'itda.record.v1';

/** 리브랜딩 전 이름들. 최근 이름이 앞이다(잇다 → 끝말봇 → 한방봇). */
const LEGACY_NAMES = ['kkeutmalbot', 'hanbang'];

const DEFAULT_SETTINGS = {
  level: 2,
  timeLimit: 15,
  first: 'me',      // 'me' | 'bot'
  sound: true,
  hardcore: false,
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
    // 값과 겹쳐도 같은 대국을 두 번 세지 않고, 하드코어(`3:hc`) 행도 같이 넘어온다.
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
  if ([10, 15, 20].includes(saved.timeLimit)) settings.timeLimit = saved.timeLimit;
  if (saved.first === 'me' || saved.first === 'bot') settings.first = saved.first;
  if (typeof saved.sound === 'boolean') settings.sound = saved.sound;
  if (typeof saved.hardcore === 'boolean') settings.hardcore = saved.hardcore;
  return settings;
}

export function saveSettings(settings) {
  writeJSON(KEY_SETTINGS, {
    level: settings.level,
    timeLimit: settings.timeLimit,
    first: settings.first,
    sound: settings.sound,
    hardcore: Boolean(settings.hardcore),
  });
}

/** 전적 키: 일반 대국은 난이도 번호, 하드코어 대국은 `3:hc`. */
export function recordKey(level, hardcore = false) {
  return hardcore ? `${level}:hc` : String(level);
}

/** 전적: { [level | '3:hc']: { wins, losses, bestCombo, bestScore, plays } } */
export function loadRecord() {
  return readJSON(KEY_RECORD, {});
}

export function saveRecord(record) {
  writeJSON(KEY_RECORD, record);
}

export function recordResult(record, level, outcome, { hardcore = false } = {}) {
  const key = recordKey(level, hardcore);
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
