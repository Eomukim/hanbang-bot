/**
 * POST /api/auth/delete
 * 지금 로그인한 계정을 완전히 지운다(되돌릴 수 없음).
 *
 * 본인 재확인을 통과해야만 지운다.
 *   - 아이디 + 비밀번호 계정: 요청 본문의 현재 `password` 가 저장된 해시와 맞아야 한다.
 *   - 구글 전용 계정(`password_hash` 없음): 요청 본문의 `confirm` 이 '삭제' 또는 '@아이디' 여야 한다.
 * 통과하면 이 사용자의 sessions 행 전부와 users 행을 지우고, 세션 쿠키를 즉시 만료시킨다.
 * 메일함(mails 의 보낸·받은 메일)과 공지 읽음(notice_reads)도 함께 정리한다.
 */
import {
  ok,
  fail,
  readJson,
  isSecureRequest,
  verifyPassword,
  currentSession,
  clearSessionCookie,
  clientIp,
  hitThrottle,
} from '../../_lib/auth.js';

/** 확인 문구 없이 지워지지 않도록, 아이디 대신 쓸 수 있는 말. */
const CONFIRM_WORD = '삭제';

export async function onRequest({ request, env }) {
  if (request.method.toUpperCase() !== 'POST') {
    return fail(405, 'method_not_allowed', 'POST 요청으로만 계정을 지울 수 있어요.', { allow: 'POST' });
  }
  if (!env.DB) return fail(503, 'not_configured', '계정 서버가 아직 준비되지 않았어요.');

  const session = await currentSession(env, request);
  if (!session) {
    return fail(401, 'not_signed_in', '로그인한 상태에서만 계정을 지울 수 있어요.', {
      'set-cookie': clearSessionCookie(isSecureRequest(request)),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const body = parsed.body;

  const ip = clientIp(request);
  const limit = await hitThrottle(env, `delete:${ip}`, 10, 600);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '시도가 너무 많아요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  if (session.password_hash) {
    const password = String(body.password ?? '');
    if (!password) return fail(400, 'password_required', '현재 비밀번호를 입력해 주세요.');
    const matched = await verifyPassword(password, session.password_hash);
    if (!matched) return fail(401, 'password_mismatch', '비밀번호가 맞지 않아요. 다시 확인해 주세요.');
  } else {
    const phrase = String(body.confirm ?? '').trim();
    if (!phrase) return fail(400, 'confirm_required', '확인 문구를 입력해 주세요.');
    const expected = [`@${session.username}`, session.username, CONFIRM_WORD];
    if (!expected.includes(phrase)) {
      return fail(400, 'confirm_mismatch', `확인 문구가 맞지 않아요. @${session.username} 또는 ${CONFIRM_WORD} 를 그대로 입력해 주세요.`);
    }
  }

  // 다른 기기의 세션까지 함께 지운다. users 행을 지우기 전에 세션부터 정리한다.
  await env.DB.prepare('DELETE FROM sessions WHERE user_id = ?').bind(session.id).run();
  // 메일함: 보낸·받은 메일과 공지 읽음 기록도 함께 지운다.
  // (사라진 계정의 쪽지가 상대 메일함에 남아 있지 않도록 양쪽을 모두 정리한다.)
  await env.DB.prepare('DELETE FROM mails WHERE sender_id = ? OR recipient_id = ?')
    .bind(session.id, session.id).run();
  await env.DB.prepare('DELETE FROM notice_reads WHERE user_id = ?').bind(session.id).run();
  // 친구: 이 사람이 낀 친구·요청 행을 모두 지운다(상대 친구 목록에 유령이 남지 않게).
  await env.DB.prepare('DELETE FROM friendships WHERE requester_id = ? OR addressee_id = ?')
    .bind(session.id, session.id).run();
  // 실험실: 내 방과 내게 온·내가 보낸 초대를 지운다. 다른 방의 내 자리도 뺀다
  // (방장 화면에 사라진 사람의 자리가 남지 않게).
  await env.DB.prepare('DELETE FROM lab_invites WHERE from_id = ? OR to_id = ?')
    .bind(session.id, session.id).run();
  await env.DB.prepare('DELETE FROM lab_rooms WHERE host_id = ?').bind(session.id).run();
  try {
    const seated = await env.DB.prepare(
      "SELECT code, version, seats_json FROM lab_rooms WHERE seats_json LIKE ? LIMIT 20",
    ).bind(`%${session.id}%`).all();
    for (const row of seated?.results || []) {
      let seats = [];
      try { seats = JSON.parse(row.seats_json || '[]'); } catch { seats = []; }
      const index = seats.findIndex((seat) => seat && seat.kind !== 'bot' && seat.userId === session.id);
      if (index < 0) continue;
      if (seats.length > 2) seats.splice(index, 1);
      else seats[index] = { kind: 'bot', userId: '', name: '봇 Lv.2 루키 봇', avatarAt: 0, level: 2, status: 'joined' };
      await env.DB.prepare(
        'UPDATE lab_rooms SET seats_json = ?, version = version + 1, updated_at = ? WHERE code = ? AND version = ?',
      ).bind(JSON.stringify(seats), Date.now(), row.code, Number(row.version)).run();
    }
  } catch {
    /* 자리 정리는 실패해도 탈퇴를 막지 않는다 */
  }
  await env.DB.prepare('DELETE FROM users WHERE id = ?').bind(session.id).run();

  return ok(
    { deleted: true },
    {
      'set-cookie': clearSessionCookie(isSecureRequest(request)),
      'cache-control': 'no-store',
    },
  );
}
