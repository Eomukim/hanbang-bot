/**
 * POST /api/auth/logout
 * 지금 세션을 DB 에서 지우고 쿠키를 비운다(다른 기기의 세션은 그대로 둔다).
 */
import { ok, endSession, clearSessionCookie, isSecureRequest } from '../../_lib/auth.js';

export async function onRequestPost({ request, env }) {
  await endSession(env, request);
  return ok({}, { 'set-cookie': clearSessionCookie(isSecureRequest(request)) });
}
