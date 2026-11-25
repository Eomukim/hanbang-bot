/**
 * GET /api/mail/sent
 * 내가 보낸 메일(내가 지우지 않았고 휴지통에 넣지 않은 것)을 최신순으로 내려 준다. 로그인 필수.
 * isRead 는 받는 사람이 열어 봤는지다.
 */
import { ok, fail, currentSession, checkReadRate } from '../../_lib/auth.js';
import { mailView, LIST_LIMIT } from '../../_lib/mail.js';

export async function onRequestGet({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '메일함 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 다른 플레이어와 메일을 주고받을 수 있어요.');

  const limited = await checkReadRate(env, request, 'sent', 150, 60);
  if (limited) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 열어 주세요.', {
      'retry-after': String(limited.retryAfter),
    });
  }

  const rows = await env.DB.prepare(
    `SELECT m.id, m.sender_username, m.recipient_username, m.reply_to_id, m.subject, m.body,
            m.is_read, m.read_at, m.created_at, m.updated_at,
            ru.nickname AS recipient_nickname, ru.display_name AS recipient_display_name,
            ru.avatar_updated_at AS recipient_avatar_at
       FROM mails m LEFT JOIN users ru ON ru.id = m.recipient_id
      WHERE m.sender_id = ? AND m.deleted_by_sender = 0 AND m.sender_trashed_at IS NULL
      ORDER BY m.created_at DESC, m.id DESC
      LIMIT ?`,
  ).bind(session.id, LIST_LIMIT).all();

  const mails = (rows?.results || []).map(mailView);
  return ok({ mails, limit: LIST_LIMIT });
}
