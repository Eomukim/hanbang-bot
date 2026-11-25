/**
 * GET /api/friends
 * 나와 얽힌 친구 관계를 한 번에 내려 준다. 로그인 필수.
 *
 *   { friends: [...], incoming: [...], outgoing: [...], counts: { friends, incoming, outgoing } }
 *
 * - 친구(accepted) · 받은 요청(내가 addressee 인 pending) · 보낸 요청(내가 requester 인 pending)
 * - 각 항목은 { id, username, nickname, displayName, avatarAt, relation, since } 이고
 *   사진은 `/api/account/avatar?u=<id>&v=<avatarAt>` 로 따로 받는다(목록 응답을 가볍게).
 * - 아이디·비밀번호 해시·세션은 절대 내려 보내지 않는다.
 */
import { ok, fail, currentSession, checkReadRate } from '../../_lib/auth.js';
import {
  loadFriendships,
  loadUsersByIds,
  relationUser,
  FRIEND_LIST_LIMIT,
} from '../../_lib/social.js';

export async function onRequestGet({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '친구 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 친구를 찾고 요청을 주고받을 수 있어요.');

  const limited = await checkReadRate(env, request, 'friends', 120, 60);
  if (limited) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 열어 주세요.', {
      'retry-after': String(limited.retryAfter),
    });
  }

  const { rows, byOther } = await loadFriendships(env, session.id);
  const users = await loadUsersByIds(env, [...byOther.keys()]);

  const friends = [];
  const incoming = [];
  const outgoing = [];
  for (const [otherId, relation] of byOther) {
    const item = relationUser(users.get(otherId), relation.status === 'accepted' ? 'friend' : relation.direction);
    if (!item) continue;
    item.since = relation.since;
    if (relation.status === 'accepted') friends.push(item);
    else if (relation.direction === 'incoming') incoming.push(item);
    else outgoing.push(item);
  }
  // 최근에 친구가 된/요청한 사람이 위로
  friends.sort((a, b) => b.since - a.since);
  incoming.sort((a, b) => b.since - a.since);
  outgoing.sort((a, b) => b.since - a.since);

  return ok({
    friends,
    incoming,
    outgoing,
    counts: { friends: friends.length, incoming: incoming.length, outgoing: outgoing.length },
    limit: FRIEND_LIST_LIMIT,
    truncated: rows.length >= FRIEND_LIST_LIMIT,
  });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'GET' });
}
