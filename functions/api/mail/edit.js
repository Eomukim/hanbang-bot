/**
 * POST /api/mail/edit
 * 내가 보낸 메일의 제목·본문을 고친다. 로그인 필수.
 *
 * body: { id, subject, body }
 *
 * - `sender_id = 세션 사용자` 인 메일만 고친다. 받는 사람·제3자는 404(존재 여부도 알려 주지 않는다).
 * - 발신자가 이미 휴지통에 넣었거나 완전 삭제한 메일은 고칠 수 없다(404).
 * - 제목 80자·본문 2000자(발송과 같은 상한)만 바꾸며 받는 사람은 그대로다.
 * - 고친 시각을 `updated_at`(ISO)에 남기고, 목록·상세에 `(수정됨)` 으로 보인다.
 * - 발송과 같은 32KB 본문 제한·출처(CSRF) 검사·사용자별 제한(10분에 30회)을 쓴다.
 */
import { ok, fail, readJson, currentSession, hitThrottle } from '../../_lib/auth.js';
import { validateMailEdit, parseId, nowStamp, mailView } from '../../_lib/mail.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '메일함 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 다른 플레이어와 메일을 주고받을 수 있어요.');

  const limit = await hitThrottle(env, `mail:edit:${session.id}`, 30, 600);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '메일 수정을 너무 자주 했어요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const id = parseId(parsed.body.id, 'm');
  if (!id) return fail(400, 'id_required', '어떤 메일인지 알 수 없어요.');

  const checked = validateMailEdit(parsed.body);
  if (!checked.ok) return fail(400, checked.error, checked.message);

  const mail = await env.DB.prepare(
    `SELECT id, sender_id, sender_trashed_at, deleted_by_sender FROM mails WHERE id = ?`,
  ).bind(id).first();
  // 내가 보낸 메일이 아니거나, 이미 내가 지운(휴지통·완전 삭제) 메일은 고칠 수 없다.
  if (!mail || mail.sender_id !== session.id) {
    return fail(404, 'not_found', '수정할 수 있는 메일이 아니에요.');
  }
  if (mail.sender_trashed_at || Number(mail.deleted_by_sender) === 1) {
    return fail(404, 'not_found', '휴지통에 있는 메일은 수정할 수 없어요. 먼저 복구해 주세요.');
  }

  const stamp = nowStamp();
  await env.DB.prepare(
    `UPDATE mails SET subject = ?, body = ?, updated_at = ?
      WHERE id = ? AND sender_id = ?`,
  ).bind(checked.subject, checked.body, stamp, id, session.id).run();

  const row = await env.DB.prepare(
    `SELECT id, sender_username, recipient_username, reply_to_id, subject, body,
            is_read, read_at, created_at, updated_at
       FROM mails WHERE id = ?`,
  ).bind(id).first();

  return ok({ mail: mailView(row) });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.');
}
