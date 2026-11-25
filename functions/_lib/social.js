/**
 * 잇다 프로필(닉네임 · 사진) · 친구 공용 도우미.
 *
 * - 아이디(`@username`)는 가입 때 정해지고 바뀌지 않는 고유 식별자다. 사람들이 보는 이름은
 *   `nickname`(1~16자)이고, 닉네임이 없으면 표시용 이름(`display_name`)·아이디를 쓴다.
 * - 프로필 사진은 R2·이미지 카드 없이 D1 의 `users.avatar_data` 에 Data URL 문자열로 넣는다
 *   (요청 본문 상한 32KB 안). 그래서 서버가 형식을 직접 확인한다 — PNG·JPEG·WebP 만 받고,
 *   매직바이트까지 맞아야 저장한다(SVG·HTML·스크립트가 섞인 Data URL 은 절대 통과시키지 않는다).
 *   화면은 사진을 늘 160×160 정사각으로 줄여 보내고, 내려 줄 때도 `image/*` + nosniff 로만 준다.
 * - 친구는 방향이 있는 한 행(`pending` → `accepted`)이다. `pair_key` 는 두 사람 id 를 정렬해
 *   이은 값이라, 서로가 동시에 요청해도 한 쌍에 한 행만 생긴다.
 */

/** 닉네임 길이 상한(코드 포인트 기준). 화면 입력 칸의 maxlength 와 같은 값. */
export const NICKNAME_MAX = 16;
/** Data URL 문자열 상한 — 요청 본문 32KB 안에서 안전하게 들어가는 값. */
export const AVATAR_STRING_MAX = 28 * 1024;
/** 디코딩한 이미지 바이트 상한(28KB 문자열 ≈ 21KB 바이트). */
export const AVATAR_BYTES_MAX = 20 * 1024;
/** 아이디 검색 최소 글자 수 — 이보다 짧으면 전체 목록이 덤프된다. */
export const SEARCH_MIN = 2;
/** 한 번에 내려 주는 검색 결과 수. */
export const SEARCH_LIMIT = 8;
/** 한 사람이 가질 수 있는 친구·요청 행 상한(목록 응답 크기 보호). */
export const FRIEND_LIST_LIMIT = 200;

/** 제어문자(C0·DEL·C1) — 줄바꿈·탭도 포함된다. */
const CONTROL_RE = /[\u0000-\u001F\u007F-\u009F]/;
/** 화면에서 보이지 않으면서 이름을 속일 수 있는 글자(제로폭·방향 제어·BOM). */
const INVISIBLE_RE = /[\u200B-\u200F\u2028-\u202E\u2060-\u2064\uFEFF]/;
const AVATAR_RE = /^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$/;

export function validateNickname(raw) {
  if (raw == null) return { ok: false, error: 'nickname_required', message: '닉네임을 입력해 주세요.' };
  if (typeof raw !== 'string') {
    return { ok: false, error: 'nickname_invalid', message: '닉네임은 글자로 입력해 주세요.' };
  }
  if (CONTROL_RE.test(raw) || INVISIBLE_RE.test(raw)) {
    return { ok: false, error: 'nickname_invalid', message: '닉네임에 쓸 수 없는 글자가 있어요.' };
  }
  // 자모가 풀린 한글(NFD)도 같은 이름으로 보이게 합치고, 가운데 공백은 하나로 줄인다.
  const nickname = String(raw).normalize('NFC').replace(/\s+/g, ' ').trim();
  const length = [...nickname].length;
  if (!length) return { ok: false, error: 'nickname_required', message: '닉네임을 입력해 주세요.' };
  if (length > NICKNAME_MAX) {
    return { ok: false, error: 'nickname_long', message: `닉네임은 ${NICKNAME_MAX}자까지 쓸 수 있어요.` };
  }
  return { ok: true, nickname };
}

/** base64 문자열 → 바이트. 형식이 깨졌으면 null. */
export function decodeBase64(text) {
  try {
    const binary = atob(String(text));
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  } catch {
    return null;
  }
}

/** 선언한 형식과 실제 파일 머리(매직바이트)가 맞는지. */
function magicMatches(mime, bytes) {
  if (bytes.length < 12) return false;
  if (mime === 'png') {
    const sig = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
    return sig.every((byte, index) => bytes[index] === byte);
  }
  if (mime === 'jpeg') {
    return bytes[0] === 0xFF && bytes[1] === 0xD8 && bytes[2] === 0xFF;
  }
  if (mime === 'webp') {
    const riff = String.fromCharCode(...bytes.slice(0, 4));
    const webp = String.fromCharCode(...bytes.slice(8, 12));
    return riff === 'RIFF' && webp === 'WEBP';
  }
  return false;
}

/**
 * 프로필 사진 Data URL 검사.
 *   성공: { ok: true, mime, bytes, data }
 *   실패: { ok: false, error, message }
 * SVG(`image/svg+xml`)·GIF·BMP·HTML 등은 정규식 단계에서 거부한다.
 */
export function validateAvatar(raw) {
  if (typeof raw !== 'string') {
    return { ok: false, error: 'avatar_invalid', message: 'PNG·JPEG·WebP 사진만 쓸 수 있어요.' };
  }
  // 상한을 먼저 본다 — 큰 문자열은 정규식에 넣기 전에 끊는다.
  if (raw.length > AVATAR_STRING_MAX) {
    return { ok: false, error: 'avatar_too_large', message: '사진이 너무 커요. 더 작은 사진으로 다시 골라 주세요.' };
  }
  const match = AVATAR_RE.exec(raw);
  if (!match) {
    return { ok: false, error: 'avatar_invalid', message: 'PNG·JPEG·WebP 사진만 쓸 수 있어요.' };
  }
  const type = match[1];
  const bytes = decodeBase64(match[2]);
  if (!bytes || !bytes.length) {
    return { ok: false, error: 'avatar_invalid', message: '사진을 읽지 못했어요. 다시 골라 주세요.' };
  }
  if (bytes.length > AVATAR_BYTES_MAX) {
    return { ok: false, error: 'avatar_too_large', message: '사진이 너무 커요. 더 작은 사진으로 다시 골라 주세요.' };
  }
  if (!magicMatches(type, bytes)) {
    return { ok: false, error: 'avatar_invalid', message: 'PNG·JPEG·WebP 사진만 쓸 수 있어요.' };
  }
  return { ok: true, mime: `image/${type}`, bytes };
}

/** 저장된 Data URL 을 그대로 응답으로 바꾼다(형식이 깨졌으면 null). */
export function avatarResponse(data) {
  const checked = validateAvatar(data);
  if (!checked.ok) return null;
  return new Response(checked.bytes, {
    headers: {
      'content-type': checked.mime,
      'content-length': String(checked.bytes.length),
      // 주소의 ?v=(avatar_updated_at)가 바뀌면 새 주소라, 오래 캐시해도 사진이 굳지 않는다.
      'cache-control': 'private, max-age=604800, immutable',
      'x-content-type-options': 'nosniff',
    },
  });
}

/** 두 사용자 id 로 방향과 무관한 한 쌍의 키를 만든다. */
export function pairKey(a, b) {
  const [low, high] = [String(a), String(b)].sort();
  return `${low}|${high}`;
}

/** 대시보드·화면에 내려도 되는 사람 정보(비밀번호·세션·사진 원본은 뺀다). */
export function socialUser(row) {
  if (!row) return null;
  const nickname = row.nickname || '';
  return {
    id: row.id,
    username: row.username,
    nickname,
    displayName: nickname || row.display_name || row.username,
    avatarAt: Number(row.avatar_updated_at || 0),
  };
}

/** 친구 요약 숫자(incoming·outgoing·friends). 배지와 버튼에 쓴다. */
export async function friendCounts(env, userId) {
  const row = await env.DB.prepare(
    `SELECT
       (SELECT COUNT(*) FROM friendships WHERE status = 'pending' AND addressee_id = ?) AS incoming,
       (SELECT COUNT(*) FROM friendships WHERE status = 'pending' AND requester_id = ?) AS outgoing,
       (SELECT COUNT(*) FROM friendships
         WHERE status = 'accepted' AND (requester_id = ? OR addressee_id = ?)) AS friends`,
  ).bind(userId, userId, userId, userId).first();
  return {
    incoming: Number(row?.incoming || 0),
    outgoing: Number(row?.outgoing || 0),
    friends: Number(row?.friends || 0),
  };
}

/**
 * 나와 얽힌 친구 행 전부(친구·받은 요청·보낸 요청)를 한 번에 읽어
 *   { rows, byOther: Map<상대 id, { status, direction, since }> }
 * 로 만든다. 검색 결과의 관계 표시도 이 map 으로 계산한다(쿼리를 결과마다 돌리지 않는다).
 */
export async function loadFriendships(env, userId) {
  const result = await env.DB.prepare(
    `SELECT pair_key, requester_id, addressee_id, status, created_at, updated_at
       FROM friendships
      WHERE requester_id = ? OR addressee_id = ?
      ORDER BY updated_at DESC
      LIMIT ?`,
  ).bind(userId, userId, FRIEND_LIST_LIMIT).all();
  const rows = result?.results || [];
  const byOther = new Map();
  for (const row of rows) {
    const otherId = row.requester_id === userId ? row.addressee_id : row.requester_id;
    const direction = row.requester_id === userId ? 'outgoing' : 'incoming';
    byOther.set(otherId, {
      status: row.status,
      direction,
      since: Number(row.updated_at || row.created_at || 0),
    });
  }
  return { rows, byOther };
}

/** 상대 id 목록의 사람 정보를 한 번에 읽는다(IN 절은 전부 바인딩). */
export async function loadUsersByIds(env, ids) {
  const unique = [...new Set(ids.filter(Boolean))].slice(0, FRIEND_LIST_LIMIT);
  if (!unique.length) return new Map();
  const placeholders = unique.map(() => '?').join(',');
  const result = await env.DB.prepare(
    `SELECT id, username, nickname, display_name, avatar_updated_at
       FROM users WHERE id IN (${placeholders})`,
  ).bind(...unique).all();
  const map = new Map();
  for (const row of result?.results || []) map.set(row.id, row);
  return map;
}

/** 검색 결과·목록 한 줄: 사람 정보 + 나와의 관계. */
export function relationUser(row, relation) {
  const user = socialUser(row);
  if (!user) return null;
  return { ...user, relation: relation || 'none' };
}

/** LIKE 검색어에서 와일드카드(`%`·`_`·`\`)를 글자 그대로 찾도록 이스케이프한다. */
export function likeEscape(text) {
  return String(text).replace(/[\\%_]/g, (char) => `\\${char}`);
}

/** 사용자 id 형식(`u_` + 32자 hex). */
export function parseUserId(raw) {
  const id = String(raw ?? '').trim();
  return /^u_[0-9a-f]{32}$/.test(id) ? id : '';
}
