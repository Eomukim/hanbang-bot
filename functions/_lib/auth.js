/**
 * 잇다 계정 공용 도우미.
 *
 * - 비밀번호: Web Crypto PBKDF2-SHA256(무작위 salt 16바이트, 아래 반복 횟수)
 * - 세션: 무작위 32바이트 토큰을 HttpOnly 쿠키로 주고, DB 에는 SHA-256 해시만 저장
 * - 봇 방지: Cloudflare Turnstile siteverify 서버 검증
 * - 요청 제한: D1 의 auth_throttle 표로 IP·경로별 창(window) 카운터
 *
 * `_lib` 처럼 밑줄로 시작하는 폴더는 Pages Functions 라우트가 되지 않는다.
 */

const enc = new TextEncoder();

export const SESSION_COOKIE = 'itda_session';
/** 세션 유지 기간(초). 쿠키 Max-Age 와 DB expires_at 이 같은 값을 쓴다. */
export const SESSION_TTL_SEC = 60 * 60 * 24 * 30;
/** PBKDF2 반복 횟수 — Workers 무료 플랜 CPU 한도(요청당 10ms) 안에서 쓰는 값.
 *  해시 문자열에 함께 저장하므로, 나중에 올리면 기존 계정은 저장된 값으로 계속 검증된다. */
const PBKDF2_ITERATIONS = 15000;
const PASSWORD_MIN = 6;
const PASSWORD_MAX = 72;
const USERNAME_RE = /^[가-힣a-zA-Z0-9_]{2,12}$/u;
const RESERVED_NAMES = new Set([
  'admin', 'administrator', 'root', 'system', 'itda', 'kkeutmal', 'guest',
  '관리자', '운영자', '잇다', '게스트', '봇', 'test', '테스트', 'help', 'support',
]);

/* ── 응답 ─────────────────────────────────────────────── */

const BASE_HEADERS = {
  'content-type': 'application/json; charset=utf-8',
  'cache-control': 'no-store, no-cache, must-revalidate',
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'same-origin',
};

export function json(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...BASE_HEADERS, ...headers },
  });
}

export function ok(data = {}, headers = {}) {
  return json({ ok: true, ...data }, 200, headers);
}

export function fail(status, error, message, headers = {}) {
  return json({ ok: false, error, message }, status, headers);
}

/** 요청 본문 상한(바이트). 공지 본문 5,000자(≈15KB)까지 넉넉히 담고 폭주는 막는다. */
export const JSON_MAX_BYTES = 32 * 1024;

function payloadTooLarge() {
  return {
    ok: false,
    status: 413,
    error: 'payload_too_large',
    message: '보낸 내용이 너무 커요. 조금 짧게 줄여 주세요.',
  };
}

function bodyUnreadable() {
  return { ok: false, status: 400, error: 'bad_request', message: '요청을 이해하지 못했어요.' };
}

/**
 * 본문을 max 바이트까지만 읽는다. 넘으면 null(그리고 스트림을 끊는다).
 * Content-Length 를 속이거나 아예 없이 보내는 폭주도 여기서 막힌다.
 */
async function readCappedText(request, max) {
  const body = request.body;
  if (!body || typeof body.getReader !== 'function') {
    const text = await request.text();
    return new TextEncoder().encode(text).byteLength > max ? null : text;
  }
  const reader = body.getReader();
  const chunks = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    total += value.byteLength;
    if (total > max) {
      try { await reader.cancel(); } catch { /* 이미 끊긴 스트림이면 그대로 */ }
      return null;
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

/**
 * JSON 본문을 크기 제한과 함께 읽는다.
 *   성공: { ok: true, body }
 *   실패: { ok: false, status, error, message }  → 그대로 fail() 에 넘기면 된다.
 * 32KB 를 넘는 본문은 읽기 전에(또는 읽는 도중에) 413 으로 끊어 Workers 메모리·CPU 소모를 막는다.
 */
export async function readJson(request) {
  const type = request.headers.get('content-type') || '';
  if (!type.includes('application/json')) return bodyUnreadable();

  const declared = Number(request.headers.get('content-length') || NaN);
  if (Number.isFinite(declared) && declared > JSON_MAX_BYTES) return payloadTooLarge();

  let text;
  try {
    text = await readCappedText(request, JSON_MAX_BYTES);
  } catch {
    return bodyUnreadable();
  }
  if (text == null) return payloadTooLarge();

  let body;
  try {
    body = JSON.parse(text);
  } catch {
    return bodyUnreadable();
  }
  if (!body || typeof body !== 'object' || Array.isArray(body)) return bodyUnreadable();
  return { ok: true, body };
}

export function isSecureRequest(request) {
  try {
    return new URL(request.url).protocol === 'https:';
  } catch {
    return true;
  }
}

/* ── 인코딩 ───────────────────────────────────────────── */

export function b64url(input) {
  const bytes = input instanceof Uint8Array ? input : new Uint8Array(input);
  let text = '';
  for (let i = 0; i < bytes.length; i += 1) text += String.fromCharCode(bytes[i]);
  return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function fromB64url(text) {
  const normalized = String(text).replace(/-/g, '+').replace(/_/g, '/');
  const pad = normalized.length % 4 === 0 ? '' : '='.repeat(4 - (normalized.length % 4));
  const binary = atob(normalized + pad);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export function randomToken(byteLength = 32) {
  return b64url(crypto.getRandomValues(new Uint8Array(byteLength)));
}

export function newUserId() {
  return `u_${crypto.randomUUID().replace(/-/g, '')}`;
}

export async function sha256(text) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', enc.encode(text)));
}

/* ── 비밀번호 ─────────────────────────────────────────── */

async function pbkdf2(password, salt, iterations) {
  const key = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveBits']);
  return crypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt, iterations },
    key,
    256,
  );
}

export async function hashPassword(password) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const bits = await pbkdf2(password, salt, PBKDF2_ITERATIONS);
  return `pbkdf2-sha256$${PBKDF2_ITERATIONS}$${b64url(salt)}$${b64url(bits)}`;
}

export async function verifyPassword(password, stored) {
  if (!stored) return false;
  const parts = String(stored).split('$');
  if (parts.length !== 4 || parts[0] !== 'pbkdf2-sha256') return false;
  const iterations = Number(parts[1]);
  if (!Number.isFinite(iterations) || iterations < 1000 || iterations > 1000000) return false;
  let salt;
  let expected;
  try {
    salt = fromB64url(parts[2]);
    expected = fromB64url(parts[3]);
  } catch {
    return false;
  }
  const bits = new Uint8Array(await pbkdf2(password, salt, iterations));
  if (bits.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < bits.length; i += 1) diff |= bits[i] ^ expected[i];
  return diff === 0;
}

/* ── 입력 검증 ────────────────────────────────────────── */

export function validateUsername(raw) {
  const username = String(raw ?? '').trim();
  if (!username) return { ok: false, error: 'username_required', message: '아이디를 입력해 주세요.' };
  if (!USERNAME_RE.test(username)) {
    return { ok: false, error: 'username_invalid', message: '아이디는 2~12자의 한글·영문·숫자·밑줄만 쓸 수 있어요.' };
  }
  if (RESERVED_NAMES.has(username.toLowerCase())) {
    return { ok: false, error: 'username_reserved', message: '쓸 수 없는 아이디예요. 다른 아이디를 정해 주세요.' };
  }
  return { ok: true, username };
}

export function validatePassword(raw) {
  const password = String(raw ?? '');
  if (!password) return { ok: false, error: 'password_required', message: '비밀번호를 입력해 주세요.' };
  if (password.length < PASSWORD_MIN) {
    return { ok: false, error: 'password_short', message: `비밀번호는 ${PASSWORD_MIN}자 이상으로 정해 주세요.` };
  }
  if (password.length > PASSWORD_MAX) {
    return { ok: false, error: 'password_long', message: `비밀번호는 ${PASSWORD_MAX}자까지 쓸 수 있어요.` };
  }
  return { ok: true, password };
}

/* 입력 오류는 다시 시도할 수 있는 값이므로 1ms 정도만 더 써서 계정 존재 여부를 살짝 흐린다. */
export async function burnTime() {
  await pbkdf2(randomToken(8), new Uint8Array(16), 1000);
}

/* ── 세션 ─────────────────────────────────────────────── */

export function readCookie(request, name) {
  const header = request.headers.get('cookie') || '';
  if (!header) return '';
  for (const part of header.split(';')) {
    const index = part.indexOf('=');
    if (index < 0) continue;
    if (part.slice(0, index).trim() !== name) continue;
    return part.slice(index + 1).trim();
  }
  return '';
}

export function sessionCookie(token, { maxAge = SESSION_TTL_SEC, secure = true } = {}) {
  const parts = [
    `${SESSION_COOKIE}=${token}`,
    'Path=/',
    `Max-Age=${maxAge}`,
    `Expires=${new Date(Date.now() + maxAge * 1000).toUTCString()}`,
    'HttpOnly',
    'SameSite=Lax',
  ];
  if (secure) parts.push('Secure');
  return parts.join('; ');
}

export function clearSessionCookie(secure = true) {
  return sessionCookie('', { maxAge: 0, secure });
}

/** 새 세션을 만들고 토큰(쿠키 값)을 돌려준다. 만료된 세션은 이때 함께 정리한다. */
export async function startSession(env, userId) {
  const token = randomToken(32);
  const tokenHash = b64url(await sha256(token));
  const now = Date.now();
  await env.DB.prepare('DELETE FROM sessions WHERE expires_at < ?').bind(now).run();
  await env.DB.prepare(
    'INSERT INTO sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)',
  ).bind(tokenHash, userId, now + SESSION_TTL_SEC * 1000, new Date(now).toISOString()).run();
  return token;
}

/** 요청 쿠키의 세션으로 지금 로그인한 사용자 행을 찾는다. 없거나 만료면 null. */
export async function currentSession(env, request) {
  if (!env.DB) return null;
  const token = readCookie(request, SESSION_COOKIE);
  if (!token) return null;
  const tokenHash = b64url(await sha256(token));
  const row = await env.DB.prepare(
    `SELECT s.token_hash, s.expires_at,
            u.id, u.username, u.password_hash, u.google_sub, u.display_name, u.created_at
       FROM sessions s JOIN users u ON u.id = s.user_id
      WHERE s.token_hash = ?`,
  ).bind(tokenHash).first();
  if (!row) return null;
  if (Number(row.expires_at) < Date.now()) {
    await env.DB.prepare('DELETE FROM sessions WHERE token_hash = ?').bind(tokenHash).run();
    return null;
  }
  return row;
}

export async function endSession(env, request) {
  if (!env.DB) return;
  const token = readCookie(request, SESSION_COOKIE);
  if (!token) return;
  const tokenHash = b64url(await sha256(token));
  await env.DB.prepare('DELETE FROM sessions WHERE token_hash = ?').bind(tokenHash).run();
}

/** 화면에 내려도 되는 사용자 정보만 골라낸다(해시·세션 제외). */
export function publicUser(row) {
  if (!row) return null;
  return {
    id: row.id,
    username: row.username,
    displayName: row.display_name || row.username,
    provider: row.google_sub ? 'google' : 'password',
    createdAt: row.created_at,
  };
}

/* ── 봇 방지 (Turnstile) ──────────────────────────────── */

export async function verifyTurnstile(env, token, ip) {
  const secret = env.TURNSTILE_SECRET_KEY;
  if (!secret) return { ok: false, reason: 'not_configured' };
  if (!token || typeof token !== 'string' || token.length > 2048) return { ok: false, reason: 'missing' };
  const form = new FormData();
  form.append('secret', secret);
  form.append('response', token);
  if (ip) form.append('remoteip', ip);
  let res;
  try {
    res = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', { method: 'POST', body: form });
  } catch {
    return { ok: false, reason: 'unreachable' };
  }
  if (!res.ok) return { ok: false, reason: `http_${res.status}` };
  const data = await res.json().catch(() => null);
  if (data && data.success) return { ok: true, hostname: data.hostname || '' };
  const codes = Array.isArray(data?.['error-codes']) ? data['error-codes'].join(',') : 'failed';
  return { ok: false, reason: codes };
}

/* ── 요청 제한 ────────────────────────────────────────── */

export function clientIp(request) {
  const direct = request.headers.get('cf-connecting-ip');
  if (direct) return direct;
  const forwarded = request.headers.get('x-forwarded-for') || '';
  return forwarded.split(',')[0].trim();
}

/** 창이 끝난 지 이만큼(초) 지난 기록은 청소한다(가장 긴 창 1시간보다 넉넉히). */
const THROTTLE_KEEP_SEC = 7200;
/** 요청 수 카운터 — 25번째마다 한 번씩 오래된 행을 지운다(확률 청소와 함께). */
let throttleHits = 0;

/**
 * auth_throttle 에 쌓인 만료 행을 정리한다. 창이 지난 기록은 어차피 다시 쓰이지 않으므로
 * 지워도 진행 중인 제한은 그대로다. 정리 실패가 요청을 막지는 않는다.
 */
export async function cleanThrottle(env, now = Math.floor(Date.now() / 1000)) {
  if (!env.DB) return 0;
  try {
    const result = await env.DB.prepare('DELETE FROM auth_throttle WHERE window_start < ?')
      .bind(now - THROTTLE_KEEP_SEC).run();
    return Number(result?.meta?.changes || 0);
  } catch {
    return 0;
  }
}

/** 창(window) 안에서 허용 횟수를 넘으면 allowed:false. 넘긴 기록도 세어 둔다. */
export async function hitThrottle(env, key, limit, windowSec) {
  if (!env.DB) return { allowed: true };
  const now = Math.floor(Date.now() / 1000);
  // 오래된 행이 무한히 쌓이지 않게 이따금 청소한다(25번째마다 · 그리고 2% 확률).
  throttleHits += 1;
  if (throttleHits % 25 === 0 || Math.random() < 0.02) await cleanThrottle(env, now);
  const row = await env.DB.prepare('SELECT count, window_start FROM auth_throttle WHERE key = ?').bind(key).first();
  if (!row || now - Number(row.window_start) >= windowSec) {
    await env.DB.prepare(
      `INSERT INTO auth_throttle (key, count, window_start) VALUES (?, 1, ?)
       ON CONFLICT(key) DO UPDATE SET count = 1, window_start = excluded.window_start`,
    ).bind(key, now).run();
    return { allowed: true };
  }
  if (Number(row.count) >= limit) {
    return { allowed: false, retryAfter: Math.max(1, windowSec - (now - Number(row.window_start))) };
  }
  await env.DB.prepare('UPDATE auth_throttle SET count = count + 1 WHERE key = ?').bind(key).run();
  return { allowed: true };
}

/**
 * 조회(GET) API 폭주 방지. 화면은 요약을 60초에 한 번, 목록을 탭을 열 때만 부르므로
 * 정상 사용자는 분당 몇 번 수준이다. 그보다 훨씬 잦은 반복 조회만 429 로 막는다.
 * 통과하면 null, 막아야 하면 { retryAfter } 를 돌려준다.
 */
export async function checkReadRate(env, request, name, limit = 150, windowSec = 60) {
  const ip = clientIp(request) || 'unknown';
  const result = await hitThrottle(env, `read:${name}:${ip}`, limit, windowSec);
  return result.allowed ? null : { retryAfter: result.retryAfter || windowSec };
}

/* ── 구글 로그인 ──────────────────────────────────────── */

/**
 * 구글 로그인(ID 토큰)을 서버에서 확인한다.
 * tokeninfo 는 서명·만료·대상(aud)까지 구글이 직접 검사해 주는 엔드포인트다.
 */
export async function verifyGoogleCredential(env, credential) {
  const clientId = env.GOOGLE_CLIENT_ID;
  if (!clientId) return { ok: false, reason: 'not_configured' };
  if (!credential || typeof credential !== 'string' || credential.length > 4096) return { ok: false, reason: 'missing' };
  let res;
  try {
    res = await fetch(`https://oauth2.googleapis.com/tokeninfo?id_token=${encodeURIComponent(credential)}`, {
      headers: { accept: 'application/json' },
    });
  } catch {
    return { ok: false, reason: 'unreachable' };
  }
  if (!res.ok) return { ok: false, reason: 'invalid_token' };
  const data = await res.json().catch(() => null);
  if (!data || !data.sub) return { ok: false, reason: 'invalid_token' };
  if (data.aud !== clientId) return { ok: false, reason: 'audience_mismatch' };
  if (data.iss !== 'accounts.google.com' && data.iss !== 'https://accounts.google.com') {
    return { ok: false, reason: 'issuer_mismatch' };
  }
  if (!data.exp || Number(data.exp) * 1000 < Date.now()) return { ok: false, reason: 'expired' };
  return {
    ok: true,
    sub: String(data.sub),
    email: String(data.email || ''),
    name: String(data.name || ''),
    picture: String(data.picture || ''),
  };
}

/** 구글 이름·메일에서 쓸 만한 아이디 씨앗을 만든다(한글·영문·숫자만, 2~10자). */
export function suggestUsername(name, email) {
  const clean = (text) => String(text || '').replace(/[^가-힣a-zA-Z0-9]/g, '');
  let seed = clean(name);
  if (seed.length < 2) seed = clean(String(email || '').split('@')[0]);
  if (seed.length < 2) seed = '잇다';
  return seed.slice(0, 10);
}

/** 이미 있는 아이디면 뒤에 숫자를 붙여 빈 이름을 찾는다. */
export async function uniqueUsername(env, seed) {
  const base = seed.slice(0, 10);
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const candidate = attempt === 0 ? base : `${base}${attempt + 1}`.slice(0, 12);
    if (!USERNAME_RE.test(candidate) || RESERVED_NAMES.has(candidate.toLowerCase())) continue;
    const taken = await env.DB.prepare('SELECT 1 AS hit FROM users WHERE username = ?').bind(candidate).first();
    if (!taken) return candidate;
  }
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const candidate = `${base.slice(0, 6)}${Math.floor(1000 + Math.random() * 9000)}`.slice(0, 12);
    if (!USERNAME_RE.test(candidate)) continue;
    const taken = await env.DB.prepare('SELECT 1 AS hit FROM users WHERE username = ?').bind(candidate).first();
    if (!taken) return candidate;
  }
  throw new Error('username_exhausted');
}
