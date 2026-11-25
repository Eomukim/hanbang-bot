/**
 * POST /api/account/ping — 접속 중(온라인) 표시용 하트비트.
 *
 * 로그인한 화면이 30초에 한 번 부른다. `users.last_seen_at` 은 30초에 한 번만 갱신해
 * D1 쓰기를 아낀다(쿨다운 안의 ping 은 행을 건드리지 않는다).
 * 친구 목록은 90초 안에 활동한 사람을 `접속 중`으로 보여 준다.
 */
import { ok, fail, currentSession } from '../../_lib/auth.js';

const COOLDOWN_MS = 30 * 1000;

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '계정 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 접속 상태를 알릴 수 있어요.');

  const now = Date.now();
  const result = await env.DB.prepare(
    'UPDATE users SET last_seen_at = ? WHERE id = ? AND (last_seen_at IS NULL OR last_seen_at < ?)',
  ).bind(now, session.id, now - COOLDOWN_MS).run();

  return ok({
    at: now,
    updated: Number(result?.meta?.changes || 0) > 0,
  }, { 'cache-control': 'no-store' });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'POST' });
}
