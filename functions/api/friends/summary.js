/**
 * GET /api/friends/summary
 * 상단 계정 버튼·친구 탭의 빨간 점과 숫자에 쓰는 가벼운 요약. 로그인 필수.
 *
 *   { incoming, outgoing, friends }
 *
 * 화면은 로그인 중 60초에 한 번만 부른다(받은 요청이 생기면 그때 빨간 점이 뜬다).
 */
import { ok, fail, currentSession, checkReadRate } from '../../_lib/auth.js';
import { friendCounts } from '../../_lib/social.js';

export async function onRequestGet({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '친구 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 친구 요청을 받을 수 있어요.');

  const limited = await checkReadRate(env, request, 'friends-summary', 180, 60);
  if (limited) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 열어 주세요.', {
      'retry-after': String(limited.retryAfter),
    });
  }

  return ok(await friendCounts(env, session.id));
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'GET' });
}
