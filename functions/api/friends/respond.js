/**
 * POST /api/friends/respond
 * 받은 친구 요청을 수락·거절하거나, 내가 보낸 요청을 취소한다. 로그인 필수.
 *
 * body: { userId: 'u_...' 또는 username: '@아이디', action: 'accept' | 'decline' | 'cancel' }
 *
 * - accept  : 나에게 온 pending 요청만 accepted 로 바꾼다.
 * - decline : 나에게 온 pending 요청 행을 지운다(상대는 다시 요청할 수 있다).
 * - cancel  : 내가 보낸 pending 요청 행만 지운다.
 * 다른 사람의 요청은 있는지조차 알려 주지 않고 404 로 답한다(권한 확인은 WHERE 절에서 한다).
 */
import {
  ok,
  fail,
  readJson,
  currentSession,
  hitThrottle,
} from '../../_lib/auth.js';
import { pairKey, friendCounts, parseUserId } from '../../_lib/social.js';

const ACTIONS = new Set(['accept', 'decline', 'cancel']);
const USERNAME_RE = /^[가-힣a-zA-Z0-9_]{2,12}$/u;

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '친구 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 친구 요청을 처리할 수 있어요.');

  const limit = await hitThrottle(env, `friend:respond:${session.id}`, 120, 60);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const body = parsed.body;

  const action = String(body.action ?? '');
  if (!ACTIONS.has(action)) return fail(400, 'action_invalid', '무엇을 할지 알 수 없어요.');

  let otherId = parseUserId(body.userId);
  if (!otherId) {
    const username = String(body.username ?? '').trim().replace(/^@+/, '').trim();
    if (!USERNAME_RE.test(username)) return fail(400, 'user_required', '누구의 요청인지 알 수 없어요.');
    const target = await env.DB.prepare('SELECT id FROM users WHERE username = ?').bind(username).first();
    if (!target) return fail(404, 'request_not_found', '그 친구 요청을 찾지 못했어요.');
    otherId = target.id;
  }
  if (otherId === session.id) return fail(400, 'self_request', '자기 자신의 요청은 처리할 수 없어요.');

  const pair = pairKey(session.id, otherId);
  const now = Date.now();
  let changes = 0;

  if (action === 'accept') {
    const result = await env.DB.prepare(
      `UPDATE friendships SET status = 'accepted', updated_at = ?
        WHERE pair_key = ? AND status = 'pending' AND addressee_id = ?`,
    ).bind(now, pair, session.id).run();
    changes = Number(result?.meta?.changes || 0);
  } else if (action === 'decline') {
    const result = await env.DB.prepare(
      `DELETE FROM friendships
        WHERE pair_key = ? AND status = 'pending' AND addressee_id = ?`,
    ).bind(pair, session.id).run();
    changes = Number(result?.meta?.changes || 0);
  } else {
    const result = await env.DB.prepare(
      `DELETE FROM friendships
        WHERE pair_key = ? AND status = 'pending' AND requester_id = ?`,
    ).bind(pair, session.id).run();
    changes = Number(result?.meta?.changes || 0);
  }

  if (!changes) return fail(404, 'request_not_found', '이미 처리됐거나 찾을 수 없는 요청이에요.');

  return ok({
    action,
    done: true,
    counts: await friendCounts(env, session.id),
  });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'POST' });
}
