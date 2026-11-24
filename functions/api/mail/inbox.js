/**
 * GET /api/mail/inbox
 * 나에게 온 메일(내가 지우지 않은 것)을 최신순으로 내려 준다. 로그인 필수.
 */
import { ok, fail, currentSession, checkReadRate } from '../../_lib/auth.js';
import { mailView, LIST_LIMIT } from '../../_lib/mail.js';

export async function onRequestGet({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '메일함 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 다른 플레이어와 메일을 주고받을 수 있어요.');

  const limited = await checkReadRate(env, request, 'inbox', 150, 60);
  if (limited) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 열어 주세요.', {
      'retry-after': String(limited.retryAfter),
    });
  }

  const rows = await env.DB.prepare(
    `SELECT id, sender_username, recipient_username, reply_to_id, subject, body,
            is_read, read_at, created_at
       FROM mails
      WHERE recipient_id = ? AND deleted_by_recipient = 0
      ORDER BY created_at DESC, id DESC
      LIMIT ?`,
  ).bind(session.id, LIST_LIMIT).all();

  const mails = (rows?.results || []).map(mailView);
  return ok({
    mails,
    unreadCount: mails.filter((mail) => !mail.isRead).length,
    limit: LIST_LIMIT,
  });
}
