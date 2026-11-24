/**
 * /api/mail/notices
 *
 * GET    — 공지사항 목록. 게스트도 읽는다(로그인하면 읽음 여부가 함께 온다).
 * POST   — 공지 작성. `ADMIN_USERNAMES` 에 있는 아이디만(아니면 403).
 * DELETE — 공지 삭제. 관리자만(아니면 403). 본문 {id} 또는 `?id=`.
 */
import { ok, fail, json, readJsonBody, currentSession } from '../../_lib/auth.js';
import { isAdmin, validateNotice, newNoticeId, noticeView } from '../../_lib/mail.js';

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

  const body = await readJsonBody(request);
  if (!body) return fail(400, 'bad_request', '요청을 이해하지 못했어요.');
  const checked = validateNotice(body);
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

  const body = await readJsonBody(request);
  const fromQuery = new URL(request.url).searchParams.get('id') || '';
  const raw = body && body.id != null ? body.id : fromQuery;
  const id = String(raw || '').trim();
  if (!id || !id.startsWith('n_') || id.length > 64) {
    return fail(400, 'id_required', '어떤 공지를 지울지 알 수 없어요.');
  }

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
