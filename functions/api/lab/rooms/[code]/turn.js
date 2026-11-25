/**
 * POST /api/lab/rooms/:code/turn — 한 수를 낸다(단어 · 시간 초과 · 막힘).
 *
 * body: { seat, turnSeq, word?, action?: 'word' | 'timeout' | 'stuck' }
 *
 * - 내 자리(사람)만 낼 수 있고, 봇 자리는 방장 화면이 대신 낸다(engine.js AI).
 * - `turnSeq` 가 지금 차례와 다르면 409 → 화면이 상태를 다시 읽고 한 번 더 시도한다
 *   (동시 제출·턴 꼬임 방지).
 * - 'timeout' 은 서버 시계로 제한 시간이 실제로 지났을 때만 받는다(참가자 누구나 알릴 수 있다).
 * - 'stuck' 은 이을 단어가 없다고 선언하는 것 — 목숨 하나를 잃고 다음 생존자로 넘어간다.
 * - 목숨이 0이 되면 탈락하고, 살아 있는 사람이 하나만 남으면 그 사람이 이긴다.
 */
import {
  ok, fail, json, readJson, currentSession, hitThrottle,
} from '../../../../_lib/auth.js';
import {
  normalizeCode,
  parseRoom,
  publicRoom,
  roomRow,
  checkWord,
  applyWord,
  loseLife,
  normalizeWord,
} from '../../../../_lib/lab.js';

async function loadRoom(env, code) {
  const row = await env.DB.prepare('SELECT * FROM lab_rooms WHERE code = ?').bind(code).first();
  return row ? parseRoom(row) : null;
}

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

function stale(room, viewerId, message) {
  return json({
    ok: false,
    error: 'stale',
    message,
    room: publicRoom(room, viewerId),
  }, 409, { 'cache-control': 'no-store' });
}

export async function onRequestPost({ request, env, params }) {
  if (!env.DB) return fail(503, 'not_configured', '실험실 서버가 아직 준비되지 않았어요.');
  const code = normalizeCode(params?.code);
  if (!code) return fail(400, 'bad_code', '방 코드를 다시 확인해 주세요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 실험실에서 놀 수 있어요.');

  const limit = await hitThrottle(env, `lab:turn:u:${session.id}`, 150, 60);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '너무 빠르게 보내고 있어요. 잠시만 기다려 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const body = parsed.body;

  const room = await loadRoom(env, code);
  if (!room) return fail(404, 'room_not_found', '방을 찾지 못했어요. 이미 닫혔을 수 있어요.');
  if (room.status !== 'playing') return fail(409, 'not_playing', '지금은 진행 중인 판이 없어요.');

  const seatIndex = Number(body.seat);
  if (!Number.isInteger(seatIndex) || seatIndex < 0 || seatIndex >= room.seats.length) {
    return fail(400, 'seat_invalid', '자리 번호를 다시 확인해 주세요.');
  }
  const seat = room.seats[seatIndex];
  const isHost = room.hostId === session.id;
  if (seat.kind === 'bot') {
    if (!isHost) return fail(403, 'not_host', '봇 차례는 방장 화면이 진행해요.');
  } else if (seat.userId !== session.id) {
    return fail(403, 'not_your_seat', '내 자리의 차례만 낼 수 있어요.');
  }
  if (!room.state.alive[seatIndex]) return fail(409, 'seat_out', '이미 탈락한 자리예요.');

  const turnSeq = Number(body.turnSeq);
  if (!Number.isFinite(turnSeq) || turnSeq !== Number(room.state.turnSeq)) {
    return stale(room, session.id, '차례가 막 바뀌었어요.');
  }
  if (Number(room.state.turnSeat) !== seatIndex) {
    return stale(room, session.id, '아직 이 자리의 차례가 아니에요.');
  }

  const action = body.action === 'timeout' || body.action === 'stuck' ? body.action : 'word';
  const expectVersion = Number(room.version);

  if (action === 'timeout') {
    const now = Date.now();
    if (room.rules.noLimit) return fail(400, 'no_limit', '제한 시간이 없는 판이에요.');
    if (now < Number(room.state.deadline) - 400) {
      return stale(room, session.id, '아직 시간이 남았어요.');
    }
    loseLife(room, seatIndex, 'timeout', now);
    if (!(await saveRoom(env, room, expectVersion))) {
      return stale(await loadRoom(env, code) || room, session.id, '차례가 막 바뀌었어요.');
    }
    return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
  }

  if (action === 'stuck') {
    loseLife(room, seatIndex, 'stuck', Date.now());
    if (!(await saveRoom(env, room, expectVersion))) {
      return stale(await loadRoom(env, code) || room, session.id, '차례가 막 바뀌었어요.');
    }
    return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
  }

  const checked = checkWord(room, body.word);
  if (!checked.ok) {
    return json({
      ok: false,
      error: checked.error,
      message: checked.message,
      word: normalizeWord(body.word),
      room: publicRoom(room, session.id),
    }, 400, { 'cache-control': 'no-store' });
  }

  // 봇 차례 난이도·미션은 화면이 계산해 보내지 않는다 — 점수·미션은 서버가 방 룰로 다시 매긴다.
  applyWord(room, seatIndex, checked, Date.now());
  if (!(await saveRoom(env, room, expectVersion))) {
    return stale(await loadRoom(env, code) || room, session.id, '차례가 막 바뀌었어요.');
  }
  return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'POST' });
}
