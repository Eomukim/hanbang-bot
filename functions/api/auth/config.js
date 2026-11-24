/**
 * GET /api/auth/config
 * 화면이 알아야 하는 공개 설정만 내려준다(Turnstile 사이트 키, 구글 클라이언트 ID).
 * 비밀 키는 절대 내려보내지 않는다.
 */
import { ok } from '../../_lib/auth.js';

export async function onRequestGet({ env }) {
  return ok({
    turnstileSiteKey: env.TURNSTILE_SITE_KEY || '',
    turnstileEnabled: Boolean(env.TURNSTILE_SITE_KEY && env.TURNSTILE_SECRET_KEY),
    googleClientId: env.GOOGLE_CLIENT_ID || '',
    googleEnabled: Boolean(env.GOOGLE_CLIENT_ID),
  });
}
