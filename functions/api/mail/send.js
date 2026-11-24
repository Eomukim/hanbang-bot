/**
 * POST /api/mail/send
 * 다른 플레이어에게 메일을 보낸다. 로그인 필수.
 *
 * body: { to, subject, body, replyToId? }
 *   - to: `@아이디` 또는 `아이디`
 *   - replyToId: 받은 메일에서 답장할 때 그 메일 id (본인이 주고받은 메일만 연결된다)
 *
 * 스팸 방지로 사용자별 분당 10통·시간당 60통 제한을 둔다(auth_throttle 표).
 */
import { ok, fail, readJson, currentSession, hitThrottle } from '../../_lib/auth.js';
import { validateMail, newMailId } from '../../_lib/mail.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '메일함 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 다른 플레이어와 메일을 주고받을 수 있어요.');

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const body = parsed.body;

  const perMinute = await hitThrottle(env, `mail:min:${session.id}`, 10, 60);
  if (!perMinute.allowed) {
    return fail(429, 'rate_limited', '메일을 너무 빨리 많이 보냈어요. 잠시 후 다시 보내 주세요.', {
      'retry-after': String(perMinute.retryAfter),
    });
  }
  const perHour = await hitThrottle(env, `mail:hour:${session.id}`, 60, 3600);
  if (!perHour.allowed) {
    return fail(429, 'rate_limited', '한 시간에 보낼 수 있는 메일 수를 넘었어요. 잠시 후 다시 보내 주세요.', {
      'retry-after': String(perHour.retryAfter),
    });
  }

  const checked = validateMail(body);
  if (!checked.ok) return fail(400, checked.error, checked.message);

  const recipient = await env.DB.prepare(
    'SELECT id, username FROM users WHERE username = ?',
  ).bind(checked.recipient).first();
  if (!recipient) {
    return fail(
      404,
      'recipient_not_found',
      `@${checked.recipient} 아이디를 찾지 못했어요. 받는 사람 아이디를 다시 확인해 주세요.`,
    );
  }
  if (recipient.id === session.id) {
    return fail(400, 'self_mail', '자기 자신에게는 메일을 보낼 수 없어요.');
  }

  let replyToId = null;
  const rawReply = String(body.replyToId ?? '').trim();
  if (rawReply) {
    const original = await env.DB.prepare(
      'SELECT id FROM mails WHERE id = ? AND (sender_id = ? OR recipient_id = ?)',
    ).bind(rawReply, session.id, session.id).first();
    if (!original) return fail(400, 'reply_invalid', '답장할 메일을 찾지 못했어요.');
    replyToId = original.id;
  }

  const id = newMailId();
  const now = Date.now();
  await env.DB.prepare(
    `INSERT INTO mails (id, sender_id, sender_username, recipient_id, recipient_username,
                        reply_to_id, subject, body, is_read, read_at,
                        deleted_by_sender, deleted_by_recipient, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, 0, 0, ?)`,
  ).bind(
    id,
    session.id,
    session.username,
    recipient.id,
    recipient.username,
    replyToId,
    checked.subject,
    checked.body,
    now,
  ).run();

  return ok({
    mail: {
      id,
      recipientUsername: recipient.username,
      subject: checked.subject,
      replyToId,
      createdAt: now,
    },
  });
}
