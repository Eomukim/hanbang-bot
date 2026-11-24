/**
 * GET /api/mail/summary
 * 우측 상단 메일함 버튼의 빨간 동그라미가 필요한지 알려 준다.
 *
 * - 로그인: 안 읽은 받은 메일 수 + 아직 안 읽은 공지 수(notice_reads 기준)
 * - 게스트: 공지는 로컬 기록으로 판단하므로 최신 공지 시각(latestNoticeAt)만 내려 준다
 */
import { ok, currentSession } from '../../_lib/auth.js';
import { isAdmin } from '../../_lib/mail.js';

export async function onRequestGet({ request, env }) {
  if (!env.DB) {
    return ok({
      signedIn: false,
      unreadMailCount: 0,
      unreadNoticeCount: 0,
      latestNoticeAt: 0,
      noticeCount: 0,
      isAdmin: false,
    });
  }

  const noticeRow = await env.DB.prepare(
    'SELECT COUNT(*) AS total, MAX(created_at) AS latest FROM notices',
  ).first();
  const noticeCount = Number(noticeRow?.total || 0);
  const latestNoticeAt = Number(noticeRow?.latest || 0);

  const session = await currentSession(env, request);
  if (!session) {
    return ok({
      signedIn: false,
      unreadMailCount: 0,
      unreadNoticeCount: 0,
      latestNoticeAt,
      noticeCount,
      isAdmin: false,
    });
  }

  const mailRow = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM mails
      WHERE recipient_id = ? AND is_read = 0 AND deleted_by_recipient = 0`,
  ).bind(session.id).first();

  const noticeUnreadRow = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM notices o
      WHERE NOT EXISTS (
        SELECT 1 FROM notice_reads r WHERE r.notice_id = o.id AND r.user_id = ?
      )`,
  ).bind(session.id).first();

  return ok({
    signedIn: true,
    username: session.username,
    unreadMailCount: Number(mailRow?.n || 0),
    unreadNoticeCount: Number(noticeUnreadRow?.n || 0),
    latestNoticeAt,
    noticeCount,
    isAdmin: isAdmin(env, session.username),
  });
}
