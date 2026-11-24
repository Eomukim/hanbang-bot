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
  key          TEXT PRIMARY KEY,                -- 'register:1.2.3.4' 처럼 경로:IP
  count        INTEGER NOT NULL DEFAULT 0,
  window_start INTEGER NOT NULL                 -- epoch 초
);
