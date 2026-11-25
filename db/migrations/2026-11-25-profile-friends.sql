-- 2026-11-25 잇다 프로필(닉네임·사진) · 친구
--
-- 이미 만들어진 표에만 적용한다. 새로 만드는 DB 는 db/schema.sql 에 같은 내용이 들어 있어
-- 이 파일이 필요 없다(칸·표가 이미 있으면 ADD COLUMN / CREATE 가 실패하므로 도구는 실패를
-- 무시하고 다음 문장으로 넘어간다).
--
-- 적용 위치: 로컬 D1(`wrangler d1 execute itda-db --local`)과
--            프로덕션 D1(`itda-db`, 8922f978-9a5d-45be-b8ce-88ba09a852c7) 대시보드 Console.

ALTER TABLE users ADD COLUMN nickname TEXT;
ALTER TABLE users ADD COLUMN avatar_data TEXT;
ALTER TABLE users ADD COLUMN avatar_updated_at INTEGER;

CREATE TABLE IF NOT EXISTS friendships (
  pair_key     TEXT PRIMARY KEY,
  requester_id TEXT NOT NULL,
  addressee_id TEXT NOT NULL,
  status       TEXT NOT NULL,
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_friendships_requester ON friendships(requester_id, status);
CREATE INDEX IF NOT EXISTS idx_friendships_addressee ON friendships(addressee_id, status);
