/**
 * POST /api/auth/register
 * 아이디 + 비밀번호 가입. 이메일은 받지 않는다.
 * Turnstile 서버 검증을 통과해야만 계정을 만든다.
 */
import {
  ok,
  fail,
  readJson,
  isSecureRequest,
  hashPassword,
  startSession,
  sessionCookie,
  verifyTurnstile,
  clientIp,
  hitThrottle,
  validateUsername,
  validatePassword,
  newUserId,
} from '../../_lib/auth.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '계정 서버가 아직 준비되지 않았어요.');

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const body = parsed.body;

  const ip = clientIp(request);
  const limit = await hitThrottle(env, `register:${ip}`, 10, 600);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '가입 시도가 너무 많아요. 잠시 후 다시 해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  const nameCheck = validateUsername(body.username);
  if (!nameCheck.ok) return fail(400, nameCheck.error, nameCheck.message);
  const passwordCheck = validatePassword(body.password);
  if (!passwordCheck.ok) return fail(400, passwordCheck.error, passwordCheck.message);
  const { username } = nameCheck;
  const { password } = passwordCheck;

  const turnstile = await verifyTurnstile(env, body.turnstileToken, ip);
  if (!turnstile.ok) {
    return fail(400, 'turnstile_failed', '봇 확인에 실패했어요. 아래 확인을 마치고 다시 시도해 주세요.');
  }

  const taken = await env.DB.prepare('SELECT 1 AS hit FROM users WHERE username = ?').bind(username).first();
  if (taken) return fail(409, 'username_taken', '이미 쓰고 있는 아이디예요.');

  const now = new Date().toISOString();
  const id = newUserId();
  const passwordHash = await hashPassword(password);
  try {
    await env.DB.prepare(
      `INSERT INTO users (id, username, password_hash, google_sub, display_name, stats_json, created_at, updated_at)
       VALUES (?, ?, ?, NULL, ?, '{}', ?, ?)`,
    ).bind(id, username, passwordHash, username, now, now).run();
  } catch (error) {
    if (String(error?.message || error).includes('UNIQUE')) {
      return fail(409, 'username_taken', '이미 쓰고 있는 아이디예요.');
    }
    throw error;
  }

  const token = await startSession(env, id);
  return ok(
    { user: { id, username, displayName: username, provider: 'password', createdAt: now } },
    { 'set-cookie': sessionCookie(token, { secure: isSecureRequest(request) }) },
  );
}
