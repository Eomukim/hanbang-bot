/** localStorage에 남는 설정 · 전적.
 *
 * 설정은 `kkeutmalbot.settings.v1`, 전적은 `kkeutmalbot.record.v1` 에 쌓는다.
 * 이전 이름으로 배포하던 시절의 키는 아래 LEGACY에 한 번만 옮겨 와서,
 * 그때 쌓인 설정·전적을 잃지 않는다(옮긴 뒤에도 예전 키는 건드리지 않는다).
 *
 * 내 단어장 기능은 없앴다. 아주 예전 버전이 이 기기에 남긴 커스텀 키는
 * 읽지도 지우지도 않고 그냥 둔다(값이 무엇이든 앱 동작에 영향이 없다).
 *
 * 전적은 난이도 번호(1~5)로 쌓고, 하드코어 대국은 같은 객체 안의 `3:hc` 처럼
 * 구분된 키에 따로 쌓는다. 그래서 예전 4단계 시절 기록도 그대로 읽힌다.
 */

const KEY_SETTINGS = 'kkeutmalbot.settings.v1';
const KEY_RECORD = 'kkeutmalbot.record.v1';

/** 리브랜딩 전 이름으로 저장된 키 → 지금 키. 값이 있으면 한 번 복사한다. */
const LEGACY = [
  ['itda.settings.v1', KEY_SETTINGS],
  ['itda.record.v1', KEY_RECORD],
  ['hanbang.settings.v1', KEY_SETTINGS],
  ['hanbang.record.v1', KEY_RECORD],
];

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

/** 예전 키에만 남아 있는 값이 있으면 지금 키로 복사한다(이미 있으면 그대로). */
export function migrateLegacy() {
  try {
    for (const [oldKey, newKey] of LEGACY) {
      const oldRaw = localStorage.getItem(oldKey);
      if (!oldRaw) continue;
      if (localStorage.getItem(newKey) != null) continue;
      localStorage.setItem(newKey, oldRaw);
    }
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

/** 전적 행이 하드코어 대국인지, 어느 난이도인지 읽는다. */
export function parseRecordKey(key) {
  const hardcore = key.endsWith(':hc');
  return { level: Number(hardcore ? key.slice(0, -3) : key), hardcore };
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
  row.bestScore = Math.max(row.bestScore || 0, outcome.score || 0);
  record[key] = row;
  saveRecord(record);
  return record;
}
