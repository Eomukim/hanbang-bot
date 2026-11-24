/**
 * POST /api/mail/delete
 * 내 메일함에서 메일 한 통을 지운다(소프트 삭제). 로그인 필수.
 *
 * - 받은 사람이 지우면 deleted_by_recipient, 보낸 사람이 지우면 deleted_by_sender 를 세운다.
 *   그래서 한쪽이 지워도 상대의 메일함은 그대로 남는다.
 * - 양쪽이 모두 지우면 그때 행을 실제로 지운다.
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

  const mail = await env.DB.prepare(
    'SELECT id, sender_id, recipient_id, deleted_by_sender, deleted_by_recipient FROM mails WHERE id = ?',
  ).bind(id).first();
  if (!mail) return fail(404, 'not_found', '이미 지운 메일이에요.');

  const isSender = mail.sender_id === session.id;
  const isRecipient = mail.recipient_id === session.id;
  if (!isSender && !isRecipient) {
    return fail(404, 'not_found', '이미 지운 메일이에요.');
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
