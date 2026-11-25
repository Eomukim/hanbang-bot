/**
 * /api/lab/rooms/:code — 실험실 방 하나.
 *
 *   GET    상태 조회(참가자) — 화면이 0.9초마다 부른다. 1행만 읽는다.
 *   PATCH  방장(신) 권한 동작 — 좌석·룰·초대·시작·차례 넘기기·글자 봉인·제한 시간·봇 난이도·재대결
 *   DELETE 방 닫기(방장)
 *
 * 권한: 방장(`host_id === session.id`)만 좌석·룰·게임 시작·신 개입을 할 수 있고,
 *       상태 조회는 그 방에 앉은 참가자(수락해 'joined' 가 된 자리)만 할 수 있다.
 *       버전(`version`)이 어긋난 PATCH 는 409 로 돌려보내 화면이 다시 맞추게 한다(낙관적 락).
 */
import { ok, fail, readJson, currentSession, hitThrottle, publicUser } from '../../../_lib/auth.js';
import { pairKey } from '../../../_lib/social.js';
import {
  MAX_SEATS,
  MIN_SEATS,
  BOT_LEVELS,
  normalizeRules,
  normalizeSeats,
  parseRoom,
  publicRoom,
  roomRow,
  cleanupRooms,
  checkPollRate,
  normalizeCode,
  filledCount,
  startRoom,
  resetRoom,
  passTurn,
  botName,
  normalizeBannedChars,
  TIME_LIMIT_MIN,
  TIME_LIMIT_MAX,
} from '../../../_lib/lab.js';

const HANGUL_CHAR_RE = /^[가-힣]$/;

async function loadRoom(env, code) {
  const row = await env.DB.prepare('SELECT * FROM lab_rooms WHERE code = ?').bind(code).first();
  return row ? parseRoom(row) : null;
}

/** 낙관적 락 저장. expectVersion 과 지금 행의 version 이 같을 때만 쓴다. */
async function saveRoom(env, room, expectVersion) {
  room.version = expectVersion + 1;
  room.updatedAt = Date.now();
  const row = roomRow(room);
  const result = await env.DB.prepare(
    `UPDATE lab_rooms
        SET status = ?, version = ?, seats_json = ?, rules_json = ?, state_json = ?, updated_at = ?
      WHERE code = ? AND version = ?`,
  ).bind(row.status, row.version, row.seats_json, row.rules_json, row.state_json, row.updated_at,
    row.code, expectVersion).run();
  return Number(result?.meta?.changes || 0) > 0;
}

function participant(room, userId) {
  if (!userId) return false;
  if (room.hostId === userId) return true;
  return room.seats.some((seat) => seat.kind !== 'bot' && seat.userId === userId && seat.status === 'joined');
}

async function resolveFriends(env, seats) {
  const ids = seats.filter((seat) => seat.kind === 'friend').map((seat) => seat.userId).filter(Boolean);
  if (!ids.length) return seats;
  const placeholders = ids.map(() => '?').join(',');
  const rows = await env.DB.prepare(
    `SELECT id, username, nickname, display_name, avatar_updated_at FROM users WHERE id IN (${placeholders})`,
  ).bind(...ids).all();
  const byId = new Map((rows?.results || []).map((row) => [row.id, row]));
  return seats.map((seat) => {
    if (seat.kind !== 'friend') return seat;
    const row = byId.get(seat.userId);
    if (!row) return seat;
    return {
      ...seat,
      name: row.nickname || row.display_name || row.username,
      avatarAt: Number(row.avatar_updated_at || 0),
    };
  });
}

async function cancelInvites(env, code, { seat = null, userId = null, exceptUserId = null } = {}) {
  const now = Date.now();
  if (seat != null) {
    await env.DB.prepare(
      "UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE room_code = ? AND seat = ? AND status = 'pending'",
    ).bind(now, code, seat).run();
  }
  if (userId) {
    await env.DB.prepare(
      "UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE room_code = ? AND to_id = ? AND status = 'pending'",
    ).bind(now, code, userId).run();
  }
  if (exceptUserId != null) {
    await env.DB.prepare(
      "UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE room_code = ? AND status = 'pending' AND to_id != ?",
    ).bind(now, code, exceptUserId).run();
  }
}

/** 그 자리에 기다리는 초대가 없으면 만든다(있으면 그대로). */
async function ensureInvite(env, room, seatIndex, hostName) {
  const seat = room.seats[seatIndex];
  if (!seat || seat.kind !== 'friend' || !seat.userId) return;
  const existing = await env.DB.prepare(
    `SELECT id FROM lab_invites
      WHERE room_code = ? AND seat = ? AND to_id = ? AND status = 'pending'`,
  ).bind(room.code, seatIndex, seat.userId).first();
  if (existing) return;
  const now = Date.now();
  await env.DB.prepare(
    `INSERT INTO lab_invites (id, room_code, from_id, from_name, to_id, seat, status, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)`,
  ).bind(`li_${crypto.randomUUID().replace(/-/g, '')}`, room.code, room.hostId, hostName, seat.userId,
    seatIndex, now, now).run();
}

/* ── GET: 상태 조회 ─────────────────────────────────────── */

export async function onRequestGet({ request, env, params }) {
  if (!env.DB) return fail(503, 'not_configured', '실험실 서버가 아직 준비되지 않았어요.');
  const code = normalizeCode(params?.code);
  if (!code) return fail(400, 'bad_code', '방 코드를 다시 확인해 주세요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 실험실 방에 들어갈 수 있어요.');

  const retryAfter = checkPollRate(request, code, 200, 60 * 1000);
  if (retryAfter) {
    return fail(429, 'rate_limited', '새로 고침이 너무 잦아요. 잠시만 기다려 주세요.', {
      'retry-after': String(retryAfter),
    });
  }

  const room = await loadRoom(env, code);
  if (!room) return fail(404, 'room_not_found', '방을 찾지 못했어요. 코드가 맞는지 확인해 주세요.');
  if (!participant(room, session.id)) {
    return fail(403, 'not_in_room', '이 방에 앉은 사람만 볼 수 있어요.');
  }
  await cleanupRooms(env);

  return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
}

/* ── PATCH: 방장 동작 ──────────────────────────────────── */

export async function onRequestPatch({ request, env, params }) {
  if (!env.DB) return fail(503, 'not_configured', '실험실 서버가 아직 준비되지 않았어요.');
  const code = normalizeCode(params?.code);
  if (!code) return fail(400, 'bad_code', '방 코드를 다시 확인해 주세요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 실험실 방을 열 수 있어요.');

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const body = parsed.body;

  const room = await loadRoom(env, code);
  if (!room) return fail(404, 'room_not_found', '방을 찾지 못했어요. 이미 닫혔을 수 있어요.');
  if (room.hostId !== session.id) {
    return fail(403, 'not_host', '방장만 방 설정을 바꿀 수 있어요.');
  }

  const action = String(body.action || '');
  const expectVersion = Number(body.version);
  if (!Number.isFinite(expectVersion)) {
    return fail(400, 'version_required', '방 상태를 다시 불러온 뒤 시도해 주세요.');
  }

  const nameOfMe = publicUser(session).displayName || publicUser(session).username;

  if (action === 'invite') {
    const seatIndex = Number(body.seat);
    const userId = String(body.userId || '');
    if (!Number.isInteger(seatIndex) || seatIndex < 0 || seatIndex >= MAX_SEATS) {
      return fail(400, 'seat_invalid', '자리 번호를 다시 확인해 주세요.');
    }
    if (!/^u_[0-9a-f]{32}$/.test(userId)) return fail(400, 'user_invalid', '초대할 친구를 다시 골라 주세요.');
    if (room.status !== 'lobby') return fail(409, 'room_playing', '게임 중에는 새로 초대할 수 없어요. 다음 판을 준비할 때 초대해 주세요.');
    if (seatIndex >= room.seats.length) return fail(400, 'seat_invalid', '그 자리가 없어요.');
    const seat = room.seats[seatIndex];
    if (seat.kind === 'host') return fail(400, 'seat_invalid', '내 자리에는 초대할 수 없어요.');
    if (seat.kind === 'friend' && seat.status === 'joined') {
      return fail(409, 'seat_taken', '이미 친구가 앉아 있는 자리예요.');
    }
    if (userId === session.id) return fail(400, 'self_invite', '나 자신은 초대할 수 없어요.');
    const rel = await env.DB.prepare('SELECT status FROM friendships WHERE pair_key = ?')
      .bind(pairKey(session.id, userId)).first();
    if (!rel || rel.status !== 'accepted') return fail(403, 'not_friend', '친구에게만 초대할 수 있어요.');
    const target = await env.DB.prepare(
      'SELECT id, username, nickname, display_name, avatar_updated_at FROM users WHERE id = ?',
    ).bind(userId).first();
    if (!target) return fail(404, 'user_not_found', '그 사람을 찾지 못했어요.');

    const limits = await hitThrottle(env, `lab:invite:u:${session.id}`, 60, 600);
    if (!limits.allowed) {
      return fail(429, 'rate_limited', '초대를 너무 많이 보냈어요. 잠시 후 다시 시도해 주세요.', {
        'retry-after': String(limits.retryAfter),
      });
    }

    // 그 자리에 있던 예전 초대·사람은 정리하고 새로 앉힌다(초대 상태).
    if (seat.kind === 'friend' && seat.userId) await cancelInvites(env, code, { userId: seat.userId });
    await cancelInvites(env, code, { seat: seatIndex });
    room.seats[seatIndex] = {
      kind: 'friend',
      userId,
      name: target.nickname || target.display_name || target.username,
      avatarAt: Number(target.avatar_updated_at || 0),
      level: 0,
      status: 'invited',
    };
    if (!(await saveRoom(env, room, expectVersion))) {
      return fail(409, 'version_conflict', '방 상태가 막 바뀌었어요. 다시 시도해 주세요.');
    }
    await ensureInvite(env, room, seatIndex, nameOfMe);
    return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
  }

  if (action === 'seats') {
    if (room.status !== 'lobby') return fail(409, 'room_playing', '게임 중에는 자리를 바꿀 수 없어요.');
    const checked = normalizeSeats(body.seats, session.id);
    if (!checked.ok) return fail(400, checked.error, '자리 배치를 다시 확인해 주세요.');
    const before = room.seats;
    const joinedBefore = new Set(
      before.filter((seat) => seat.kind === 'friend' && seat.status === 'joined').map((seat) => seat.userId),
    );
    let seats = checked.seats.map((seat) => {
      if (seat.kind !== 'friend') return seat;
      return { ...seat, status: joinedBefore.has(seat.userId) ? 'joined' : 'invited' };
    });
    seats = await resolveFriends(env, seats);
    room.seats = seats;
    if (!(await saveRoom(env, room, expectVersion))) {
      return fail(409, 'version_conflict', '방 상태가 막 바뀌었어요. 다시 시도해 주세요.');
    }
    // 남아 있는 '초대 중' 자리만 초대 행을 유지하고, 사라진 자리의 초대는 거둔다.
    const invited = new Map();
    for (let i = 0; i < room.seats.length; i += 1) {
      const seat = room.seats[i];
      if (seat.kind === 'friend' && seat.status === 'invited') {
        invited.set(`${seat.userId}|${i}`, i);
        await ensureInvite(env, room, i, nameOfMe);
      }
    }
    const pending = await env.DB.prepare(
      "SELECT id, to_id, seat FROM lab_invites WHERE room_code = ? AND status = 'pending'",
    ).bind(code).all();
    for (const row of pending?.results || []) {
      if (!invited.has(`${row.to_id}|${Number(row.seat)}`)) {
        await env.DB.prepare("UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE id = ?")
          .bind(Date.now(), row.id).run();
      }
    }
    return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
  }

  if (action === 'rules') {
    if (room.status === 'playing') return fail(409, 'room_playing', '게임 중에는 시작 전 룰을 바꿀 수 없어요. 신 패널을 써 주세요.');
    room.rules = normalizeRules(body.rules);
    if (!(await saveRoom(env, room, expectVersion))) {
      return fail(409, 'version_conflict', '방 상태가 막 바뀌었어요. 다시 시도해 주세요.');
    }
    return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
  }

  if (action === 'start') {
    if (room.status === 'playing') return fail(409, 'already_playing', '이미 시작했어요.');
    if (filledCount(room.seats) < MIN_SEATS) {
      return fail(400, 'need_players', '최소 두 자리를 채워야 시작할 수 있어요.');
    }
    const startChar = HANGUL_CHAR_RE.test(String(body.startChar || '')) ? String(body.startChar) : '';
    startRoom(room, startChar);
    if (!(await saveRoom(env, room, expectVersion))) {
      return fail(409, 'version_conflict', '방 상태가 막 바뀌었어요. 다시 시도해 주세요.');
    }
    // 시작하면 아직 수락하지 않은 초대는 모두 거둔다(자리는 초대 중인 채로 남는다).
    await env.DB.prepare(
      "UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE room_code = ? AND status = 'pending'",
    ).bind(Date.now(), code).run();
    return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
  }

  if (action === 'pass') {
    if (room.status !== 'playing') return fail(409, 'not_playing', '지금은 진행 중인 판이 없어요.');
    const from = room.state.turnSeat;
    const next = passTurn(room);
    if (next < 0) return fail(409, 'not_playing', '넘길 차례가 없어요.');
    room.state.event = { type: 'pass', seat: from, to: next, by: 'god', at: Date.now() };
    if (!(await saveRoom(env, room, expectVersion))) {
      return fail(409, 'version_conflict', '차례가 막 바뀌었어요. 다시 시도해 주세요.');
    }
    return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
  }

  if (action === 'seal') {
    const ch = String(body.char || '').trim();
    if (!HANGUL_CHAR_RE.test(ch)) return fail(400, 'char_invalid', '봉인할 글자를 한 글자로 정해 주세요.');
    const current = room.rules.bannedChars || '';
    if (current.includes(ch)) return fail(409, 'already_banned', `‘${ch}’는 이미 봉인했어요.`);
    room.rules.bannedChars = normalizeBannedChars(current + ch);
    room.state.event = { type: 'seal', char: ch, by: 'god', at: Date.now() };
    if (!(await saveRoom(env, room, expectVersion))) {
      return fail(409, 'version_conflict', '방 상태가 막 바뀌었어요. 다시 시도해 주세요.');
    }
    return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
  }

  if (action === 'timeLimit') {
    if (room.rules.noLimit === false && room.status !== 'playing') {
      return fail(409, 'not_playing', '게임 중에만 제한 시간을 바꿀 수 있어요. 시작 전에는 룰에서 정해 주세요.');
    }
    const noLimit = Boolean(body.noLimit);
    const raw = Math.round(Number(body.timeLimit));
    if (!noLimit && (!Number.isFinite(raw) || raw < TIME_LIMIT_MIN || raw > TIME_LIMIT_MAX)) {
      return fail(400, 'time_invalid', `제한 시간은 ${TIME_LIMIT_MIN}~${TIME_LIMIT_MAX}초 사이로 정해 주세요.`);
    }
    room.rules.noLimit = noLimit;
    if (!noLimit) room.rules.timeLimit = Math.max(TIME_LIMIT_MIN, Math.min(TIME_LIMIT_MAX, raw));
    room.state.deadline = noLimit ? 0 : Date.now() + room.rules.timeLimit * 1000;
    room.state.event = {
      type: 'timeLimit', timeLimit: room.rules.timeLimit, noLimit, by: 'god', at: Date.now(),
    };
    if (!(await saveRoom(env, room, expectVersion))) {
      return fail(409, 'version_conflict', '방 상태가 막 바뀌었어요. 다시 시도해 주세요.');
    }
    return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
  }

  if (action === 'botLevel') {
    const seatIndex = Number(body.seat);
    const level = Number(body.level);
    if (!Number.isInteger(seatIndex) || seatIndex < 0 || seatIndex >= room.seats.length) {
      return fail(400, 'seat_invalid', '자리 번호를 다시 확인해 주세요.');
    }
    if (room.seats[seatIndex].kind !== 'bot') return fail(400, 'not_bot', '봇 자리만 난이도를 바꿀 수 있어요.');
    if (!BOT_LEVELS.includes(level)) return fail(400, 'level_invalid', '봇 난이도는 Lv.1~5 사이예요.');
    room.seats[seatIndex] = { ...room.seats[seatIndex], level, name: botName(level) };
    room.state.event = { type: 'botLevel', seat: seatIndex, level, by: 'god', at: Date.now() };
    if (!(await saveRoom(env, room, expectVersion))) {
      return fail(409, 'version_conflict', '방 상태가 막 바뀌었어요. 다시 시도해 주세요.');
    }
    return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
  }

  if (action === 'rematch') {
    resetRoom(room);
    await env.DB.prepare(
      "UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE room_code = ? AND status = 'pending'",
    ).bind(Date.now(), code).run();
    if (!(await saveRoom(env, room, expectVersion))) {
      return fail(409, 'version_conflict', '방 상태가 막 바뀌었어요. 다시 시도해 주세요.');
    }
    return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
  }

  return fail(400, 'action_invalid', '알 수 없는 요청이에요.');
}

/* ── DELETE: 방 닫기 ───────────────────────────────────── */

export async function onRequestDelete({ request, env, params }) {
  if (!env.DB) return fail(503, 'not_configured', '실험실 서버가 아직 준비되지 않았어요.');
  const code = normalizeCode(params?.code);
  if (!code) return fail(400, 'bad_code', '방 코드를 다시 확인해 주세요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 방을 닫을 수 있어요.');

  const room = await loadRoom(env, code);
  if (!room) return ok({ closed: true });
  if (room.hostId !== session.id) return fail(403, 'not_host', '방장만 방을 닫을 수 있어요.');

  await env.DB.prepare('DELETE FROM lab_invites WHERE room_code = ?').bind(code).run();
  await env.DB.prepare('DELETE FROM lab_rooms WHERE code = ? AND host_id = ?').bind(code, session.id).run();
  return ok({ closed: true }, { 'cache-control': 'no-store' });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'GET, PATCH, DELETE' });
}
