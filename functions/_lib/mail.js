/**
 * 잇다 메일함 공용 도우미.
 *
 * - 메일(쪽지): 로그인한 플레이어끼리 주고받는 짧은 편지. 답장은 reply_to_id 로 원본을 가리킨다.
 * - 공지사항: 관리자(Cloudflare Pages 환경변수 `ADMIN_USERNAMES`)만 쓰고 지울 수 있고,
 *   누구나(게스트 포함) 읽는다.
 * - 읽음: 받은 메일은 mails.is_read/read_at, 공지는 사용자별 notice_reads 표로 기억한다.
 * - 휴지통: `삭제`는 내 쪽 `*_trashed_at`(ISO)만 기록하고, 휴지통에서 `완전 삭제`할 때
 *   비로소 `deleted_by_*` 를 세운다(양쪽 다 지우면 행 삭제). 각자 독립이다.
 * - 수정: 보낸 사람만 `updated_at`(ISO)과 제목·본문을 바꿀 수 있고, 관리자는 공지를 고친다.
 *
 * 보안 규칙: 이 파일을 포함한 모든 메일 API 는 D1 에 `.prepare(...).bind(...)` 만 쓴다.
 * 값이 SQL 문자열에 직접 들어가는 곳은 없다.
 */

/** 제목·본문 길이 상한(화면 입력 칸의 maxlength 와 같은 값). */
export const SUBJECT_MAX = 80;
export const BODY_MAX = 2000;
export const NOTICE_TITLE_MAX = 100;
export const NOTICE_BODY_MAX = 5000;

/** 한 번에 내려 주는 목록 크기. */
export const LIST_LIMIT = 100;

/** 공지 작성 권한이 있는 아이디 목록(환경변수 ADMIN_USERNAMES, 쉼표 구분). */
export function adminUsernames(env) {
  return String(env?.ADMIN_USERNAMES || '')
    .split(',')
    .map((name) => name.trim().replace(/^@/, ''))
    .filter(Boolean);
}

/** 지금 로그인한 아이디가 관리자인가. 대소문자는 구분하지 않는다. */
export function isAdmin(env, username) {
  if (!username) return false;
  const wanted = String(username).toLowerCase();
  return adminUsernames(env).some((name) => name.toLowerCase() === wanted);
}

export function newMailId() {
  return `m_${crypto.randomUUID().replace(/-/g, '')}`;
}

export function newNoticeId() {
  return `n_${crypto.randomUUID().replace(/-/g, '')}`;
}

/** 줄바꿈은 살리고 앞뒤 공백만 정리한다. */
function cleanText(raw, max) {
  return String(raw ?? '').replace(/\r\n?/g, '\n').trim().slice(0, max);
}

/** 받는 사람 표기: `@아이디` 와 `아이디` 를 모두 받는다. */
export function parseRecipient(raw) {
  return String(raw ?? '').trim().replace(/^@/, '').trim();
}

export function validateMail({ to, subject, body }) {
  const recipient = parseRecipient(to);
  if (!recipient) {
    return { ok: false, error: 'recipient_required', message: '받는 사람 아이디를 입력해 주세요.' };
  }
  if (recipient.length > 12 || !/^[가-힣a-zA-Z0-9_]{2,12}$/u.test(recipient)) {
    return { ok: false, error: 'recipient_invalid', message: '아이디는 2~12자의 한글·영문·숫자·밑줄로 적어 주세요.' };
  }
  const title = cleanText(subject, SUBJECT_MAX + 1);
  if (!title) {
    return { ok: false, error: 'subject_required', message: '제목을 입력해 주세요.' };
  }
  if (title.length > SUBJECT_MAX) {
    return { ok: false, error: 'subject_long', message: `제목은 ${SUBJECT_MAX}자까지 쓸 수 있어요.` };
  }
  const text = cleanText(body, BODY_MAX + 1);
  if (!text) {
    return { ok: false, error: 'body_required', message: '내용을 입력해 주세요.' };
  }
  if (text.length > BODY_MAX) {
    return { ok: false, error: 'body_long', message: `내용은 ${BODY_MAX}자까지 쓸 수 있어요.` };
  }
  return { ok: true, recipient, subject: title, body: text };
}

/**
 * 보낸 메일 수정 입력 검사(받는 사람은 바꾸지 않는다).
 * 발송(`validateMail`)과 같은 제목 80자·본문 2000자 상한을 쓴다.
 */
export function validateMailEdit({ subject, body }) {
  const title = cleanText(subject, SUBJECT_MAX + 1);
  if (!title) {
    return { ok: false, error: 'subject_required', message: '제목을 입력해 주세요.' };
  }
  if (title.length > SUBJECT_MAX) {
    return { ok: false, error: 'subject_long', message: `제목은 ${SUBJECT_MAX}자까지 쓸 수 있어요.` };
  }
  const text = cleanText(body, BODY_MAX + 1);
  if (!text) {
    return { ok: false, error: 'body_required', message: '내용을 입력해 주세요.' };
  }
  if (text.length > BODY_MAX) {
    return { ok: false, error: 'body_long', message: `내용은 ${BODY_MAX}자까지 쓸 수 있어요.` };
  }
  return { ok: true, subject: title, body: text };
}

/** ISO 문자열(또는 비어 있는 값)을 epoch ms 로. 값이 없거나 이상하면 null. */
export function stampToMs(raw) {
  if (raw == null || raw === '') return null;
  const ms = Date.parse(String(raw));
  return Number.isFinite(ms) ? ms : null;
}

/** 지금 시각을 DB 에 남기는 ISO 문자열로. */
export function nowStamp() {
  return new Date().toISOString();
}

export function validateNotice({ title, body }) {
  const heading = cleanText(title, NOTICE_TITLE_MAX + 1);
  if (!heading) {
    return { ok: false, error: 'title_required', message: '공지 제목을 입력해 주세요.' };
  }
  if (heading.length > NOTICE_TITLE_MAX) {
    return { ok: false, error: 'title_long', message: `공지 제목은 ${NOTICE_TITLE_MAX}자까지 쓸 수 있어요.` };
  }
  const text = cleanText(body, NOTICE_BODY_MAX + 1);
  if (!text) {
    return { ok: false, error: 'body_required', message: '공지 내용을 입력해 주세요.' };
  }
  if (text.length > NOTICE_BODY_MAX) {
    return { ok: false, error: 'body_long', message: `공지 내용은 ${NOTICE_BODY_MAX}자까지 쓸 수 있어요.` };
  }
  return { ok: true, title: heading, body: text };
}

/** 메일 행 → 화면이 쓰는 모양. 보낸·받은·휴지통 목록과 메일 상세가 같은 모양을 쓴다.
 *  목록 쿼리가 `users` 를 붙여 주면 닉네임·사진 시각이 함께 오고, 없으면 아이디로만 보인다.
 *  (`sender_username` 은 보낸 때의 아이디 스냅숏이라, 닉네임을 바꿔도 그대로 남는다.) */
export function mailView(row) {
  if (!row) return null;
  return {
    id: row.id,
    senderUsername: row.sender_username,
    senderNickname: row.sender_nickname || '',
    senderDisplayName: row.sender_nickname || row.sender_display_name || row.sender_username,
    senderAvatarAt: Number(row.sender_avatar_at || 0),
    recipientUsername: row.recipient_username,
    recipientNickname: row.recipient_nickname || '',
    recipientDisplayName: row.recipient_nickname || row.recipient_display_name || row.recipient_username,
    recipientAvatarAt: Number(row.recipient_avatar_at || 0),
    replyToId: row.reply_to_id || null,
    subject: row.subject,
    body: row.body,
    isRead: Number(row.is_read) === 1,
    readAt: row.read_at == null ? null : Number(row.read_at),
    createdAt: Number(row.created_at),
    updatedAt: stampToMs(row.updated_at),
    // 휴지통 목록에서만 채워지는 값(받은/보낸 구분과 휴지통에 넣은 시각)
    folder: row.folder || null,
    trashedAt: stampToMs(row.trashed_at),
  };
}

export function noticeView(row) {
  if (!row) return null;
  return {
    id: row.id,
    authorUsername: row.author_username,
    title: row.title,
    body: row.body,
    isRead: Number(row.is_read) === 1,
    createdAt: Number(row.created_at),
    updatedAt: stampToMs(row.updated_at),
  };
}

/** 목록 항목 하나의 식별자를 검사한다. 이상하면 ''. */
export function parseId(raw, prefix) {
  const id = String(raw ?? '').trim();
  if (!id || id.length > 64) return '';
  if (prefix && !id.startsWith(prefix)) return '';
  return /^[a-z]_[0-9a-zA-Z]+$/.test(id) ? id : '';
}
