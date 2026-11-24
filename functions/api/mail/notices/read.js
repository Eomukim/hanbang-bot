/**
 * POST /api/mail/notices/read
 * 공지를 읽음으로 표시한다(사용자별 notice_reads). 로그인 필수.
 *
 * body: { id }  한 건, { ids: [...] } 여러 건, { all: true } 지금 있는 공지 전부
 */
import { ok, fail, readJsonBody, currentSession } from '../../../_lib/auth.js';
import { parseId } from '../../../_lib/mail.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '공지 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 공지 읽음 상태가 기기에 상관없이 유지돼요.');

  const body = await readJsonBody(request);
  if (!body) return fail(400, 'bad_request', '요청을 이해하지 못했어요.');
  const now = Date.now();

  if (body.all === true) {
    await env.DB.prepare(
      `INSERT OR IGNORE INTO notice_reads (user_id, notice_id, read_at)
       SELECT ?, id, ? FROM notices`,
    ).bind(session.id, now).run();
    return ok({ marked: 'all' });
  }

  const ids = [];
  if (body.id != null) {
    const one = parseId(body.id, 'n');
    if (one) ids.push(one);
  }
  if (Array.isArray(body.ids)) {
    for (const raw of body.ids.slice(0, 100)) {
      const one = parseId(raw, 'n');
      if (one && !ids.includes(one)) ids.push(one);
    }
  }
  if (!ids.length) return fail(400, 'id_required', '어떤 공지를 읽었는지 알 수 없어요.');

  const statement = env.DB.prepare(
    `INSERT OR REPLACE INTO notice_reads (user_id, notice_id, read_at) VALUES (?, ?, ?)`,
  );
  const batch = ids.map((id) => statement.bind(session.id, id, now));
  await env.DB.batch(batch);

  const unread = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM notices o
      WHERE NOT EXISTS (
        SELECT 1 FROM notice_reads r WHERE r.notice_id = o.id AND r.user_id = ?
      )`,
  ).bind(session.id).first();

  return ok({ marked: ids.length, unreadNoticeCount: Number(unread?.n || 0) });
}
