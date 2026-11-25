-- 2026-11-25 잇다 메일함 — 휴지통 · 수정
--
-- 이미 만들어진 표(mails · notices)에만 적용한다. 새로 만드는 DB 는 db/schema.sql 에
-- 같은 칸이 들어 있어 이 파일이 필요 없다(칸이 이미 있으면 ADD COLUMN 이 실패하므로
-- 도구는 실패를 무시하고 다음 문장으로 넘어간다).
--
-- 적용 위치: 로컬 D1(`wrangler d1 execute itda-db --local`)과
--            프로덕션 D1(`itda-db`) 대시보드 Console.

ALTER TABLE mails ADD COLUMN sender_trashed_at TEXT;
ALTER TABLE mails ADD COLUMN recipient_trashed_at TEXT;
ALTER TABLE mails ADD COLUMN updated_at TEXT;
ALTER TABLE notices ADD COLUMN updated_at TEXT;
