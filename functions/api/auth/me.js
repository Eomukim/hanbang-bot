/**
 * GET /api/auth/me
 * 지금 요청의 세션 쿠키로 로그인한 사용자를 돌려준다. 비로그인이면 user:null.
 */
import { ok, currentSession, publicUser } from '../../_lib/auth.js';

export async function onRequestGet({ request, env }) {
  if (!env.DB) return ok({ user: null });
  const row = await currentSession(env, request);
  return ok({ user: publicUser(row) });
}
