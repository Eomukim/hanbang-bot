-- 2026-11-25 잇다 실험실(최대 8인 커스텀 방 · 방장 신 모드) · 접속 중 표시
--
-- 이미 만들어진 표에만 적용한다. 새로 만드는 DB 는 db/schema.sql 에 같은 내용이 들어 있어
-- 이 파일이 필요 없다(칸·표가 이미 있으면 ADD COLUMN / CREATE 가 실패하므로 도구는 실패를
-- 무시하고 다음 문장으로 넘어간다).
--
-- 적용 위치: 로컬 D1(`wrangler d1 execute itda-db --local`)과
--            프로덕션 D1(`itda-db`, 8922f978-9a5d-45be-b8ce-88ba09a852c7) 대시보드 Console.

-- 접속 중(온라인) 표시: 마지막으로 잇다를 쓴 시각(epoch ms). 30초에 한 번만 갱신한다.
ALTER TABLE users ADD COLUMN last_seen_at INTEGER;

-- 실험실 방. 방 하나 = 한 행. 좌석·룰·진행 상태를 간결한 JSON 으로 모아 두어
-- 폴링 1회가 1행만 읽는다(D1 무료 일일 읽기 한도 절약).
CREATE TABLE IF NOT EXISTS lab_rooms (
  code       TEXT PRIMARY KEY,              -- 6자리 방 코드(헷갈리는 O·0·I·1 제외)
  host_id    TEXT NOT NULL,                 -- 방장(신) 사용자 id
  status     TEXT NOT NULL,                 -- 'lobby' | 'playing' | 'over'
  version    INTEGER NOT NULL DEFAULT 1,    -- 좌석·룰 변경 낙관적 락
  seats_json TEXT NOT NULL,                 -- 좌석 배열(2~8): 나·친구·봇
  rules_json TEXT NOT NULL,                 -- 제한 시간·목숨·한방·글자수·금지 글자·미션
  state_json TEXT NOT NULL,                 -- 진행 상태: 차례·점수·목숨·최근 단어
  created_at INTEGER NOT NULL,              -- epoch ms
  updated_at INTEGER NOT NULL               -- epoch ms (정리 기준)
);

CREATE INDEX IF NOT EXISTS idx_lab_rooms_host ON lab_rooms(host_id);
CREATE INDEX IF NOT EXISTS idx_lab_rooms_updated ON lab_rooms(updated_at);

-- 실험실 초대. 상대가 수락하면 지정한 자리에 착석한다.
CREATE TABLE IF NOT EXISTS lab_invites (
  id         TEXT PRIMARY KEY,
  room_code  TEXT NOT NULL,
  from_id    TEXT NOT NULL,                 -- 초대한 방장
  from_name  TEXT NOT NULL,                 -- 초대 당시 방장 이름(표시용)
  to_id      TEXT NOT NULL,                 -- 초대받은 사람
  seat       INTEGER NOT NULL,              -- 착석할 자리 번호
  status     TEXT NOT NULL,                 -- 'pending' | 'accepted' | 'declined'
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lab_invites_to ON lab_invites(to_id, status);
CREATE INDEX IF NOT EXISTS idx_lab_invites_room ON lab_invites(room_code);
