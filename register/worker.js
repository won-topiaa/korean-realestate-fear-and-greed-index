// 데이터 API 이용 등록 창구 (Cloudflare Worker aptfeargreed-register, 주소 https://register.aptfeargreed.com/register)
// API는 키 없이 열려 있고, 누가 어떤 목적으로 쓰는지 알기 위해 등록을 받는다 (등록하지 않아도 API는 그대로 쓸 수 있음).
// 사이트 데이터 API 페이지(api/template.html)의 등록 칸이 JSON으로 보내면 D1(바인딩 이름 DB)의 registrations 표에 넣는다 (register/schema.sql).
// 고친 뒤에는 Cloudflare 대시보드 → Workers → aptfeargreed-register → 코드 편집에 이 파일을 붙여 넣고 배포한다.
const ORIGINS = ["https://aptfeargreed.com", "https://www.aptfeargreed.com"];
const PURPOSES = ["service", "research", "media", "education", "personal", "other"];
const MAX = { org: 100, name: 50, email: 120, purpose_detail: 1000, url: 300 };
const PER_DAY = 5;  // 같은 곳(IP)에서 하루에 받는 등록 수

const json = (body, status, headers) => new Response(JSON.stringify(body), { status, headers: { ...headers, "Content-Type": "application/json; charset=utf-8" } });

async function sha256(s) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("").slice(0, 24);
}

export default {
  async fetch(req, env) {
    const origin = req.headers.get("Origin") || "";
    const cors = { "Access-Control-Allow-Origin": ORIGINS.includes(origin) ? origin : ORIGINS[0], "Access-Control-Allow-Methods": "POST, OPTIONS",
                   "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400", Vary: "Origin" };
    const path = new URL(req.url).pathname;
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (path !== "/register") return new Response("아파트 공포탐욕지수 데이터 API 이용 등록 창구예요. 등록은 https://aptfeargreed.com/api/ 에서 해 주세요.\n", { headers: { "Content-Type": "text/plain; charset=utf-8" } });
    if (req.method !== "POST") return json({ ok: false, error: "POST로 보내 주세요" }, 405, cors);
    if (!ORIGINS.includes(origin)) return json({ ok: false, error: "사이트의 등록 칸에서 보내 주세요" }, 403, cors);

    let b;
    try { b = await req.json(); } catch { return json({ ok: false, error: "보낸 내용을 읽지 못했어요" }, 400, cors); }
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

    const ip = await sha256((req.headers.get("CF-Connecting-IP") || "") + "|aptfeargreed-register");
    const n = await env.DB.prepare("SELECT COUNT(*) AS n FROM registrations WHERE ip_hash = ? AND created_kst > datetime('now', '+9 hours', '-1 day')").bind(ip).first("n");
    if (n >= PER_DAY) return json({ ok: false, error: "오늘은 더 받을 수 없어요. 내일 다시 보내 주세요" }, 429, cors);
    await env.DB.prepare(`INSERT INTO registrations (created_kst, org, name, email, purpose, purpose_detail, url, commercial, ip_hash, user_agent)
                          VALUES (datetime('now', '+9 hours'), ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
      .bind(r.org, r.name, r.email, r.purpose, r.purpose_detail, r.url, r.commercial, ip, (req.headers.get("User-Agent") || "").slice(0, 200)).run();
    return json({ ok: true }, 200, cors);
  },
};
