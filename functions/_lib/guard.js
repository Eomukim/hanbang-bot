/**
 * 잇다 요청 가드 — 출처(교차 사이트) 검사 · 보안 응답 헤더 · 본문 크기 제한.
 *
 * - CSRF: 상태를 바꾸는 요청(POST·PUT·PATCH·DELETE)에 `Origin`(없으면 `Referer`) 헤더가
 *   붙어 있으면, 이 배포의 주소와 로컬 개발 주소만 통과시킨다. 다른 사이트에서 온 요청은 403.
 *   헤더가 아예 없는 요청(서버·도구·앱)은 세션 쿠키가 SameSite=Lax 라서 그대로 둔다.
 * - 공격자가 만든 페이지는 브라우저가 늘 Origin 을 붙이므로, 이 검사만으로 교차 사이트
 *   요청 위조(CSRF)가 막힌다. 그림·링크·폼 어느 쪽으로 보내도 마찬가지다.
 * - 헤더: 모든 응답(정적 파일 포함)에 nosniff · referrer-policy · frame-options 를 붙인다.
 */

/** 요청 본문 상한(바이트). 화면 입력 상한(공지 본문 5,000자 ≈ 15KB)보다 넉넉하고 폭주는 막는다. */
export const JSON_MAX_BYTES = 32 * 1024;

const STATE_CHANGING = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

const SECURITY_HEADERS = {
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'same-origin',
  'x-frame-options': 'DENY',
};

export function securityHeaders() {
  return { ...SECURITY_HEADERS };
}

/** 응답 헤더에 보안 헤더를 더한다(이미 있으면 그대로 둔다). */
export function withSecurityHeaders(response) {
  if (!response || !response.headers) return response;
  let missing = false;
  for (const key of Object.keys(SECURITY_HEADERS)) {
    if (!response.headers.has(key)) { missing = true; break; }
  }
  if (!missing) return response;
  const wrapped = new Response(response.body, response);
  for (const [key, value] of Object.entries(SECURITY_HEADERS)) {
    if (!wrapped.headers.has(key)) wrapped.headers.set(key, value);
  }
  return wrapped;
}

function forbiddenOrigin() {
  return new Response(
    JSON.stringify({
      ok: false,
      error: 'forbidden_origin',
      message: '다른 사이트에서 보낸 요청이라 막았어요.',
    }),
    {
      status: 403,
      headers: {
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'no-store',
        ...SECURITY_HEADERS,
      },
    },
  );
}

export function payloadTooLarge() {
  return new Response(
    JSON.stringify({
      ok: false,
      error: 'payload_too_large',
      message: '보낸 내용이 너무 커요. 조금 짧게 줄여 주세요.',
    }),
    {
      status: 413,
      headers: {
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'no-store',
        ...SECURITY_HEADERS,
      },
    },
  );
}

/**
 * `Content-Length` 가 상한을 넘는 요청을 라우팅 전에 413 으로 끊는다.
 * (Content-Length 를 속이거나 없이 보내는 청크는 각 API 의 readJson() 이 스트림을 읽다가 끊는다.)
 */
export function guardPayload(request) {
  const declared = Number(request.headers.get('content-length') || NaN);
  if (Number.isFinite(declared) && declared > JSON_MAX_BYTES) return payloadTooLarge();
  return null;
}

/** 환경변수 `ALLOWED_ORIGINS`(쉼표 구분)에 적어 둔 추가 주소. */
function extraOrigins(env) {
  return String(env?.ALLOWED_ORIGINS || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean)
    .map((value) => {
      try { return new URL(value).origin.toLowerCase(); } catch { return ''; }
    })
    .filter(Boolean);
}

function isLocal(parsed) {
  return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && LOCAL_HOSTS.has(parsed.hostname);
}

/**
 * 요청 출처가 허용 범위인가.
 *   - 이 요청이 도착한 주소(배포 주소·미리보기 주소)
 *   - 같은 호스트(프로토콜만 다른 경우: http↔https 전환)
 *   - 로컬 개발(http://127.0.0.1:*, http://localhost:*)
 *   - 환경변수 ALLOWED_ORIGINS
 */
export function isAllowedSource(request, env, source) {
  let parsed;
  try { parsed = new URL(source); } catch { return false; }
  if (!parsed.hostname) return false;
  let target;
  try { target = new URL(request.url); } catch { return false; }
  if (parsed.origin.toLowerCase() === 'null') return false;
  if (parsed.origin.toLowerCase() === target.origin.toLowerCase()) return true;
  if (parsed.host.toLowerCase() === target.host.toLowerCase()) return true;
  if (isLocal(parsed)) return true;
  return extraOrigins(env).includes(parsed.origin.toLowerCase());
}

/**
 * 상태를 바꾸는 요청의 출처를 검사한다.
 * 통과하면 null, 막아야 하면 403 응답을 돌려준다.
 */
export function guardRequest(request, env) {
  const method = String(request.method || 'GET').toUpperCase();
  if (!STATE_CHANGING.has(method)) return null;

  const origin = request.headers.get('origin');
  const referer = request.headers.get('referer');
  const source = origin != null && origin.trim() ? origin.trim() : (referer || '').trim();
  if (!source) return null; // 헤더 없는 요청은 SameSite=Lax 쿠키로 지켜진다
  if (origin && origin.trim() === 'null') return forbiddenOrigin();
  if (isAllowedSource(request, env, source)) return null;
  return forbiddenOrigin();
}
