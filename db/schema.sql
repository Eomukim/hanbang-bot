-- 잇다 계정 DB (Cloudflare D1 `itda-db`) 스키마
-- 대시보드 D1 콘솔에 아래 문장을 하나씩 실행했고, 이 파일은 같은 내용의 기록이다.

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,          -- 로그인·검색에 쓰는 고유 아이디(@아이디)
  password_hash TEXT,                           -- pbkdf2-sha256$반복$salt$hash · 구글 전용 계정은 NULL
  google_sub    TEXT UNIQUE,                    -- 구글 계정 고유 ID · 아이디/비번 계정은 NULL
  display_name  TEXT,                           -- 구글 이름 등 표시용 이름
  nickname      TEXT,                           -- 사용자가 정한 닉네임(1~16자) · 없으면 표시용 이름·아이디
  avatar_data   TEXT,                           -- 프로필 사진(160px 정사각 WebP/JPEG Data URL) · 없으면 글자 아바타
  avatar_updated_at INTEGER,                    -- 사진을 마지막으로 바꾼 시각(epoch ms) · 주소의 ?v= 캐시 키
  stats_json    TEXT NOT NULL DEFAULT '{}',     -- 개인 전적·설정 동기화용 경량 JSON(랭킹 UI 없음)
  last_seen_at  INTEGER,                        -- 마지막 활동 시각(epoch ms) · 90초 안이면 접속 중
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
-- 2026-11-25: 삭제는 먼저 휴지통(sender_trashed_at·recipient_trashed_at)으로 옮기고,
-- 휴지통에서 완전 삭제할 때만 deleted_by_* 를 세운다. 기존 DB 는 db/migrations/ 참고.
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
  sender_trashed_at    TEXT,                    -- 보낸 사람이 휴지통으로 옮긴 시각(ISO). NULL 이면 내 함에 있음
  recipient_trashed_at TEXT,                    -- 받는 사람이 휴지통으로 옮긴 시각(ISO)
  updated_at           TEXT,                    -- 수정한 시각(ISO). NULL 이면 수정한 적 없음
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
  updated_at      TEXT,                         -- 수정한 시각(ISO). NULL 이면 수정한 적 없음
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

-- ── 친구 ─────────────────────────────────────────────────────
-- 두 사람 사이의 한 행. `pending`(요청 보냄) → `accepted`(친구).
-- 요청한 쪽이 requester_id, 받은 쪽이 addressee_id 다. pair_key 는 두 id 를 정렬해 이은 값이라
-- 방향이 엇갈린 두 요청이 들어와도 한 쌍에 한 행만 남는다(UNIQUE).
-- 거절·요청 취소·친구 삭제는 행을 지운다(나중에 다시 요청할 수 있다).
CREATE TABLE IF NOT EXISTS friendships (
  pair_key     TEXT PRIMARY KEY,                -- 정렬한 두 사용자 id(예: u_a...|u_b...)
  requester_id TEXT NOT NULL,                   -- 요청을 보낸 사람
  addressee_id TEXT NOT NULL,                   -- 요청을 받은 사람
  status       TEXT NOT NULL,                   -- 'pending' | 'accepted'
  created_at   INTEGER NOT NULL,                -- epoch ms
  updated_at   INTEGER NOT NULL                 -- 수락·재요청 시각(epoch ms)
);

CREATE INDEX IF NOT EXISTS idx_friendships_requester ON friendships(requester_id, status);
CREATE INDEX IF NOT EXISTS idx_friendships_addressee ON friendships(addressee_id, status);

-- ── 실험실 (최대 8인 커스텀 방 · 방장 = 신 모드) ─────────────
-- 방 하나 = 한 행. 좌석·룰·진행 상태를 JSON 으로 모아 두어 폴링 1회가 1행만 읽는다.
-- 전적·랭킹·엽전은 이 방에서 쌓지 않는다.
CREATE TABLE IF NOT EXISTS lab_rooms (
  code       TEXT PRIMARY KEY,              -- 6자리 방 코드(O·0·I·1 제외)
  host_id    TEXT NOT NULL,
  status     TEXT NOT NULL,                 -- 'lobby' | 'playing' | 'over'
  version    INTEGER NOT NULL DEFAULT 1,    -- 낙관적 락
  seats_json TEXT NOT NULL,
  rules_json TEXT NOT NULL,
  state_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lab_rooms_host ON lab_rooms(host_id);
CREATE INDEX IF NOT EXISTS idx_lab_rooms_updated ON lab_rooms(updated_at);

CREATE TABLE IF NOT EXISTS lab_invites (
  id         TEXT PRIMARY KEY,
  room_code  TEXT NOT NULL,
  from_id    TEXT NOT NULL,
  from_name  TEXT NOT NULL,
  to_id      TEXT NOT NULL,
  seat       INTEGER NOT NULL,
  status     TEXT NOT NULL,                 -- 'pending' | 'accepted' | 'declined'
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lab_invites_to ON lab_invites(to_id, status);
CREATE INDEX IF NOT EXISTS idx_lab_invites_room ON lab_invites(room_code);
