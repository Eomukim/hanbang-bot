/**
 * POST /api/mail/restore
 * 휴지통에 있는 내 메일을 원래 함(받은 메일·보낸 메일)으로 되돌린다. 로그인 필수.
 *
 * - 내 쪽 `*_trashed_at` 만 비운다. 상대의 상태는 건드리지 않는다.
 * - 휴지통에 없는 메일이면 404 로 답한다(남의 메일도 같은 답 — 존재 여부를 알려 주지 않는다).
 */
import { ok, fail, readJson, currentSession, hitThrottle } from '../../_lib/auth.js';
import { parseId } from '../../_lib/mail.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '메일함 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 다른 플레이어와 메일을 주고받을 수 있어요.');

  const limit = await hitThrottle(env, `mail:restore:${session.id}`, 120, 60);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const id = parseId(parsed.body.id, 'm');
  if (!id) return fail(400, 'id_required', '어떤 메일인지 알 수 없어요.');

  const mail = await env.DB.prepare(
    `SELECT id, sender_id, recipient_id, deleted_by_sender, deleted_by_recipient,
            sender_trashed_at, recipient_trashed_at
       FROM mails WHERE id = ?`,
  ).bind(id).first();
  if (!mail) return fail(404, 'not_found', '휴지통에 없는 메일이에요.');

  const isRecipient = mail.recipient_id === session.id;
  const isSender = mail.sender_id === session.id;
  if (!isRecipient && !isSender) return fail(404, 'not_found', '휴지통에 없는 메일이에요.');

  const trashed = isRecipient ? mail.recipient_trashed_at : mail.sender_trashed_at;
  if (!trashed) return fail(404, 'not_found', '휴지통에 없는 메일이에요.');
  if (Number(isRecipient ? mail.deleted_by_recipient : mail.deleted_by_sender) === 1) {
    return fail(404, 'not_found', '이미 완전히 지운 메일이에요.');
  }

  if (isRecipient) {
    await env.DB.prepare(
      `UPDATE mails SET recipient_trashed_at = NULL
        WHERE id = ? AND recipient_id = ? AND recipient_trashed_at IS NOT NULL`,
    ).bind(id, session.id).run();
  } else {
    await env.DB.prepare(
      `UPDATE mails SET sender_trashed_at = NULL
        WHERE id = ? AND sender_id = ? AND sender_trashed_at IS NOT NULL`,
    ).bind(id, session.id).run();
  }

  return ok({ restored: true, folder: isRecipient ? 'inbox' : 'sent' });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.');
}
