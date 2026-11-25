/**
 * GET /api/account/avatar?u=<사용자 id>&v=<avatar_updated_at>
 * 프로필 사진을 이미지로 내려 준다. 로그인한 사용자만 볼 수 있다.
 *
 * - 사진은 `users.avatar_data` 의 Data URL 이고, 저장할 때 이미 PNG·JPEG·WebP 인지 확인했다.
 *   여기서도 한 번 더 확인하고 `content-type: image/*` + `nosniff` 로만 보낸다.
 * - 주소의 `v` 는 사진을 바꾼 시각(avatar_updated_at)이다. 사진을 바꾸면 주소가 달라지므로
 *   오래 캐시해도(7일, immutable) 예전 사진이 남지 않는다.
 * - 사진이 없으면 404(화면은 닉네임 첫 글자 아바타를 그린다).
 */
import { fail, currentSession, checkReadRate } from '../../_lib/auth.js';
import { avatarResponse, parseUserId } from '../../_lib/social.js';

export async function onRequestGet({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '계정 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 프로필 사진을 볼 수 있어요.');

  const limited = await checkReadRate(env, request, 'avatar', 900, 60);
  if (limited) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limited.retryAfter),
    });
  }

  let userId = '';
  try {
    userId = parseUserId(new URL(request.url).searchParams.get('u'));
  } catch {
    userId = '';
  }
  if (!userId) return fail(400, 'user_required', '누구의 사진인지 알 수 없어요.');

  const row = await env.DB.prepare('SELECT avatar_data FROM users WHERE id = ?').bind(userId).first();
  const response = row ? avatarResponse(row.avatar_data || '') : null;
  if (!response) {
    return fail(404, 'avatar_not_found', '프로필 사진이 없어요.', { 'cache-control': 'private, max-age=60' });
  }
  return response;
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'GET' });
}
