/**
 * POST /api/mail/trash/empty
 * 내 휴지통을 비운다 — 휴지통에 있는 메일을 내 쪽에서 모두 완전 삭제한다. 로그인 필수.
 *
 * - 내가 받은 메일은 deleted_by_recipient, 내가 보낸 메일은 deleted_by_sender 를 세운다.
 * - 양쪽이 모두 완전 삭제한 행은 그때 실제로 지운다(상대 메일함은 그대로).
 * - 실수 방지는 화면에서 `정말 비울까?` 두 번 확인으로 하고, 여기서는 연타를 막는
 *   사용자별 제한(10분에 10회)과 batch 로 한 번에 처리한다.
 */
import { ok, fail, currentSession, hitThrottle } from '../../../_lib/auth.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '메일함 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 다른 플레이어와 메일을 주고받을 수 있어요.');

  const limit = await hitThrottle(env, `mail:trash-empty:${session.id}`, 10, 600);
  if (!limit.allowed) {
    return fail(429, 'rate_limited', '휴지통 비우기를 너무 자주 눌렀어요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limit.retryAfter),
    });
  }

  const countRow = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM mails
      WHERE ((recipient_id = ? AND recipient_trashed_at IS NOT NULL AND deleted_by_recipient = 0)
          OR (sender_id = ? AND sender_trashed_at IS NOT NULL AND deleted_by_sender = 0))`,
  ).bind(session.id, session.id).first();
  const count = Number(countRow?.n || 0);

  if (count > 0) {
    await env.DB.batch([
      env.DB.prepare(
        `UPDATE mails SET deleted_by_recipient = 1
          WHERE recipient_id = ? AND recipient_trashed_at IS NOT NULL AND deleted_by_recipient = 0`,
      ).bind(session.id),
      env.DB.prepare(
        `UPDATE mails SET deleted_by_sender = 1
          WHERE sender_id = ? AND sender_trashed_at IS NOT NULL AND deleted_by_sender = 0`,
      ).bind(session.id),
      env.DB.prepare(
        `DELETE FROM mails
          WHERE deleted_by_sender = 1 AND deleted_by_recipient = 1
            AND (sender_id = ? OR recipient_id = ?)`,
      ).bind(session.id, session.id),
    ]);
  }

  return ok({ purged: count });
}

export async function onRequest({ request }) {
  return fail(405, 'method_not_allowed', '지원하지 않는 요청 방식이에요.');
}
