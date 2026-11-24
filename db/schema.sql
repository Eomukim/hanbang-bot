-- 잇다 계정 DB (Cloudflare D1 `itda-db`) 스키마
-- 대시보드 D1 콘솔에 아래 문장을 하나씩 실행했고, 이 파일은 같은 내용의 기록이다.

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,          -- 화면에 보이는 아이디(닉네임)
  password_hash TEXT,                           -- pbkdf2-sha256$반복$salt$hash · 구글 전용 계정은 NULL
  google_sub    TEXT UNIQUE,                    -- 구글 계정 고유 ID · 아이디/비번 계정은 NULL
  display_name  TEXT,                           -- 구글 이름 등 표시용 이름
  stats_json    TEXT NOT NULL DEFAULT '{}',     -- 개인 전적·설정 동기화용 경량 JSON(랭킹 UI 없음)
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,                  -- 세션 토큰의 SHA-256(원문은 쿠키에만)
  user_id    TEXT NOT NULL,
  expires_at INTEGER NOT NULL,                  -- epoch ms
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS auth_throttle (
  key          TEXT PRIMARY KEY,                -- 'register:1.2.3.4' 처럼 경로:IP(또는 사용자)
  count        INTEGER NOT NULL DEFAULT 0,
  window_start INTEGER NOT NULL                 -- epoch 초
);

-- ── 메일함 ────────────────────────────────────────────────────
-- 플레이어끼리 주고받는 쪽지. 한쪽이 지워도 상대 메일함은 남도록
-- deleted_by_sender / deleted_by_recipient 를 따로 둔다(양쪽 다 지우면 행 삭제).
CREATE TABLE IF NOT EXISTS mails (
  id                   TEXT PRIMARY KEY,
  sender_id            TEXT NOT NULL,
  sender_username      TEXT NOT NULL,           -- 보낸 때의 아이디(탈퇴 뒤에도 표시가 남도록)
  recipient_id         TEXT NOT NULL,
  recipient_username   TEXT NOT NULL,
  reply_to_id          TEXT,                    -- 답장이면 원본 메일 id
  subject              TEXT NOT NULL,
  body                 TEXT NOT NULL,
  is_read              INTEGER NOT NULL DEFAULT 0,
  read_at              INTEGER,
  deleted_by_sender    INTEGER NOT NULL DEFAULT 0,
  deleted_by_recipient INTEGER NOT NULL DEFAULT 0,
  created_at           INTEGER NOT NULL         -- epoch ms
);

CREATE INDEX IF NOT EXISTS idx_mails_recipient ON mails(recipient_id, created_at);
CREATE INDEX IF NOT EXISTS idx_mails_sender ON mails(sender_id, created_at);

-- 공지사항: 관리자(ADMIN_USERNAMES)만 쓰고 지운다. 누구나 읽는다.
CREATE TABLE IF NOT EXISTS notices (
  id              TEXT PRIMARY KEY,
  author_username TEXT NOT NULL,
  title           TEXT NOT NULL,
  body            TEXT NOT NULL,
  created_at      INTEGER NOT NULL              -- epoch ms
);

CREATE INDEX IF NOT EXISTS idx_notices_created ON notices(created_at);

-- 사용자별 공지 읽음. 기기가 바뀌어도 빨간 동그라미가 다시 뜨지 않게 한다.
CREATE TABLE IF NOT EXISTS notice_reads (
  user_id   TEXT NOT NULL,
  notice_id TEXT NOT NULL,
  read_at   INTEGER NOT NULL,
  PRIMARY KEY (user_id, notice_id)
);
