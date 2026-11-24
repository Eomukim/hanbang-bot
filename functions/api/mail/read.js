/**
 * POST /api/mail/read
 * 받은 메일을 읽음으로 표시한다(read_at 기록). 로그인 필수.
 *
 * 권한: `recipient_id` 가 세션 사용자와 같은 메일만 읽음 처리한다.
 *       다른 사람의 메일 id 로 찔러 보내도 아무 행도 바뀌지 않는다(updated 0).
 * 이미 읽은 메일이면 아무것도 바꾸지 않는다.
 */
import { ok, fail, readJson, currentSession, checkReadRate } from '../../_lib/auth.js';
import { parseId } from '../../_lib/mail.js';

export async function onRequestPost({ request, env }) {
  if (!env.DB) return fail(503, 'not_configured', '메일함 서버가 아직 준비되지 않았어요.');
  const session = await currentSession(env, request);
  if (!session) return fail(401, 'not_signed_in', '로그인하면 다른 플레이어와 메일을 주고받을 수 있어요.');

  const limited = await checkReadRate(env, request, 'mail-read', 240, 60);
  if (limited) {
    return fail(429, 'rate_limited', '요청이 너무 잦아요. 잠시 후 다시 시도해 주세요.', {
      'retry-after': String(limited.retryAfter),
    });
  }

  const parsed = await readJson(request);
  if (!parsed.ok) return fail(parsed.status, parsed.error, parsed.message);
  const body = parsed.body;
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
