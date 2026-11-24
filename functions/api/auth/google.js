/**
 * POST /api/auth/google
 * 구글 로그인(ID 토큰)으로 로그인하거나 처음이면 자동으로 계정을 만든다.
 * 아이디/비밀번호 가입과 같은 users 표를 쓰고, 구글 계정은 google_sub 로 잇는다.
 */
import {
  ok,
  fail,
  readJsonBody,
  isSecureRequest,
  startSession,
  sessionCookie,
  verifyGoogleCredential,
  suggestUsername,
  uniqueUsername,
  clientIp,
  hitThrottle,
  newUserId,
} from '../../_lib/auth.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '계정 서버가 아직 준비되지 않았어요.');
  if (!env.GOOGLE_CLIENT_ID) return fail(503, 'google_disabled', '구글 로그인은 아직 준비 중이에요.');

  const body = await readJsonBody(request);
  if (!body) return fail(400, 'bad_request', '요청을 이해하지 못했어요.');

  const ip = clientIp(request);
  const limit = await hitThrottle(env, `google:${ip}`, 20, 600);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '로그인 시도가 너무 많아요. 잠시 후 다시 해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  const verified = await verifyGoogleCredential(env, body.credential);
  if (!verified.ok) return fail(401, 'google_failed', '구글 로그인을 확인하지 못했어요. 다시 시도해 주세요.');

  const displayName = (verified.name || '').trim().slice(0, 24);
  let user = await env.DB.prepare(
    'SELECT id, username, google_sub, display_name, created_at FROM users WHERE google_sub = ?',
  ).bind(verified.sub).first();

  if (!user) {
    const now = new Date().toISOString();
    const id = newUserId();
    const username = await uniqueUsername(env, suggestUsername(verified.name, verified.email));
    const name = displayName || username;
    await env.DB.prepare(
      `INSERT INTO users (id, username, password_hash, google_sub, display_name, stats_json, created_at, updated_at)
       VALUES (?, ?, NULL, ?, ?, '{}', ?, ?)`,
    ).bind(id, username, verified.sub, name, now, now).run();
    user = { id, username, google_sub: verified.sub, display_name: name, created_at: now };
  } else if (displayName && displayName !== user.display_name) {
    await env.DB.prepare('UPDATE users SET display_name = ?, updated_at = ? WHERE id = ?')
      .bind(displayName, new Date().toISOString(), user.id).run();
    user.display_name = displayName;
  }

  const token = await startSession(env, user.id);
  return ok(
    {
      user: {
        id: user.id,
        username: user.username,
        displayName: user.display_name || user.username,
        provider: 'google',
        createdAt: user.created_at,
      },
    },
    { 'set-cookie': sessionCookie(token, { secure: isSecureRequest(request) }) },
  );
}
