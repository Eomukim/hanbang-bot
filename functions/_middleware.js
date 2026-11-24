/**
 * 잇다 전체 요청 미들웨어.
 *
 * 1) `/api/*` 의 상태 변경 요청(POST·DELETE …)은 출처(Origin/Referer)를 검사해
 *    다른 사이트에서 보낸 교차 요청을 403 으로 막는다(CSRF 방지).
 * 2) 모든 응답(정적 파일 포함)에 nosniff · referrer-policy · frame-options 를 붙인다.
 *
 * 정적 자산의 캐시 규칙은 `_headers` 가 그대로 담당한다.
 */
import { guardRequest, withSecurityHeaders } from './_lib/guard.js';

export async function onRequest(context) {
  const { request, env, next } = context;
  let pathname = '';
  try { pathname = new URL(request.url).pathname; } catch { pathname = ''; }

  if (pathname.startsWith('/api/')) {
    const blocked = guardRequest(request, env);
    if (blocked) return blocked;
  }

  const response = await next();
  return withSecurityHeaders(response);
}
