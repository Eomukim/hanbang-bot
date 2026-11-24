/**
 * /api/mail/notices
 *
 * GET    — 공지사항 목록. 게스트도 읽는다(로그인하면 읽음 여부가 함께 온다).
 * POST   — 공지 작성. `ADMIN_USERNAMES` 에 있는 아이디만(아니면 403).
 * DELETE — 공지 삭제. 관리자만(아니면 403). 본문 {id} 또는 `?id=`.
 *
 * 폭주 방지: 조회는 IP별, 작성·삭제는 관리자 계정별로 창(window) 제한을 둔다.
 * 교차 사이트 요청은 `_middleware.js` 의 출처 검사가 먼저 막는다.
 */
import { ok, fail, json, readJson, currentSession, hitThrottle, checkReadRate } from '../../_lib/auth.js';
import { isAdmin, validateNotice, newNoticeId, noticeView, parseId } from '../../_lib/mail.js';

const NOTICE_LIMIT = 50;

async function listNotices(env, session) {
  let rows;
  if (session) {
    rows = await env.DB.prepare(
      `SELECT n.id, n.author_username, n.title, n.body, n.created_at,
              CASE WHEN r.notice_id IS NULL THEN 0 ELSE 1 END AS is_read
         FROM notices n
         LEFT JOIN notice_reads r ON r.notice_id = n.id AND r.user_id = ?
        ORDER BY n.created_at DESC, n.id DESC
        LIMIT ?`,
    ).bind(session.id, NOTICE_LIMIT).all();
  } else {
    rows = await env.DB.prepare(
      `SELECT id, author_username, title, body, created_at, 0 AS is_read
         FROM notices
        ORDER BY created_at DESC, id DESC
        LIMIT ?`,
    ).bind(NOTICE_LIMIT).all();
  }
  return (rows?.results || []).map(noticeView);
}

export async function onRequestGet({ request, env }) {
  if (!env.DB) return ok({ notices: [], signedIn: false, isAdmin: false, latestNoticeAt: 0 });

  const limited = await checkReadRate(env, request, 'notices', 150, 60);
  if (limited) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 열어 주세요.', {
      'retry-after': String(limited.retryAfter),
    });
  }

  const session = await currentSession(env, request);
  const notices = await listNotices(env, session);
  return ok({
    notices,
    signedIn: Boolean(session),
    isAdmin: Boolean(session) && isAdmin(env, session.username),
    latestNoticeAt: notices.length ? Math.max(...notices.map((n) => n.createdAt)) : 0,
  });
}

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '공지 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session || !isAdmin(env, session.username)) {
    return fail(403, 'forbidden', '공지 작성은 관리자만 할 수 있어요.');
  }

  const limit = await hitThrottle(env, `notice:write:${session.id}`, 20, 600);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '공지를 너무 자주 올렸어요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const checked = validateNotice(parsed.body);
  if (!checked.ok) return fail(400, checked.error, checked.message);

  const id = newNoticeId();
  const now = Date.now();
  await env.DB.prepare(
    `INSERT INTO notices (id, author_username, title, body, created_at)
     VALUES (?, ?, ?, ?, ?)`,
  ).bind(id, session.username, checked.title, checked.body, now).run();

  return ok({ notice: { id, authorUsername: session.username, title: checked.title, body: checked.body, createdAt: now } });
}

export async function onRequestDelete({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '공지 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session || !isAdmin(env, session.username)) {
    return fail(403, 'forbidden', '공지 삭제는 관리자만 할 수 있어요.');
  }

  const limit = await hitThrottle(env, `notice:delete:${session.id}`, 20, 600);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  // 본문이 있으면 본문의 id, 없으면 `?id=`. 너무 큰 본문은 그대로 거부한다.
  const parsed = await readJson(request);
  if (!parsed.ok && parsed.status === 413) return fail(parsed.status, parsed.error, parsed.message);
  const fromQuery = new URL(request.url).searchParams.get('id') || '';
  const raw = parsed.ok && parsed.body.id != null ? parsed.body.id : fromQuery;
  const id = parseId(raw, 'n');
  if (!id) return fail(400, 'id_required', '어떤 공지를 지울지 알 수 없어요.');

  const existing = await env.DB.prepare('SELECT id FROM notices WHERE id = ?').bind(id).first();
  if (!existing) return fail(404, 'not_found', '이미 지운 공지예요.');

  await env.DB.prepare('DELETE FROM notice_reads WHERE notice_id = ?').bind(id).run();
  await env.DB.prepare('DELETE FROM notices WHERE id = ?').bind(id).run();
  return ok({ deleted: true });
}

export async function onRequest({ request }) {
  return json(
    { ok: false, error: 'method_not_allowed', message: '지원하지 않는 요청 방식이에요.' },
    405,
    { allow: 'GET, POST, DELETE' },
  );
}
