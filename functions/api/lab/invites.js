/**
 * /api/lab/invites — 실험실 초대.
 *
 *   GET  내게 온 초대(대기 중) 목록. 화면이 8초에 한 번쯤 가볍게 확인한다.
 *   POST { id, action: 'accept' | 'decline' } — 수락하면 그 방의 지정한 자리에 즉시 착석한다.
 *
 * 초대는 30분이 지나면 사라지고, 방이 닫혔으면 목록에서 빠진다.
 */
import { ok, fail, readJson, currentSession } from '../../_lib/auth.js';
import {
  parseRoom,
  publicRoom,
  roomRow,
  checkPollRate,
  botSeat,
} from '../../_lib/lab.js';

const INVITE_TTL_MS = 30 * 60 * 1000;
const HANGUL_DISPLAY_MAX = 16;

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

/* ── GET: 내게 온 초대 ─────────────────────────────────── */

export async function onRequestGet({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '실험실 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 초대를 받을 수 있어요.');

  const retryAfter = checkPollRate(request, `INV_${session.id}`, 120, 60 * 1000);
  if (retryAfter) {
    return fail(429, 'rate_limited', '잠시만 기다려 주세요.', { 'retry-after': String(retryAfter) });
  }

  const now = Date.now();
  const rows = await env.DB.prepare(
    `SELECT i.id, i.room_code, i.from_name, i.seat, i.created_at, r.status AS room_status
       FROM lab_invites i
       LEFT JOIN lab_rooms r ON r.code = i.room_code
      WHERE i.to_id = ? AND i.status = 'pending' AND i.updated_at > ?
      ORDER BY i.created_at DESC
      LIMIT 6`,
  ).bind(session.id, now - INVITE_TTL_MS).all();

  const invites = [];
  for (const row of rows?.results || []) {
    if (!row.room_status) {
      // 방이 이미 닫혔다 — 목록에 남기지 않고 정리한다.
      await env.DB.prepare("UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE id = ?")
        .bind(now, row.id).run();
      continue;
    }
    invites.push({
      id: row.id,
      code: row.room_code,
      fromName: row.from_name,
      seat: Number(row.seat),
      createdAt: Number(row.created_at),
      roomStatus: row.room_status,
    });
  }
  return ok({ invites, now }, { 'cache-control': 'no-store' });
}

/* ── POST: 수락 · 거절 ─────────────────────────────────── */

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '실험실 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 초대에 답할 수 있어요.');

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const body = parsed.body;
  const id = String(body.id || '');
  const action = body.action === 'decline' ? 'decline' : body.action === 'accept' ? 'accept' : '';
  if (!id || !action) return fail(400, 'bad_request', '초대를 다시 확인해 주세요.');

  const invite = await env.DB.prepare(
    'SELECT id, room_code, from_id, from_name, to_id, seat, status, updated_at FROM lab_invites WHERE id = ?',
  ).bind(id).first();
  if (!invite || invite.to_id !== session.id || invite.status !== 'pending') {
    return fail(404, 'invite_not_found', '이미 처리됐거나 사라진 초대예요.');
  }
  if (Number(invite.updated_at) < Date.now() - INVITE_TTL_MS) {
    await env.DB.prepare("UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE id = ?")
      .bind(Date.now(), id).run();
    return fail(410, 'invite_expired', '초대가 만료됐어요. 방장에게 다시 부탁해 주세요.');
  }

  const room = await loadRoom(env, invite.room_code);
  if (!room) {
    await env.DB.prepare("UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE id = ?")
      .bind(Date.now(), id).run();
    return fail(404, 'room_not_found', '방이 이미 닫혔어요.');
  }

  const seatIndex = Number(invite.seat);
  const seat = room.seats[seatIndex];
  const now = Date.now();

  if (action === 'decline') {
    await env.DB.prepare("UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE id = ?").bind(now, id).run();
    if (room.status === 'lobby' && seat && seat.kind === 'friend' && seat.userId === session.id && seat.status === 'invited') {
      const expectVersion = Number(room.version);
      if (room.seats.length > 2) room.seats.splice(seatIndex, 1);
      else room.seats[seatIndex] = botSeat(2);
      await saveRoom(env, room, expectVersion);
    }
    return ok({ declined: true }, { 'cache-control': 'no-store' });
  }

  // 수락
  if (room.status !== 'lobby') return fail(409, 'room_playing', '이미 게임이 시작된 방이에요.');
  if (!seat || seat.kind !== 'friend' || seat.userId !== session.id) {
    await env.DB.prepare("UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE id = ?").bind(now, id).run();
    return fail(409, 'seat_changed', '자리가 바뀌었어요. 방장에게 다시 초대를 부탁해 주세요.');
  }
  if (seat.status === 'joined') {
    await env.DB.prepare("UPDATE lab_invites SET status = 'accepted', updated_at = ? WHERE id = ?").bind(now, id).run();
    return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
  }

  const user = await env.DB.prepare(
    'SELECT username, nickname, display_name, avatar_updated_at FROM users WHERE id = ?',
  ).bind(session.id).first();
  const name = String(user?.nickname || user?.display_name || user?.username || '친구').slice(0, HANGUL_DISPLAY_MAX);
  const expectVersion = Number(room.version);
  room.seats[seatIndex] = {
    ...seat,
    status: 'joined',
    name,
    avatarAt: Number(user?.avatar_updated_at || 0),
  };
  if (!(await saveRoom(env, room, expectVersion))) {
    return fail(409, 'version_conflict', '방 상태가 막 바뀌었어요. 다시 시도해 주세요.');
  }
  await env.DB.prepare("UPDATE lab_invites SET status = 'accepted', updated_at = ? WHERE id = ?").bind(now, id).run();
  // 다른 방에서 나를 기다리던 초대는 정리한다(한 번에 한 방).
  await env.DB.prepare(
    "UPDATE lab_invites SET status = 'declined', updated_at = ? WHERE to_id = ? AND status = 'pending' AND id != ?",
  ).bind(now, session.id, id).run();

  return ok({ room: publicRoom(room, session.id) }, { 'cache-control': 'no-store' });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'GET, POST' });
}
