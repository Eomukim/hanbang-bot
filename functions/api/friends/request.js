/**
 * POST /api/friends/request
 * 아이디(또는 사용자 id)로 친구 요청을 보낸다. 로그인 필수.
 *
 * body: { username: '@아이디' } 또는 { userId: 'u_...' }
 *
 * - 자기 자신에게는 보낼 수 없다.
 * - 이미 친구면 409 `already_friends`, 내가 이미 보낸 요청이 있으면 409 `already_requested`.
 * - 상대가 먼저 나에게 요청을 보내 둔 상태라면 새 행을 만들지 않고 **바로 친구가 된다**
 *   (accepted 로 바꾸고 `accepted: true` 로 답한다) — 받은 요청 화면과 결과가 어긋나지 않게.
 * - 한 사람이 10분에 30번까지만 요청할 수 있다(무작위 아이디로 요청 폭탄을 막는다).
 */
import {
  ok,
  fail,
  readJson,
  currentSession,
  hitThrottle,
  clientIp,
} from '../../_lib/auth.js';
import {
  pairKey,
  socialUser,
  friendCounts,
  parseUserId,
} from '../../_lib/social.js';

/** 아이디 형식(가입 규칙과 같은 2~12자 한글·영문·숫자·밑줄). */
const USERNAME_RE = /^[가-힣a-zA-Z0-9_]{2,12}$/u;

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '친구 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 친구 요청을 보낼 수 있어요.');

  const ip = clientIp(request) || 'unknown';
  const perIp = await hitThrottle(env, `friend:req:ip:${ip}`, 60, 600);
  if (!perIp.allowed) {
    return fail(429, 'rate_limited', '친구 요청이 너무 잦아요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(perIp.retryAfter),
    });
  }
  const perUser = await hitThrottle(env, `friend:req:u:${session.id}`, 30, 600);
  if (!perUser.allowed) {
    return fail(429, 'rate_limited', '친구 요청을 너무 많이 보냈어요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(perUser.retryAfter),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const body = parsed.body;

  const userId = parseUserId(body.userId);
  let target = null;
  if (userId) {
    target = await env.DB.prepare(
      'SELECT id, username, nickname, display_name, avatar_updated_at FROM users WHERE id = ?',
    ).bind(userId).first();
  } else {
    const username = String(body.username ?? '').trim().replace(/^@+/, '').trim();
    if (!USERNAME_RE.test(username)) {
      return fail(400, 'username_invalid', '친구로 찾을 아이디는 2~12자의 한글·영문·숫자·밑줄이에요.');
    }
    target = await env.DB.prepare(
      'SELECT id, username, nickname, display_name, avatar_updated_at FROM users WHERE username = ?',
    ).bind(username).first();
  }
  if (!target) return fail(404, 'user_not_found', '그 아이디를 찾지 못했어요.');
  if (target.id === session.id) return fail(400, 'self_request', '자기 자신에게는 친구 요청을 보낼 수 없어요.');

  const pair = pairKey(session.id, target.id);
  const existing = await env.DB.prepare(
    'SELECT requester_id, addressee_id, status FROM friendships WHERE pair_key = ?',
  ).bind(pair).first();
  const now = Date.now();

  if (existing) {
    if (existing.status === 'accepted') {
      return fail(409, 'already_friends', '이미 친구예요.', { 'x-friend-state': 'friend' });
    }
    if (existing.requester_id === session.id) {
      return fail(409, 'already_requested', '이미 친구 요청을 보냈어요. 상대가 수락하면 친구가 돼요.');
    }
    // 상대가 먼저 보낸 요청이 있다 → 새로 만들지 않고 바로 친구가 된다.
    await env.DB.prepare(
      `UPDATE friendships SET status = 'accepted', updated_at = ?
        WHERE pair_key = ? AND status = 'pending' AND addressee_id = ?`,
    ).bind(now, pair, session.id).run();
    return ok({
      accepted: true,
      friend: socialUser(target),
      counts: await friendCounts(env, session.id),
    });
  }

  await env.DB.prepare(
    `INSERT INTO friendships (pair_key, requester_id, addressee_id, status, created_at, updated_at)
     VALUES (?, ?, ?, 'pending', ?, ?)`,
  ).bind(pair, session.id, target.id, now, now).run();

  return ok({
    requested: true,
    friend: socialUser(target),
    counts: await friendCounts(env, session.id),
  });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'POST' });
}
