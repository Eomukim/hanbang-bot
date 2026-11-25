/**
 * POST /api/lab/rooms — 실험실 방을 만든다(로그인 필수, 방장 = 나).
 *
 * body: { rules?: {...}, seats?: [...] }   (둘 다 없으면 `나 + 봇 Lv.2` 2자리로 시작)
 *
 * - 한 사람은 실험실 방을 하나만 가진다. 새로 만들면 예전 방과 그 초대를 지운다.
 * - 방 코드는 6자리(헷갈리는 O·0·I·1 제외)이고, 겹치면 다시 뽑는다.
 * - 만들 때 오래된 방·초대를 함께 정리한다(D1 행이 무한히 쌓이지 않게).
 */
import { ok, fail, readJson, currentSession, hitThrottle, clientIp, publicUser } from '../../../_lib/auth.js';
import {
  newCode,
  newRoom,
  normalizeRules,
  normalizeSeats,
  parseRoom,
  publicRoom,
  roomRow,
  cleanupRooms,
  hostSeat,
  botSeat,
} from '../../../_lib/lab.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '실험실 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 실험실 방을 만들 수 있어요.');

  const ip = clientIp(request) || 'unknown';
  const perIp = await hitThrottle(env, `lab:create:ip:${ip}`, 40, 600);
  if (!perIp.allowed) {
    return fail(429, 'rate_limited', '방을 너무 자주 만들었어요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(perIp.retryAfter),
    });
  }
  const perUser = await hitThrottle(env, `lab:create:u:${session.id}`, 15, 600);
  if (!perUser.allowed) {
    return fail(429, 'rate_limited', '방을 너무 자주 만들었어요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(perUser.retryAfter),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const body = parsed.body;

  const me = publicUser(session);
  const name = me.displayName || me.username;

  let seats = [hostSeat(session.id, name, me.avatarAt), botSeat(2)];
  if (body.seats != null) {
    const checked = normalizeSeats(body.seats, session.id);
    if (!checked.ok) return fail(400, checked.error, '자리 배치를 다시 확인해 주세요.');
    seats = checked.seats;
    // 새 방에서는 친구를 초대로만 앉힌다(초대 수락 전에는 'invited').
    seats = seats.map((seat) => (seat.kind === 'friend' ? { ...seat, status: 'invited' } : seat));
  }
  // 친구 자리의 이름은 언제나 서버가 DB 에서 채운다(사칭 방지).
  const friendIds = seats.filter((seat) => seat.kind === 'friend').map((seat) => seat.userId);
  if (friendIds.length) {
    const placeholders = friendIds.map(() => '?').join(',');
    const rows = await env.DB.prepare(
      `SELECT id, username, nickname, display_name, avatar_updated_at FROM users WHERE id IN (${placeholders})`,
    ).bind(...friendIds).all();
    const byId = new Map((rows?.results || []).map((row) => [row.id, row]));
    seats = seats.map((seat) => {
      if (seat.kind !== 'friend') return seat;
      const row = byId.get(seat.userId);
      if (!row) return { ...seat, status: 'invited', name: '' };
      return {
        ...seat,
        name: row.nickname || row.display_name || row.username,
        avatarAt: Number(row.avatar_updated_at || 0),
      };
    });
  }

  await cleanupRooms(env, { force: true });

  // 이전 방(과 그 초대) 정리 — 한 사람에게 방은 하나.
  const mine = await env.DB.prepare('SELECT code FROM lab_rooms WHERE host_id = ?').bind(session.id).all();
  const oldCodes = (mine?.results || []).map((row) => row.code);
  if (oldCodes.length) {
    const marks = oldCodes.map(() => '?').join(',');
    await env.DB.prepare(`DELETE FROM lab_invites WHERE room_code IN (${marks})`).bind(...oldCodes).run();
    await env.DB.prepare('DELETE FROM lab_rooms WHERE host_id = ?').bind(session.id).run();
  }
  // 다른 방에서 나를 기다리는 초대도 정리(새 방으로 옮겼으니).
  await env.DB.prepare("DELETE FROM lab_invites WHERE to_id = ? AND status = 'pending'").bind(session.id).run();

  const rules = normalizeRules(body.rules);
  let code = '';
  for (let attempt = 0; attempt < 6 && !code; attempt += 1) {
    const candidate = newCode();
    const taken = await env.DB.prepare('SELECT 1 AS hit FROM lab_rooms WHERE code = ?').bind(candidate).first();
    if (!taken) code = candidate;
  }
  if (!code) return fail(503, 'code_exhausted', '방 코드를 만들지 못했어요. 잠시 후 다시 시도해 주세요.');

  const room = newRoom({ code, hostId: session.id, hostName: name, hostAvatarAt: me.avatarAt, rules, seats });
  const row = roomRow(room);
  await env.DB.prepare(
    `INSERT INTO lab_rooms (code, host_id, status, version, seats_json, rules_json, state_json, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).bind(row.code, row.host_id, row.status, row.version, row.seats_json, row.rules_json, row.state_json,
    row.created_at, row.updated_at).run();

  return ok({ room: publicRoom(parseRoom(row), session.id) }, { 'cache-control': 'no-store' });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'POST' });
}
