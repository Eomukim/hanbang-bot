/**
 * POST /api/friends/remove
 * 친구를 끊는다(친구 목록의 `친구 삭제`). 로그인 필수.
 *
 * body: { userId: 'u_...' 또는 username: '@아이디' }
 *
 * - accepted 인 두 사람 사이의 행만 지운다. 받은/보낸 요청은 respond(거절·취소)로 처리한다.
 * - 지운 뒤에는 서로 다시 요청할 수 있다.
 */
import {
  ok,
  fail,
  readJson,
  currentSession,
  hitThrottle,
} from '../../_lib/auth.js';
import { pairKey, friendCounts, parseUserId } from '../../_lib/social.js';

const USERNAME_RE = /^[가-힣a-zA-Z0-9_]{2,12}$/u;

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '친구 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 친구를 정리할 수 있어요.');

  const limit = await hitThrottle(env, `friend:remove:${session.id}`, 60, 60);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);

  let otherId = parseUserId(parsed.body.userId);
  if (!otherId) {
    const username = String(parsed.body.username ?? '').trim().replace(/^@+/, '').trim();
    if (!USERNAME_RE.test(username)) return fail(400, 'user_required', '누구인지 알 수 없어요.');
    const target = await env.DB.prepare('SELECT id FROM users WHERE username = ?').bind(username).first();
    if (!target) return fail(404, 'friend_not_found', '그 친구를 찾지 못했어요.');
    otherId = target.id;
  }
  if (otherId === session.id) return fail(400, 'self_request', '자기 자신은 친구 삭제할 수 없어요.');

  const pair = pairKey(session.id, otherId);
  const result = await env.DB.prepare(
    `DELETE FROM friendships
      WHERE pair_key = ? AND status = 'accepted'
        AND (requester_id = ? OR addressee_id = ?)`,
  ).bind(pair, session.id, session.id).run();

  if (!Number(result?.meta?.changes || 0)) {
    return fail(404, 'friend_not_found', '이미 친구가 아니에요.');
  }

  return ok({ removed: true, counts: await friendCounts(env, session.id) });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'POST' });
}
