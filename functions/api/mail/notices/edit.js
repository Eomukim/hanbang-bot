/**
 * POST /api/mail/notices/edit
 * 공지사항의 제목·본문을 고친다. `ADMIN_USERNAMES` 관리자만(아니면 403).
 *
 * body: { id, title, body }
 *
 * - 공지 작성과 같은 상한(제목 100자·본문 5000자)과 사용자별 제한(10분에 20회)을 쓴다.
 * - 고친 시각을 `updated_at`(ISO)에 남기고, 목록·상세에 `(수정됨)` 으로 보인다.
 * - 읽음 기록(`notice_reads`)은 그대로 둔다 — 수정했다고 모두에게 새 공지로 다시 뜨지 않는다.
 */
import { ok, fail, readJson, currentSession, hitThrottle } from '../../../_lib/auth.js';
import { isAdmin, validateNotice, parseId, nowStamp, noticeView } from '../../../_lib/mail.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '공지 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session || !isAdmin(env, session.username)) {
    return fail(403, 'forbidden', '공지 수정은 관리자만 할 수 있어요.');
  }

  const limit = await hitThrottle(env, `notice:edit:${session.id}`, 20, 600);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '공지 수정을 너무 자주 했어요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const id = parseId(parsed.body.id, 'n');
  if (!id) return fail(400, 'id_required', '어떤 공지인지 알 수 없어요.');

  const checked = validateNotice(parsed.body);
  if (!checked.ok) return fail(400, checked.error, checked.message);

  const existing = await env.DB.prepare('SELECT id FROM notices WHERE id = ?').bind(id).first();
  if (!existing) return fail(404, 'not_found', '이미 지운 공지예요.');

  const stamp = nowStamp();
  await env.DB.prepare(
    'UPDATE notices SET title = ?, body = ?, updated_at = ? WHERE id = ?',
  ).bind(checked.title, checked.body, stamp, id).run();

  const row = await env.DB.prepare(
    `SELECT id, author_username, title, body, created_at, updated_at
       FROM notices WHERE id = ?`,
  ).bind(id).first();

  return ok({ notice: noticeView(row) });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.');
}
