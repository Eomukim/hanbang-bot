/**
 * POST /api/auth/login
 * 아이디 + 비밀번호 로그인. Turnstile 검증을 함께 통과해야 세션을 준다.
 */
import {
  ok,
  fail,
  readJsonBody,
  isSecureRequest,
  verifyPassword,
  burnTime,
  startSession,
  sessionCookie,
  verifyTurnstile,
  clientIp,
  hitThrottle,
  validateUsername,
} from '../../_lib/auth.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '계정 서버가 아직 준비되지 않았어요.');

  const body = await readJsonBody(request);
  if (!body) return fail(400, 'bad_request', '요청을 이해하지 못했어요.');

  const ip = clientIp(request);
  const limit = await hitThrottle(env, `login:${ip}`, 20, 600);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '로그인 시도가 너무 많아요. 잠시 후 다시 해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  const nameCheck = validateUsername(body.username);
  if (!nameCheck.ok) return fail(401, 'invalid_credentials', '아이디 또는 비밀번호가 맞지 않아요.');
  const password = String(body.password ?? '');

  const turnstile = await verifyTurnstile(env, body.turnstileToken, ip);
  if (!turnstile.ok) {
    return fail(400, 'turnstile_failed', '봇 확인에 실패했어요. 아래 확인을 마치고 다시 시도해 주세요.');
  }

  const user = await env.DB.prepare(
    'SELECT id, username, password_hash, google_sub, display_name, created_at FROM users WHERE username = ?',
  ).bind(nameCheck.username).first();

  if (!user) {
    await burnTime();
    return fail(401, 'invalid_credentials', '아이디 또는 비밀번호가 맞지 않아요.');
  }
  if (!user.password_hash) {
    return fail(409, 'use_google', '구글 로그인으로 만든 계정이에요. 아래 구글 로그인을 써 주세요.');
  }
  const matched = await verifyPassword(password, user.password_hash);
  if (!matched) return fail(401, 'invalid_credentials', '아이디 또는 비밀번호가 맞지 않아요.');

  const token = await startSession(env, user.id);
  return ok(
    {
      user: {
        id: user.id,
        username: user.username,
        displayName: user.display_name || user.username,
        provider: 'password',
        createdAt: user.created_at,
      },
    },
    { 'set-cookie': sessionCookie(token, { secure: isSecureRequest(request) }) },
  );
}
