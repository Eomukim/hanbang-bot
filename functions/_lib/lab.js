/**
 * 잇다 실험실 — 최대 8인 커스텀 방 · 방장 = 신(God) 모드.
 *
 * 방 하나가 `lab_rooms` 한 행이다. 좌석(`seats_json`)·룰(`rules_json`)·진행 상태
 * (`state_json`)를 JSON 으로 모아 두어, 화면이 0.9초마다 부르는 상태 조회가
 * **1행만** 읽는다(D1 무료 일일 읽기 한도 절약). 초대는 `lab_invites` 에 따로 쌓는다.
 *
 * 이 방의 판은 전적·랭킹·엽전에 전혀 반영되지 않는다(초대 전용 실험 공간).
 *
 * 서버가 지키는 것: 방장 권한(`host_id === session.id`), 차례·좌석 소유권,
 * 낙관적 락(`version`)과 턴 번호(`turnSeq`), 단어의 구조(글자·길이·이어야 할 글자·금지 글자·중복).
 * 사전 수록 여부는 73만 단어 사전을 화면이 이미 들고 있으므로 참가자 화면이 먼저 확인하고,
 * 서버는 위 구조 규칙만 다시 본다(보상이 없는 실험실이라 사전 조회를 서버에 두지 않는다).
 */

export const MAX_SEATS = 8;
export const MIN_SEATS = 2;
export const CODE_LENGTH = 6;
/** 헷갈리는 O·0·I·1 을 뺀 방 코드 글자. */
const CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
const CODE_RE = /^[A-HJ-NP-Z2-9]{6}$/;

/** 이만큼 손대지 않은 방은 지운다(재조회·생성 때 확률적으로 정리). */
export const ROOM_TTL_MS = 3 * 60 * 60 * 1000;
/** 끝난 방은 결과를 잠깐 볼 수 있게만 남긴다. */
export const OVER_TTL_MS = 10 * 60 * 1000;
const INVITE_TTL_MS = 30 * 60 * 1000;

/** 최근 주고받은 단어를 몇 수까지 방에 남길까(화면 표시용). */
export const CHAIN_KEEP = 40;
/** 이미 나온 단어 목록 상한(중복 방지용 · 응답 크기 보호). */
export const USED_KEEP = 400;

export const TIME_LIMIT_MIN = 1;
export const TIME_LIMIT_MAX = 999;
export const LIVES_MIN = 1;
export const LIVES_MAX = 5;
export const MIN_LEN_MIN = 1;
export const MIN_LEN_MAX = 10;
export const MAX_LEN_MIN = 2;
export const MAX_LEN_MAX = 30;
export const BANNED_CHARS_MAX = 20;

export const BOT_LEVELS = [1, 2, 3, 4, 5];
export const BOT_NAMES = { 1: '순한', 2: '루키', 3: '마스터', 4: '극악', 5: '지옥' };

/** 미션 글자 14종 — engine.js 의 MISSION_CHARS 와 같다. */
export const MISSION_CHARS = ['가', '나', '다', '라', '마', '바', '사', '아', '자', '차', '카', '타', '파', '하'];

/** 첫 글자를 비워 두면 서버가 이 가운데 하나로 연다(화면은 사전에서 고른 글자를 보낼 수 있다). */
const AUTO_START_CHARS = ['가', '나', '다', '라', '마', '바', '사', '아', '자', '차', '카', '타', '파', '하', '기', '모', '부', '시', '이', '정'];

const HANGUL_CHAR_RE = /^[가-힣]$/;
/** 낼 수 있는 단어 — 한글로 시작해 한글로 끝나고 가운데는 한글·숫자·영문. */
export const WORD_PATTERN = /^[가-힣][가-힣0-9A-Za-z]*[가-힣]$/;
const ZERO_WIDTH = /[\u200b-\u200f\u2060\ufeff]/g;
const FULLWIDTH_ALNUM = /[\uff10-\uff19\uff21-\uff3a\uff41-\uff5a]/g;
const CONTROL_RE = /[\u0000-\u001F\u007F-\u009F]/;

const USER_ID_RE = /^u_[0-9a-f]{32}$/;

/* ── 코드 · 기본값 ───────────────────────────────────────── */

export function newCode() {
  const bytes = crypto.getRandomValues(new Uint8Array(CODE_LENGTH));
  let code = '';
  for (let i = 0; i < CODE_LENGTH; i += 1) code += CODE_ALPHABET[bytes[i] % CODE_ALPHABET.length];
  return code;
}

export function normalizeCode(raw) {
  const code = String(raw ?? '').trim().toUpperCase();
  return CODE_RE.test(code) ? code : '';
}

export function defaultRules() {
  return {
    timeLimit: 30,
    noLimit: false,
    lives: 3,
    oneShot: 'allow',
    minLen: 2,
    maxLen: 12,
    bannedChars: '',
    startChar: '',
    mission: true,
  };
}

const clampInt = (value, min, max, fallback) => {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
};

/** 금지 글자 목록: 공백·제어문자를 빼고 한 글자씩, 중복 없이, 20개까지. */
export function normalizeBannedChars(raw) {
  const cleaned = String(raw ?? '')
    .replace(CONTROL_RE, '')
    .replace(/\s+/g, '');
  const out = [];
  for (const ch of cleaned) {
    if (!out.includes(ch)) out.push(ch);
    if (out.length >= BANNED_CHARS_MAX) break;
  }
  return out.join('');
}

/**
 * 화면이 보낸 룰을 검사한다. 범위를 벗어난 숫자는 가까운 경계로 당기고,
 * 형태가 틀린 값은 기본값을 쓴다(실험실은 방장이 마음대로 정하는 공간이다).
 */
export function normalizeRules(raw) {
  const base = defaultRules();
  if (!raw || typeof raw !== 'object') return base;
  const rules = { ...base };
  if (raw.timeLimit != null) rules.timeLimit = clampInt(raw.timeLimit, TIME_LIMIT_MIN, TIME_LIMIT_MAX, base.timeLimit);
  if (typeof raw.noLimit === 'boolean') rules.noLimit = raw.noLimit;
  if (raw.lives != null) rules.lives = clampInt(raw.lives, LIVES_MIN, LIVES_MAX, base.lives);
  if (raw.oneShot === 'ban' || raw.oneShot === 'allow') rules.oneShot = raw.oneShot;
  if (raw.minLen != null) rules.minLen = clampInt(raw.minLen, MIN_LEN_MIN, MIN_LEN_MAX, base.minLen);
  if (raw.maxLen != null) rules.maxLen = clampInt(raw.maxLen, MAX_LEN_MIN, MAX_LEN_MAX, base.maxLen);
  if (rules.minLen > rules.maxLen) rules.maxLen = Math.min(MAX_LEN_MAX, rules.minLen);
  if (raw.bannedChars != null) rules.bannedChars = normalizeBannedChars(raw.bannedChars);
  if (raw.startChar != null) {
    const ch = String(raw.startChar).trim();
    rules.startChar = HANGUL_CHAR_RE.test(ch) ? ch : '';
  }
  if (typeof raw.mission === 'boolean') rules.mission = raw.mission;
  return rules;
}

/* ── 좌석 ────────────────────────────────────────────────── */

export function botName(level) {
  return `봇 Lv.${level} ${BOT_NAMES[level] || ''}`.trim();
}

export function hostSeat(hostId, name, avatarAt = 0) {
  return { kind: 'host', userId: hostId, name, avatarAt: Number(avatarAt || 0), level: 0, status: 'joined' };
}

export function botSeat(level = 2) {
  const lv = clampInt(level, 1, 5, 2);
  return { kind: 'bot', userId: '', name: botName(lv), avatarAt: 0, level: lv, status: 'joined' };
}

/** 좌석 한 칸이 실질적으로 채워졌는가(초대만 된 자리는 아직 사람이 아니다). */
export function seatFilled(seat) {
  if (!seat) return false;
  if (seat.kind === 'bot') return true;
  return seat.status === 'joined' && Boolean(seat.userId);
}

export function filledCount(seats) {
  return (seats || []).filter(seatFilled).length;
}

/**
 * 화면이 보낸 좌석 배열을 검사한다.
 * 구조만 본다 — 친구 좌석의 이름·사진은 호출한 쪽이 DB 에서 다시 채운다(사칭 방지).
 */
export function normalizeSeats(raw, hostId) {
  if (!Array.isArray(raw)) return { ok: false, error: 'seats_invalid' };
  if (raw.length < MIN_SEATS || raw.length > MAX_SEATS) return { ok: false, error: 'seats_count' };
  const seats = [];
  const seen = new Set();
  let hosts = 0;
  for (const item of raw) {
    if (!item || typeof item !== 'object') return { ok: false, error: 'seats_invalid' };
    const kind = item.kind === 'bot' ? 'bot' : item.kind === 'friend' ? 'friend' : item.kind === 'host' ? 'host' : null;
    if (!kind) return { ok: false, error: 'seats_invalid' };
    if (kind === 'host') {
      hosts += 1;
      if (item.userId !== hostId) return { ok: false, error: 'host_seat' };
      seats.push(hostSeat(hostId, String(item.name || '').slice(0, 16), item.avatarAt));
      continue;
    }
    if (kind === 'bot') {
      seats.push(botSeat(item.level));
      continue;
    }
    const userId = String(item.userId || '');
    if (!USER_ID_RE.test(userId)) return { ok: false, error: 'seat_user' };
    if (seen.has(userId)) return { ok: false, error: 'seat_duplicate' };
    if (userId === hostId) return { ok: false, error: 'seat_duplicate' };
    seen.add(userId);
    const status = item.status === 'invited' ? 'invited' : 'joined';
    seats.push({
      kind: 'friend',
      userId,
      name: String(item.name || '').slice(0, 16),
      avatarAt: Number(item.avatarAt || 0),
      level: 0,
      status,
    });
  }
  if (hosts !== 1) return { ok: false, error: 'host_seat' };
  return { ok: true, seats };
}

/* ── 진행 상태 ───────────────────────────────────────────── */

export function emptyState() {
  return {
    turnSeq: 0,
    turnSeat: -1,
    needChar: '',
    missionChar: '',
    deadline: 0,
    scores: [],
    lives: [],
    alive: [],
    used: [],
    chain: [],
    rounds: 0,
    finished: false,
    winner: null,
    reason: '',
    event: null,
    startedAt: 0,
    endedAt: 0,
    startChar: '',
  };
}

export function newRoom({ code, hostId, hostName, hostAvatarAt = 0, rules, seats }) {
  const now = Date.now();
  return {
    code,
    hostId,
    status: 'lobby',
    version: 1,
    seats: seats || [hostSeat(hostId, hostName, hostAvatarAt), botSeat(2)],
    rules: rules || defaultRules(),
    state: emptyState(),
    createdAt: now,
    updatedAt: now,
  };
}

export function parseRoom(row) {
  if (!row) return null;
  let seats = [];
  let rules = defaultRules();
  let state = emptyState();
  try { seats = JSON.parse(row.seats_json || '[]'); } catch { seats = []; }
  try { rules = normalizeRules(JSON.parse(row.rules_json || '{}')); } catch { rules = defaultRules(); }
  try { state = { ...emptyState(), ...JSON.parse(row.state_json || '{}') }; } catch { state = emptyState(); }
  return {
    code: row.code,
    hostId: row.host_id,
    status: row.status,
    version: Number(row.version || 1),
    seats: Array.isArray(seats) ? seats : [],
    rules,
    state,
    createdAt: Number(row.created_at || 0),
    updatedAt: Number(row.updated_at || 0),
  };
}

export function roomRow(room) {
  return {
    code: room.code,
    host_id: room.hostId,
    status: room.status,
    version: room.version,
    seats_json: JSON.stringify(room.seats),
    rules_json: JSON.stringify(room.rules),
    state_json: JSON.stringify(room.state),
    created_at: room.createdAt,
    updated_at: room.updatedAt,
  };
}

/** 화면에 내려 줄 방 모양. 보기 좋게 다듬고 내 자리·방장 여부를 함께 준다. */
export function publicRoom(room, viewerId) {
  const isHost = room.hostId === viewerId;
  let mySeat = -1;
  const seats = room.seats.map((seat, index) => {
    const mine = Boolean(viewerId) && seat.userId === viewerId && seat.kind !== 'bot';
    if (mine && seat.status === 'joined') mySeat = index;
    return {
      kind: seat.kind,
      name: seat.name || (seat.kind === 'bot' ? botName(seat.level) : '친구'),
      avatarAt: Number(seat.avatarAt || 0),
      level: seat.kind === 'bot' ? Number(seat.level || 2) : 0,
      status: seat.kind === 'bot' ? 'joined' : (seat.status || 'joined'),
      userId: seat.kind === 'bot' ? '' : (seat.status === 'joined' || isHost ? seat.userId : ''),
      mine,
    };
  });
  return {
    code: room.code,
    hostId: isHost ? room.hostId : '',
    status: room.status,
    version: room.version,
    seats,
    rules: room.rules,
    state: room.state,
    mySeat,
    isHost,
    filled: filledCount(room.seats),
    now: Date.now(),
  };
}

/* ── 단어 규칙 ───────────────────────────────────────────── */

const BASE = 0xac00;
const JUNGSEONG = 21;
const JONGSEONG = 28;

export function normalizeWord(raw) {
  return String(raw ?? '')
    .normalize('NFC')
    .replace(ZERO_WIDTH, '')
    .replace(FULLWIDTH_ALNUM, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0))
    .replace(/\s+/g, '')
    .trim();
}

/** 표준 두음법칙 대체 음절(리→이, 라→나 …). 해당 없으면 null. */
export function twoeumOf(ch) {
  if (ch.length !== 1) return null;
  const k = ch.charCodeAt(0) - BASE;
  if (k < 0 || k >= 19 * JUNGSEONG * JONGSEONG) return null;
  const cho = Math.floor(k / (JUNGSEONG * JONGSEONG));
  const jung = Math.floor((k % (JUNGSEONG * JONGSEONG)) / JONGSEONG);
  const jong = k % JONGSEONG;
  const iVowels = new Set([2, 3, 6, 7, 12, 17, 20]);
  const compose = (c, u, j) => String.fromCharCode(BASE + (c * JUNGSEONG + u) * JONGSEONG + j);
  if (cho === 5) return compose(iVowels.has(jung) ? 11 : 2, jung, jong); // ㄹ
  if (cho === 2 && iVowels.has(jung)) return compose(11, jung, jong);   // ㄴ
  return null;
}

export function allowedStarts(ch) {
  const alt = ch ? twoeumOf(ch) : null;
  return alt && alt !== ch ? [ch, alt] : [ch];
}

export function countChar(word, ch) {
  if (!ch) return 0;
  let n = 0;
  for (const c of String(word || '')) if (c === ch) n += 1;
  return n;
}

/**
 * 지금 차례에서 이 단어를 낼 수 있는지 구조 규칙으로 본다.
 *   성공: { ok: true, word, score, hits, missionMul }
 *   실패: { ok: false, error, message }
 */
export function checkWord(room, raw) {
  const word = normalizeWord(raw);
  const rules = room.rules;
  if (!word) return { ok: false, error: 'empty', message: '단어를 입력해 주세요.' };
  if (!WORD_PATTERN.test(word)) {
    return { ok: false, error: 'hangul', message: '한글로 시작하고 한글로 끝나는 단어만 쓸 수 있어요.' };
  }
  const length = [...word].length;
  if (length < rules.minLen) {
    return { ok: false, error: 'too_short', message: `${rules.minLen}글자 이상이어야 해요.` };
  }
  if (length > rules.maxLen) {
    return { ok: false, error: 'too_long', message: `${rules.maxLen}글자까지 쓸 수 있어요.` };
  }
  const need = room.state.needChar;
  if (need && !allowedStarts(need).some((start) => word.startsWith(start))) {
    return { ok: false, error: 'start', message: `‘${need}’(으)로 시작해야 해요.` };
  }
  const banned = rules.bannedChars || '';
  for (const ch of word) {
    if (banned.includes(ch)) {
      return { ok: false, error: 'banned', message: `‘${ch}’는 방장이 봉인한 글자예요.` };
    }
  }
  if ((room.state.used || []).includes(word)) {
    return { ok: false, error: 'used', message: '이미 나온 단어예요.' };
  }
  const hits = rules.mission ? countChar(word, room.state.missionChar) : 0;
  const missionMul = hits <= 0 ? 1 : hits === 1 ? 1.5 : hits;
  const score = Math.round((length * length + 4 * length) * missionMul);
  return { ok: true, word, score, hits, missionMul };
}

/* ── 차례 ────────────────────────────────────────────────── */

export function aliveSeatIndexes(room) {
  const seats = room.seats;
  const out = [];
  for (let i = 0; i < seats.length; i += 1) {
    if (room.state.alive[i]) out.push(i);
  }
  return out;
}

/** 지금 자리 다음의 살아 있는 자리(한 바퀴 돌아 자기 자신까지). 없으면 -1. */
export function nextAliveSeat(room, from) {
  const seats = room.seats;
  for (let step = 1; step <= seats.length; step += 1) {
    const index = (from + step) % seats.length;
    if (room.state.alive[index]) return index;
  }
  return -1;
}

function newDeadline(room, now = Date.now()) {
  return room.rules.noLimit ? 0 : now + room.rules.timeLimit * 1000;
}

/** 차례를 다음 생존자에게 넘긴다(같은 이어야 할 글자에서 계속). */
export function passTurn(room, now = Date.now()) {
  const next = nextAliveSeat(room, room.state.turnSeat);
  room.state.turnSeat = next;
  room.state.turnSeq += 1;
  room.state.deadline = next >= 0 ? newDeadline(room, now) : 0;
  return next;
}

export function finishRoom(room, winner, reason, now = Date.now()) {
  room.status = 'over';
  room.state.finished = true;
  room.state.winner = winner;
  room.state.reason = reason || '';
  room.state.endedAt = now;
  room.state.deadline = 0;
  room.state.turnSeat = -1;
}

/** 목숨 하나를 잃는다. 0이 되면 탈락. 살아 있는 사람이 하나만 남으면 그 사람이 이긴다. */
export function loseLife(room, seatIndex, reason, now = Date.now()) {
  const state = room.state;
  if (!state.alive[seatIndex]) return { eliminated: false, over: false };
  state.lives[seatIndex] = Math.max(0, Number(state.lives[seatIndex] || 0) - 1);
  const eliminated = state.lives[seatIndex] <= 0;
  if (eliminated) state.alive[seatIndex] = false;
  const alive = aliveSeatIndexes(room);
  if (alive.length <= 1) {
    finishRoom(room, alive.length === 1 ? alive[0] : null, alive.length === 1 ? 'last-alive' : 'draw', now);
    return { eliminated, over: true };
  }
  state.turnSeq += 1;
  state.event = {
    type: eliminated ? 'eliminated' : 'life',
    seat: seatIndex,
    reason,
    lives: state.lives[seatIndex],
    at: now,
  };
  // 목숨을 잃은 자리는 이번 차례를 마치고 다음 생존자로 넘어간다.
  state.turnSeat = -1;
  const next = nextAliveSeat(room, seatIndex);
  state.turnSeat = next;
  state.deadline = next >= 0 ? newDeadline(room, now) : 0;
  return { eliminated, over: false };
}

/**
 * 단어를 낸다(검사는 호출한 쪽에서 마쳤다).
 * 점수를 더하고, 미션을 돌리고, 다음 차례로 넘긴다.
 */
export function applyWord(room, seatIndex, checked, now = Date.now()) {
  const state = room.state;
  const seat = room.seats[seatIndex];
  state.scores[seatIndex] = Number(state.scores[seatIndex] || 0) + checked.score;
  state.used.push(checked.word);
  if (state.used.length > USED_KEEP) state.used.splice(0, state.used.length - USED_KEEP);
  state.chain.push({
    seat: seatIndex,
    name: seat?.name || '',
    word: checked.word,
    score: checked.score,
    missionHits: checked.hits,
    at: now,
  });
  if (state.chain.length > CHAIN_KEEP) state.chain.splice(0, state.chain.length - CHAIN_KEEP);
  state.needChar = checked.word.charAt(checked.word.length - 1);
  state.rounds += 1;
  let nextMission = null;
  if (checked.hits > 0 && room.rules.mission) {
    const pool = MISSION_CHARS.filter((ch) => ch !== state.missionChar);
    const pick = pool[Math.floor(Math.random() * pool.length)] || MISSION_CHARS[0];
    state.missionChar = pick;
    nextMission = pick;
  }
  state.event = {
    type: 'word',
    seat: seatIndex,
    word: checked.word,
    score: checked.score,
    hits: checked.hits,
    nextMission,
    at: now,
  };
  state.turnSeq += 1;
  const next = nextAliveSeat(room, seatIndex);
  state.turnSeat = next;
  state.deadline = next >= 0 ? newDeadline(room, now) : 0;
  return next;
}

/** 방장이 게임을 시작한다. 좌석에 앉은 사람·봇만 목숨과 점수를 받는다. */
export function startRoom(room, startChar = '', now = Date.now()) {
  const rules = room.rules;
  const seats = room.seats;
  const state = emptyState();
  const chosen = HANGUL_CHAR_RE.test(startChar) ? startChar : rules.startChar;
  state.startChar = chosen || AUTO_START_CHARS[Math.floor(Math.random() * AUTO_START_CHARS.length)];
  state.needChar = state.startChar;
  state.missionChar = rules.mission
    ? MISSION_CHARS[Math.floor(Math.random() * MISSION_CHARS.length)]
    : '';
  state.scores = seats.map(() => 0);
  state.lives = seats.map(() => rules.lives);
  state.alive = seats.map((seat) => seatFilled(seat));
  state.startedAt = now;
  state.turnSeq = 1;
  state.turnSeat = state.alive.findIndex(Boolean);
  state.deadline = state.turnSeat >= 0 ? newDeadline(room, now) : 0;
  state.event = { type: 'start', seat: state.turnSeat, startChar: state.startChar, at: now };
  room.state = state;
  room.status = 'playing';
  room.version += 1;
  room.updatedAt = now;
  return state;
}

/** 다시 한 판(좌석·룰은 그대로, 진행 상태만 비운다). */
export function resetRoom(room, now = Date.now()) {
  room.state = emptyState();
  room.status = 'lobby';
  room.version += 1;
  room.updatedAt = now;
  return room;
}

/** 시간이 다 된 차례를 찾는다(폴링 때 서버가 확인). */
export function expiredTurn(room, now = Date.now()) {
  const state = room.state;
  if (room.status !== 'playing' || room.rules.noLimit) return false;
  return Number(state.deadline) > 0 && now >= Number(state.deadline);
}

/* ── 정리 ───────────────────────────────────────────────── */

/**
 * 오래된 방·초대를 정리한다(방 생성 때, 그리고 이따금 조회 때).
 * 진행 중인 방이라도 3시간 넘게 손대지 않았으면 지운다 — 무료 D1 행이 무한히 쌓이지 않게.
 */
export async function cleanupRooms(env, { force = false } = {}) {
  if (!env.DB) return;
  if (!force && Math.random() > 0.04) return;
  const now = Date.now();
  try {
    await env.DB.prepare('DELETE FROM lab_rooms WHERE updated_at < ?').bind(now - ROOM_TTL_MS).run();
    await env.DB.prepare('DELETE FROM lab_rooms WHERE status = ? AND updated_at < ?')
      .bind('over', now - OVER_TTL_MS).run();
    await env.DB.prepare('DELETE FROM lab_invites WHERE updated_at < ?').bind(now - INVITE_TTL_MS).run();
    await env.DB.prepare(
      `DELETE FROM lab_invites
        WHERE room_code NOT IN (SELECT code FROM lab_rooms) AND status = 'pending'`,
    ).run();
  } catch {
    /* 정리 실패가 요청을 막지는 않는다 */
  }
}

/* ── 폴링 제한 (D1 쓰기 없이) ───────────────────────────── */

/**
 * 상태 폴링은 0.9초에 한 번씩 온다. 다른 API 처럼 D1 카운터를 쓰면 폴링마다 쓰기가 생겨
 * 무료 한도가 녹으므로, Worker 인스턴스 메모리에서 IP·방 별 창(window)만 센다.
 * 인스턴스가 바뀌면 다시 세지만, 폭주를 막는 목적에는 충분하다.
 */
const pollWindows = new Map();

export function checkPollRate(request, roomCode, limit = 200, windowMs = 60 * 1000) {
  const ip = request.headers.get('cf-connecting-ip')
    || (request.headers.get('x-forwarded-for') || '').split(',')[0].trim()
    || 'unknown';
  const key = `${ip}|${roomCode}`;
  const now = Date.now();
  const row = pollWindows.get(key);
  if (!row || now - row.start >= windowMs) {
    if (pollWindows.size > 2000) {
      for (const [k, v] of pollWindows) if (now - v.start >= windowMs) pollWindows.delete(k);
    }
    pollWindows.set(key, { start: now, count: 1 });
    return null;
  }
  if (row.count >= limit) return Math.max(1, Math.ceil((windowMs - (now - row.start)) / 1000));
  row.count += 1;
  return null;
}
