-- 데이터 API 이용 등록 (Cloudflare D1 데이터베이스 aptfeargreed-api, register/worker.js가 씀)
-- 확인: Cloudflare 대시보드 → 저장소·데이터베이스 → D1 → aptfeargreed-api → registrations 표
CREATE TABLE IF NOT EXISTS registrations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_kst TEXT NOT NULL,          -- 등록한 때 (한국 시간)
  org TEXT NOT NULL,                  -- 회사·기관 (개인이면 '개인')
  name TEXT,                          -- 담당자 이름 (선택)
  email TEXT NOT NULL,                -- 연락받을 이메일 (형식·주소 변경 안내)
  purpose TEXT NOT NULL,              -- service · research · media · education · personal · other
  purpose_detail TEXT,                -- 쓰려는 곳·방법 (선택)
  url TEXT,                           -- 서비스 주소 (선택)
  commercial INTEGER NOT NULL,        -- 돈을 받는 서비스에 쓰는지 (1 예, 0 아니오)
  ip_hash TEXT,                       -- 같은 곳에서 하루 5번 넘게 보내지 않게 (IP를 되돌릴 수 없게 바꾼 값)
  user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_registrations_ip ON registrations (ip_hash, created_kst);
