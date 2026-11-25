/**
 * POST /api/mail/delete
 * 메일 한 통을 내 쪽에서 **완전 삭제**한다. 로그인 필수.
 *
 * - 화면의 `삭제` 는 먼저 휴지통(POST /api/mail/trash)으로 옮기고, 휴지통의
 *   `완전 삭제` 와 `휴지통 비우기` 가 이 API 를 쓴다.
 * - 받은 사람이 지우면 deleted_by_recipient, 보낸 사람이 지우면 deleted_by_sender 를 세운다.
 *   그래서 한쪽이 지워도 상대의 메일함은 그대로 남는다.
 * - 양쪽이 모두 지우면 그때 행을 실제로 지운다.
 *
 * 권한: `sender_id` 또는 `recipient_id` 가 세션 사용자와 같은 메일만 지운다.
 *       다른 사람의 메일은 있는지조차 알려 주지 않고 404 로 답한다.
 */
import { ok, fail, readJson, currentSession, hitThrottle } from '../../_lib/auth.js';
import { parseId } from '../../_lib/mail.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '메일함 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 다른 플레이어와 메일을 주고받을 수 있어요.');

  const limit = await hitThrottle(env, `mail:purge:${session.id}`, 60, 60);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const body = parsed.body;
  const id = parseId(body.id, 'm');
  if (!id) return fail(400, 'id_required', '어떤 메일인지 알 수 없어요.');

  const mail = await env.DB.prepare(
    'SELECT id, sender_id, recipient_id, deleted_by_sender, deleted_by_recipient FROM mails WHERE id = ?',
  ).bind(id).first();
  if (!mail) return fail(404, 'not_found', '이미 완전히 지운 메일이에요.');

  const isSender = mail.sender_id === session.id;
  const isRecipient = mail.recipient_id === session.id;
  if (!isSender && !isRecipient) {
    return fail(404, 'not_found', '이미 완전히 지운 메일이에요.');
  }

  const deletedBySender = Number(mail.deleted_by_sender) === 1 || isSender ? 1 : 0;
  const deletedByRecipient = Number(mail.deleted_by_recipient) === 1 || isRecipient ? 1 : 0;

  if (deletedBySender === 1 && deletedByRecipient === 1) {
    await env.DB.prepare('DELETE FROM mails WHERE id = ?').bind(id).run();
    return ok({ deleted: true, purged: true });
  }

  await env.DB.prepare(
    `UPDATE mails SET deleted_by_sender = ?, deleted_by_recipient = ? WHERE id = ?`,
  ).bind(deletedBySender, deletedByRecipient, id).run();

  return ok({ deleted: true, purged: false });
}
