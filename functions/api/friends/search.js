/**
 * GET /api/friends/search?q=<아이디 일부>
 * 아이디로 사람을 찾는다. 로그인 필수.
 *
 * - `@` 는 붙여도 되고 안 붙여도 된다. 2~12자 아이디만 검색어로 받는다.
 * - 정확히 같은 아이디 → 앞부분 일치 → 가운데 포함 순으로, 최대 8건만 내려 준다(전체 목록 덤프 방지).
 * - 내려 주는 값은 닉네임·`@아이디`·프로필 사진 시각·나와의 관계뿐이다.
 *   비밀번호 해시·세션·가입일 등은 응답에 넣지 않는다.
 * - 검색은 사용자당 분당 40회, IP당 분당 120회로 제한한다(아이디 목록 긁기 방지).
 */
import { ok, fail, currentSession, hitThrottle, checkReadRate } from '../../_lib/auth.js';
import {
  SEARCH_MIN,
  SEARCH_LIMIT,
  loadFriendships,
  relationUser,
  likeEscape,
} from '../../_lib/social.js';

const QUERY_RE = /^[가-힣a-zA-Z0-9_]{2,12}$/u;

export async function onRequestGet({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '친구 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 아이디로 친구를 찾을 수 있어요.');

  const limited = await checkReadRate(env, request, 'friends-search', 120, 60);
  if (limited) {
    return fail(429, 'rate_limited', '검색이 너무 잦아요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limited.retryAfter),
    });
  }
  const perUser = await hitThrottle(env, `friend:search:${session.id}`, 40, 60);
  if (!perUser.allowed) {
    return fail(429, 'rate_limited', '검색이 너무 잦아요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(perUser.retryAfter),
    });
  }

  let raw = '';
  try {
    raw = String(new URL(request.url).searchParams.get('q') || '');
  } catch {
    raw = '';
  }
  const query = raw.trim().replace(/^@+/, '');
  if ([...query].length < SEARCH_MIN) {
    return fail(400, 'query_short', '아이디를 두 글자 이상 넣어 주세요.');
  }
  if (!QUERY_RE.test(query)) {
    return fail(400, 'query_invalid', '아이디는 2~12자의 한글·영문·숫자·밑줄이에요.');
  }

  const escaped = likeEscape(query);
  const result = await env.DB.prepare(
    `SELECT id, username, nickname, display_name, avatar_updated_at, last_seen_at
       FROM users
      WHERE id <> ? AND username LIKE ? ESCAPE '\\'
      ORDER BY CASE WHEN lower(username) = lower(?) THEN 0
                    WHEN lower(username) LIKE ? ESCAPE '\\' THEN 1
                    ELSE 2 END,
               length(username), username
      LIMIT ?`,
  ).bind(session.id, `%${escaped}%`, query, `${escaped}%`, SEARCH_LIMIT).all();

  const { byOther } = await loadFriendships(env, session.id);
  const results = (result?.results || []).map((row) => {
    const relation = byOther.get(row.id);
    const label = !relation
      ? 'none'
      : relation.status === 'accepted'
        ? 'friend'
        : relation.direction;
    return relationUser(row, label);
  }).filter(Boolean);

  return ok({ query, results, limit: SEARCH_LIMIT });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.', { allow: 'GET' });
}
