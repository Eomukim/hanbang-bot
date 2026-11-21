/** localStorage에 남는 설정 · 내 단어장 · 전적. */

const KEY_SETTINGS = 'hanbang.settings.v1';
const KEY_CUSTOM = 'hanbang.custom.v1';
const KEY_RECORD = 'hanbang.record.v1';

const DEFAULT_SETTINGS = {
  level: 2,
  timeLimit: 15,
  first: 'me',      // 'me' | 'bot'
  sound: true,
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

export function loadSettings() {
  const saved = readJSON(KEY_SETTINGS, {});
  const settings = { ...DEFAULT_SETTINGS };
  if ([1, 2, 3, 4].includes(saved.level)) settings.level = saved.level;
  if ([10, 15, 20].includes(saved.timeLimit)) settings.timeLimit = saved.timeLimit;
  if (saved.first === 'me' || saved.first === 'bot') settings.first = saved.first;
  if (typeof saved.sound === 'boolean') settings.sound = saved.sound;
  return settings;
}

export function saveSettings(settings) {
  writeJSON(KEY_SETTINGS, {
    level: settings.level,
    timeLimit: settings.timeLimit,
    first: settings.first,
    sound: settings.sound,
  });
}

/** 내 단어장: { 단어: { mean, at } } */
export function loadCustom() {
  const raw = readJSON(KEY_CUSTOM, {});
  const out = {};
  for (const [word, meta] of Object.entries(raw)) {
    if (typeof word !== 'string' || !word) continue;
    out[word] = {
      mean: typeof meta?.mean === 'string' ? meta.mean : '',
      at: typeof meta?.at === 'number' ? meta.at : 0,
    };
  }
  return out;
}

export function saveCustom(words) {
  writeJSON(KEY_CUSTOM, words);
}

/** 전적: { [level]: { wins, losses, bestCombo, bestScore } } */
export function loadRecord() {
  return readJSON(KEY_RECORD, {});
}

export function saveRecord(record) {
  writeJSON(KEY_RECORD, record);
}

export function recordResult(record, level, outcome) {
  const row = record[level] || { wins: 0, losses: 0, bestCombo: 0, bestScore: 0, plays: 0 };
  row.plays = (row.plays || 0) + 1;
  if (outcome.win) row.wins += 1;
  else row.losses += 1;
  row.bestCombo = Math.max(row.bestCombo || 0, outcome.bestCombo || 0);
  row.bestScore = Math.max(row.bestScore || 0, outcome.score || 0);
  record[level] = row;
  saveRecord(record);
  return record;
}
