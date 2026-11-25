/**
 * POST /api/lab/rooms/:code/leave — 앉은 자리에서 일어난다(참가자).
 *
 * - 준비 중: 자리를 비운다(최소 2자리를 지켜야 하면 그 자리는 봇이 된다). 내게 온 초대도 거둔다.
 * - 게임 중: 탈락 처리되고, 남은 사람이 하나면 그 사람이 이긴다.
 * - 방장은 방을 닫아야 한다(DELETE). 방장 자리는 비울 수 없다.
 */
import { ok, fail, currentSession } from '../../../../_lib/auth.js';
import {
  normalizeCode,
  parseRoom,
  publicRoom,
  roomRow,
  aliveSeatIndexes,
  finishRoom,
  nextAliveSeat,
  botSeat,
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

export async function onRequestPost({ request, env, params }) {
  if (!env.DB) return fail(503, 'not_configured', '실험실 서버가 아직 준비되지 않았어요.');
  const code = normalizeCode(params?.code);
  if (!code) return fail(400, 'bad_code', '방 코드를 다시 확인해 주세요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 실험실 방에서 나올 수 있어요.');

  const room = await loadRoom(env, code);
  if (!room) return ok({ left: true, closed: true });
  if (room.hostId === session.id) {
    return fail(400, 'host_leave', '방장은 방을 닫아 주세요.');
  }
  const index = room.seats.findIndex(
    (seat) => seat.kind !== 'bot' && seat.userId === session.id && seat.status === 'joined',
  );
  if (index < 0) {
    await env.DB.prepare("UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE room_code = ? AND to_id = ? AND status = 'pending'")
      .bind(Date.now(), code, session.id).run();
    return ok({ left: true });
  }

  const expectVersion = Number(room.version);
  if (room.status === 'playing') {
    const state = room.state;
    state.lives[index] = 0;
    state.alive[index] = false;
    state.turnSeq += 1;
    const alive = aliveSeatIndexes(room);
    if (alive.length <= 1) {
      finishRoom(room, alive.length === 1 ? alive[0] : null, 'leave', Date.now());
    } else {
      if (Number(state.turnSeat) === index) {
        const next = nextAliveSeat(room, index);
        state.turnSeat = next;
        state.deadline = room.rules.noLimit ? 0 : Date.now() + room.rules.timeLimit * 1000;
      }
      state.event = { type: 'leave', seat: index, at: Date.now() };
    }
  } else {
    if (room.seats.length > 2) room.seats.splice(index, 1);
    else room.seats[index] = botSeat(2);
  }

  if (!(await saveRoom(env, room, expectVersion))) {
    return fail(409, 'version_conflict', '방 상태가 막 바뀌었어요. 다시 시도해 주세요.');
  }
  await env.DB.prepare("UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE room_code = ? AND to_id = ? AND status = 'pending'")
    .bind(Date.now(), code, session.id).run();
  return ok({ left: true }, { 'cache-control': 'no-store' });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'POST' });
}
