// 데이터 API 이용 등록 창구 (Cloudflare Worker aptfeargreed-register, 주소 https://register.aptfeargreed.com/register)
// API는 키 없이 열려 있고, 누가 어떤 목적으로 쓰는지 알기 위해 등록을 받는다 (등록하지 않아도 API는 그대로 쓸 수 있음).
// 사이트 '데이터 사용하기' 페이지(use/template.html)의 신청 칸이 JSON으로 보내면 D1(바인딩 이름 DB)의 registrations 표에 넣는다 (register/schema.sql).
// 개인정보 (use/template.html의 안내와 같게): IP는 저장소 밖(D1 meta 표)에 무작위로 만든 값을 섞어 해시하고(이 공개 코드만으로는 되돌릴 수 없게)
// 하루 뒤 지운다. 신청은 2년 지나면 지운다 — 매일 예약 작업(트리거 Cron "0 18 * * *", 한국 시간 새벽 3시)과 신청이 들어올 때마다.
// 새 신청은 메일로도 알린다: 바인딩 MAIL(Send Email) → wontopiaaa@gmail.com (aptfeargreed.com Email Routing에서 확인한 받는 주소만 됨).
// 고친 뒤에는 Cloudflare 대시보드 → Workers → aptfeargreed-register → 코드 편집에 이 파일을 붙여 넣고 배포한다.
import { EmailMessage } from "cloudflare:email";

const ORIGINS = ["https://aptfeargreed.com", "https://www.aptfeargreed.com"];
const PURPOSES = ["service", "research", "media", "education", "personal", "other"];
const MAX = { org: 100, name: 50, email: 120, purpose_detail: 1000, url: 300 };
const PER_DAY = 5;  // 같은 곳(IP)에서 하루에 받는 등록 수 (알림 메일도 그만큼만)
const NOTIFY = { from: "register@aptfeargreed.com", to: "wontopiaaa@gmail.com" };
const PURPOSE_KO = { service: "서비스·앱에 점수 보여 주기", research: "리서치·투자 분석", media: "언론·콘텐츠", education: "교육·학술 연구", personal: "개인 공부·취미", other: "기타" };

const json = (body, status, headers) => new Response(JSON.stringify(body), { status, headers: { ...headers, "Content-Type": "application/json; charset=utf-8" } });

async function sha256(s) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("").slice(0, 24);
}

// IP에 섞는 값: 처음 한 번 D1이 무작위로 만들어 meta 표에 둔다 (예전엔 이 코드에 적힌 고정값이라, IPv4를 다 해시해 보면 원래 IP가 나왔음)
async function salt(db) {
  await db.batch([
    db.prepare("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)"),
    db.prepare("INSERT OR IGNORE INTO meta (k, v) VALUES ('ip_salt', lower(hex(randomblob(32))))"),
  ]);
  return db.prepare("SELECT v FROM meta WHERE k = 'ip_salt'").first("v");
}

const b64 = (s) => { let t = ""; for (const x of new TextEncoder().encode(s)) t += String.fromCharCode(x); return btoa(t); };
// 메일 머리글의 한글: 45바이트씩 끊은 =?UTF-8?B?…?= 여러 개 (한 조각 75자 제한)
function word(s) {
  const out = [""];
  for (const ch of s) {
    if (new TextEncoder().encode(out[out.length - 1] + ch).length > 45) out.push("");
    out[out.length - 1] += ch;
  }
  return out.map((x) => `=?UTF-8?B?${b64(x)}?=`).join("\r\n ");
}

// 새 신청 알림 메일. 실패해도(받는 주소 확인 전 등) 신청은 이미 저장됨
async function notify(env, r) {
  const body = ["아파트 공포탐욕지수 데이터 사용 신청이 들어왔어요.", "",
    `회사·기관: ${r.org}`, `담당자: ${r.name || "-"}`, `이메일: ${r.email}`, `사용 목적: ${PURPOSE_KO[r.purpose]}`,
    `상업적 이용: ${r.commercial ? "예" : "아니오"}`, `서비스 주소: ${r.url || "-"}`, "", "어디에 어떻게 쓰나요:", r.purpose_detail || "-", "",
    "이 메일에 답장하면 신청한 분께 가요. 전체 목록: Cloudflare 대시보드 → D1 → aptfeargreed-api → registrations"].join("\r\n");
  const reply = /^[\w.+-]+@[\w-]+(\.[\w-]+)+$/.test(r.email) ? `Reply-To: ${r.email}\r\n` : "";  // 머리글에 이상한 글자가 끼지 않게 단순한 주소만
  const raw = `From: ${word("아파트 공포탐욕지도")} <${NOTIFY.from}>\r\nTo: ${NOTIFY.to}\r\n${reply}Subject: ${word(`[데이터 사용 신청] ${r.org.slice(0, 40)}`)}\r\n`
    + `Date: ${new Date().toUTCString()}\r\nMessage-ID: <${crypto.randomUUID()}@aptfeargreed.com>\r\nMIME-Version: 1.0\r\n`
    + `Content-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: base64\r\n\r\n${b64(body).replace(/.{76}/g, "$&\r\n")}\r\n`;
  await env.MAIL.send(new EmailMessage(NOTIFY.from, NOTIFY.to, raw));
}

// 보유 기간: 신청은 2년, IP 값은 하루 제한에만 쓰니 하루
async function cleanup(db) {
  await db.batch([
    db.prepare("DELETE FROM registrations WHERE created_kst < datetime('now', '+9 hours', '-2 years')"),
    db.prepare("UPDATE registrations SET ip_hash = NULL WHERE ip_hash IS NOT NULL AND created_kst < datetime('now', '+9 hours', '-1 day')"),
  ]);
}

export default {
  async fetch(req, env, ctx) {
    const origin = req.headers.get("Origin") || "";
    const cors = { "Access-Control-Allow-Origin": ORIGINS.includes(origin) ? origin : ORIGINS[0], "Access-Control-Allow-Methods": "POST, OPTIONS",
                   "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400", Vary: "Origin" };
    const path = new URL(req.url).pathname;
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (path !== "/register") return new Response("아파트 공포탐욕지수 데이터 API 이용 등록 창구예요. 신청은 https://aptfeargreed.com/use/ 에서 해 주세요.\n", { headers: { "Content-Type": "text/plain; charset=utf-8" } });
    if (req.method !== "POST") return json({ ok: false, error: "POST로 보내 주세요" }, 405, cors);
    if (!ORIGINS.includes(origin)) return json({ ok: false, error: "사이트의 신청 칸에서 보내 주세요" }, 403, cors);

    let b = null;
    try { b = await req.json(); } catch {}
    if (!b || typeof b !== "object" || Array.isArray(b)) return json({ ok: false, error: "보낸 내용을 읽지 못했어요" }, 400, cors);  // null·배열도 (예전엔 null에 오류로 멈췄음)
    if (b.website) return json({ ok: true }, 200, cors);  // 사람에게는 안 보이는 칸: 채워져 있으면 자동 프로그램이라 조용히 버림
    const s = (k) => String(b[k] ?? "").replace(/\s+/g, " ").trim().slice(0, MAX[k]);
    const r = { org: s("org"), name: s("name"), email: s("email").toLowerCase(), purpose: PURPOSES.includes(b.purpose) ? b.purpose : "",
                purpose_detail: String(b.purpose_detail ?? "").trim().slice(0, MAX.purpose_detail), url: s("url"), commercial: b.commercial === "yes" ? 1 : 0 };
    const bad = [];
    if (!r.org) bad.push("회사·기관");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(r.email)) bad.push("이메일");
    if (!r.purpose) bad.push("사용 목적");
    if (!["yes", "no"].includes(b.commercial)) bad.push("상업적 이용 여부");
    if (b.agree !== true) bad.push("개인정보 수집·이용 동의");
    if (bad.length) return json({ ok: false, error: `다음 칸을 확인해 주세요: ${bad.join(", ")}` }, 400, cors);

    await cleanup(env.DB);  // 예약 작업이 꺼져 있어도 보유 기간이 지켜지게
    const ip = await sha256(`${await salt(env.DB)}|${req.headers.get("CF-Connecting-IP") || ""}`);
    const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM registrations WHERE ip_hash = ? AND created_kst > datetime('now', '+9 hours', '-1 day')").bind(ip).first("n");
    if (n >= PER_DAY) return json({ ok: false, error: "오늘은 더 받을 수 없어요. 내일 다시 보내 주세요" }, 429, cors);
    await env.DB.prepare(`INSERT INTO registrations (created_kst, org, name, email, purpose, purpose_detail, url, commercial, ip_hash, user_agent)
                          VALUES (datetime('now', '+9 hours'), ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(r.org, r.name, r.email, r.purpose, r.purpose_detail, r.url, r.commercial, ip, (req.headers.get("User-Agent") || "").slice(0, 200)).run();
    if (env.MAIL) ctx.waitUntil(notify(env, r).catch((e) => console.log("알림 메일 실패:", e.message)));  // 답은 기다리지 않고 바로
    return json({ ok: true }, 200, cors);
  },

  // 매일 한 번 (대시보드 → aptfeargreed-register → 설정 → 트리거 이벤트 → Cron "0 18 * * *")
  async scheduled(event, env, ctx) {
    ctx.waitUntil(cleanup(env.DB));
  },
};
