/**
 * POST /api/mail/read
 * 받은 메일을 읽음으로 표시한다(read_at 기록). 로그인 필수.
 * 이미 읽은 메일이면 아무것도 바꾸지 않는다.
 */
import { ok, fail, readJsonBody, currentSession } from '../../_lib/auth.js';
import { parseId } from '../../_lib/mail.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '메일함 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 다른 플레이어와 메일을 주고받을 수 있어요.');

  const body = await readJsonBody(request);
  if (!body) return fail(400, 'bad_request', '요청을 이해하지 못했어요.');
  const id = parseId(body.id, 'm');
  if (!id) return fail(400, 'id_required', '어떤 메일인지 알 수 없어요.');

  const result = await env.DB.prepare(
    `UPDATE mails SET is_read = 1, read_at = ?
      WHERE id = ? AND recipient_id = ? AND is_read = 0`,
  ).bind(Date.now(), id, session.id).run();

  const unread = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM mails
      WHERE recipient_id = ? AND is_read = 0 AND deleted_by_recipient = 0`,
  ).bind(session.id).first();

  return ok({
    updated: Number(result?.meta?.changes || 0),
    unreadMailCount: Number(unread?.n || 0),
  });
}
