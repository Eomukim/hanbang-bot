/**
 * /api/mail/trash
 *
 * GET  — 내 휴지통에 있는 메일(내가 받은 것·보낸 것 모두)을 최신 휴지통 이동순으로 내려 준다.
 *         각 항목의 folder('inbox'|'sent')로 어느 함에서 왔는지 알 수 있다. 로그인 필수.
 * POST — 내 메일함에서 메일 한 통을 휴지통으로 옮긴다(body {id}). 로그인 필수.
 *
 * - 받는 사람이 옮기면 recipient_trashed_at, 보낸 사람이 옮기면 sender_trashed_at 만 기록한다.
 *   그래서 한쪽이 휴지통에 넣어도 상대의 메일함은 그대로다(각자 독립).
 * - 휴지통에 있는 메일은 안 읽은 메일 수(빨간 동그라미)에도 세지 않는다.
 * - 여기서는 행을 지우지 않는다. 완전 삭제는 POST /api/mail/delete, 휴지통 비우기는
 *   POST /api/mail/trash/empty 다.
 *
 * 권한: `sender_id` 또는 `recipient_id` 가 세션 사용자와 같은 메일만 옮긴다.
 *       다른 사람의 메일은 있는지조차 알려 주지 않고 404 로 답한다.
 */
import { ok, fail, readJson, currentSession, hitThrottle, checkReadRate } from '../../_lib/auth.js';
import { mailView, parseId, nowStamp, LIST_LIMIT } from '../../_lib/mail.js';

export async function onRequestGet({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '메일함 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 다른 플레이어와 메일을 주고받을 수 있어요.');

  const limited = await checkReadRate(env, request, 'trash', 150, 60);
  if (limited) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 열어 주세요.', {
      'retry-after': String(limited.retryAfter),
    });
  }

  const rows = await env.DB.prepare(
    `SELECT m.id, m.sender_username, m.recipient_username, m.reply_to_id, m.subject, m.body,
            m.is_read, m.read_at, m.created_at, m.updated_at,
            su.nickname AS sender_nickname, su.display_name AS sender_display_name,
            su.avatar_updated_at AS sender_avatar_at,
            ru.nickname AS recipient_nickname, ru.display_name AS recipient_display_name,
            ru.avatar_updated_at AS recipient_avatar_at,
            CASE WHEN m.recipient_id = ? THEN 'inbox' ELSE 'sent' END AS folder,
            CASE WHEN m.recipient_id = ? THEN m.recipient_trashed_at ELSE m.sender_trashed_at END AS trashed_at
       FROM mails m
       LEFT JOIN users su ON su.id = m.sender_id
       LEFT JOIN users ru ON ru.id = m.recipient_id
      WHERE ((m.recipient_id = ? AND m.recipient_trashed_at IS NOT NULL AND m.deleted_by_recipient = 0)
          OR (m.sender_id = ? AND m.sender_trashed_at IS NOT NULL AND m.deleted_by_sender = 0))
      ORDER BY trashed_at DESC, m.created_at DESC, m.id DESC
      LIMIT ?`,
  ).bind(session.id, session.id, session.id, session.id, LIST_LIMIT).all();

  const mails = (rows?.results || []).map(mailView);
  return ok({ mails, limit: LIST_LIMIT });
}

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '메일함 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 다른 플레이어와 메일을 주고받을 수 있어요.');

  const limit = await hitThrottle(env, `mail:trash:${session.id}`, 120, 60);
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
  if (!mail) return fail(404, 'not_found', '이미 지운 메일이에요.');

  const isRecipient = mail.recipient_id === session.id;
  const isSender = mail.sender_id === session.id;
  if (!isRecipient && !isSender) return fail(404, 'not_found', '이미 지운 메일이에요.');
  if (Number(isRecipient ? mail.deleted_by_recipient : mail.deleted_by_sender) === 1) {
    return fail(404, 'not_found', '이미 지운 메일이에요.');
  }

  const already = isRecipient ? mail.recipient_trashed_at : mail.sender_trashed_at;
  if (already) {
    return ok({ trashed: true, folder: isRecipient ? 'inbox' : 'sent', already: true });
  }

  const stamp = nowStamp();
  if (isRecipient) {
    await env.DB.prepare(
      `UPDATE mails SET recipient_trashed_at = ?
        WHERE id = ? AND recipient_trashed_at IS NULL AND deleted_by_recipient = 0`,
    ).bind(stamp, id).run();
  } else {
    await env.DB.prepare(
      `UPDATE mails SET sender_trashed_at = ?
        WHERE id = ? AND sender_trashed_at IS NULL AND deleted_by_sender = 0`,
    ).bind(stamp, id).run();
  }

  return ok({ trashed: true, folder: isRecipient ? 'inbox' : 'sent', trashedAt: stamp });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.');
}
