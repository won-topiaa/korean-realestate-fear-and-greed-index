// 데이터 API 이용 등록 창구 (Cloudflare Worker aptfeargreed-register, 주소 https://register.aptfeargreed.com/register)
// API는 키 없이 열려 있고, 누가 어떤 목적으로 쓰는지 알기 위해 등록을 받는다 (등록하지 않아도 API는 그대로 쓸 수 있음).
// 사이트 '데이터 사용하기' 페이지(use/template.html)의 신청 칸이 JSON으로 보내면 D1(바인딩 이름 DB)의 registrations 표에 넣는다 (register/schema.sql).
// 개인정보 (use/template.html의 안내와 같게): IP는 저장소 밖(D1 meta 표)에 무작위로 만든 값을 섞어 해시하고(이 공개 코드만으로는 되돌릴 수 없게)
// 하루 뒤 지운다. 신청은 2년 지나면 지운다 — 매일 예약 작업(트리거 Cron "0 18 * * *", 한국 시간 새벽 3시)과 신청이 들어올 때마다.
// 새 신청은 메일로도 알린다: 바인딩 MAIL(Send Email) → wontopiaaa@gmail.com (aptfeargreed.com Email Routing에서 확인한 받는 주소만 됨).
// 방문자 세기(/visit)도 여기서: 사이트 바닥글 스크립트가 페이지를 열 때마다 보내고, 누적 방문자 수를 돌려받아 바닥글에 보여 준다.
// 매주 월요일 새벽 예약 작업이 지난주 방문 요약을 같은 메일로 보낸다.
// 사이트 감시도 매일 예약 작업에서: 사이트의 status.json(site_build.py가 만듦)을 읽어 주간 소식·실거래 주간 갱신·배포·지수가 오래 안 바뀌었으면
// 같은 메일로 알린다 (GitHub 예약이 빠지거나 갱신·배포가 실패해도 GitHub 밖에서 알 수 있게). 같은 문제는 3일에 한 번, 고쳐지면 한 번.
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

// 알림 메일 (받는 주소는 NOTIFY.to 하나, Email Routing에서 확인한 주소만 됨)
async function send(env, subject, body, replyTo = "") {
  const reply = /^[\w.+-]+@[\w-]+(\.[\w-]+)+$/.test(replyTo) ? `Reply-To: ${replyTo}\r\n` : "";  // 머리글에 이상한 글자가 끼지 않게 단순한 주소만
  const raw = `From: ${word("아파트 공포탐욕지도")} <${NOTIFY.from}>\r\nTo: ${NOTIFY.to}\r\n${reply}Subject: ${word(subject)}\r\n`
    + `Date: ${new Date().toUTCString()}\r\nMessage-ID: <${crypto.randomUUID()}@aptfeargreed.com>\r\nMIME-Version: 1.0\r\n`
    + `Content-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: base64\r\n\r\n${b64(body).replace(/.{76}/g, "$&\r\n")}\r\n`;
  await env.MAIL.send(new EmailMessage(NOTIFY.from, NOTIFY.to, raw));
}

// 새 신청 알림 메일. 실패해도(받는 주소 확인 전 등) 신청은 이미 저장됨
async function notify(env, r) {
  const body = ["아파트 공포탐욕지수 데이터 사용 신청이 들어왔어요.", "",
    `회사·기관: ${r.org}`, `담당자: ${r.name || "-"}`, `이메일: ${r.email}`, `사용 목적: ${PURPOSE_KO[r.purpose]}`,
    `상업적 이용: ${r.commercial ? "예" : "아니오"}`, `서비스 주소: ${r.url || "-"}`, "", "어디에 어떻게 쓰나요:", r.purpose_detail || "-", "",
    "이 메일에 답장하면 신청한 분께 가요. 전체 목록: Cloudflare 대시보드 → D1 → aptfeargreed-api → registrations"].join("\r\n");
  await send(env, `[데이터 사용 신청] ${r.org.slice(0, 40)}`, body, r.email);
}

// ---------- 방문자 세기 ----------
// 브라우저에 저장한 무작위 번호(v)로 '처음 온 사람'과 '다른 날 다시 온 사람(재방문)'을 나눠 센다. IP·브라우저 정보는 저장하지 않는다.
// visitors: 번호별 첫 방문일·마지막 방문일·방문한 날 수 (400일 넘게 안 온 번호는 지움) · visit_days: 날짜별 방문자(first_time 처음·revisit 재방문)
// page_views: 날짜·페이지별 조회 · meta.visitors_total: 누적 방문자 (바닥글에 보여 줄 때 전체를 세지 않게 새 방문자마다 1씩)
const VISIT_TABLES = [
  "CREATE TABLE IF NOT EXISTS visitors (vid TEXT PRIMARY KEY, first_day TEXT NOT NULL, last_day TEXT NOT NULL, days INTEGER NOT NULL)",
  "CREATE TABLE IF NOT EXISTS visit_days (day TEXT PRIMARY KEY, visitors INTEGER NOT NULL DEFAULT 0, first_time INTEGER NOT NULL DEFAULT 0, revisit INTEGER NOT NULL DEFAULT 0)",
  "CREATE TABLE IF NOT EXISTS page_views (day TEXT NOT NULL, page TEXT NOT NULL, views INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, page))",
  "CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL)",
];
const kstDay = (ms = Date.now()) => new Date(ms + 9 * 3600e3).toISOString().slice(0, 10);
const total = async (db) => +((await db.prepare("SELECT v FROM meta WHERE k = 'visitors_total'").first("v")) || 0);

// 막기: 같은 IP에서 1분에 30번 넘게 오거나(IP는 이 Worker 메모리에만 잠깐 두고 저장하지 않음) 하루 새 방문자가 DAY_CAP을 넘으면
// 세지 않고 수만 돌려준다 (가짜 번호를 마구 보내 누적 수를 부풀리거나 D1 하루 쓰기 한도를 다 써서 신청까지 막지 못하게)
const RATE = { ms: 60e3, max: 30 }, DAY_CAP = 5000, hits = new Map();
function limited(ip) {
  const t = Date.now(), h = hits.get(ip);
  if (!h || t - h.t > RATE.ms) {
    if (hits.size > 5000) hits.clear();
    hits.set(ip, { t, n: 1 });
    return false;
  }
  return ++h.n > RATE.max;
}

async function visit(db, b) {
  const day = kstDay(), page = /^\/(?:[a-z-]{1,20}\/)?$/.test(b.p || "") ? b.p : "기타";  // "/", "/seoul/", "/apt/" …
  const v = /^[0-9a-f]{32}$/.test(b.v || "") ? b.v : null;  // 저장을 막아 둔 브라우저는 번호 없이 조회만 셈
  if (((await db.prepare("SELECT first_time FROM visit_days WHERE day = ?").bind(day).first("first_time")) || 0) >= DAY_CAP) return total(db);
  // 한 묶음(D1에서는 한 트랜잭션)으로: 처음 온 사람·다른 날 다시 온 사람인지는 방문자 표를 바꾸기 전에 SQL 조건으로 판단한다.
  // 중간에 실패하면 전부 되돌려, 번호만 남고 날짜별 수·누적 수가 빠지는 일이 없게. 같은 사람이 탭 두 개로 동시에 열어도 한 번만 센다
  const NEW = "NOT EXISTS (SELECT 1 FROM visitors WHERE vid = ?1)", BACK = "EXISTS (SELECT 1 FROM visitors WHERE vid = ?1 AND last_day < ?2)";
  const st = [db.prepare("INSERT INTO page_views (day, page, views) VALUES (?, ?, 1) ON CONFLICT (day, page) DO UPDATE SET views = views + 1").bind(day, page)];
  if (v) st.push(
    db.prepare(`INSERT INTO visit_days (day, visitors, first_time, revisit) SELECT ?2, 1, ${NEW}, ${BACK} WHERE ${NEW} OR ${BACK}
                ON CONFLICT (day) DO UPDATE SET visitors = visitors + 1, first_time = first_time + excluded.first_time, revisit = revisit + excluded.revisit`).bind(v, day),
    db.prepare(`INSERT INTO meta (k, v) SELECT 'visitors_total', '1' WHERE ${NEW} ON CONFLICT (k) DO UPDATE SET v = CAST(v AS INTEGER) + 1`).bind(v),
    db.prepare(`INSERT INTO visitors (vid, first_day, last_day, days) VALUES (?1, ?2, ?2, 1)
                ON CONFLICT (vid) DO UPDATE SET last_day = excluded.last_day, days = days + 1 WHERE last_day < excluded.last_day`).bind(v, day));
  await db.batch(st);
  return total(db);
}

// 지난주(월~일) 방문 요약 메일 (월요일 새벽 예약 작업)
async function weekly(env, now) {
  const db = env.DB, from = kstDay(now - 7 * 864e5), to = kstDay(now - 864e5);
  const w = await db.prepare("SELECT COALESCE(SUM(visitors), 0) AS v, COALESCE(SUM(first_time), 0) AS n, COALESCE(SUM(revisit), 0) AS r FROM visit_days WHERE day BETWEEN ? AND ?").bind(from, to).first();
  const people = await db.prepare("SELECT COUNT(*) AS c FROM visitors WHERE last_day >= ? AND first_day <= ?").bind(from, to).first("c");  // 월요일 새벽(메일 전)에 처음 온 사람은 빼고
  const loyal = await db.prepare("SELECT COUNT(*) AS c FROM visitors WHERE days >= 2").first("c");
  const pages = (await db.prepare("SELECT page, SUM(views) AS views FROM page_views WHERE day BETWEEN ? AND ? GROUP BY page ORDER BY views DESC LIMIT 12").bind(from, to).all()).results;
  const regs = await db.prepare("SELECT COUNT(*) AS c FROM registrations WHERE created_kst >= ? AND created_kst < ?").bind(from, kstDay(now)).first("c");
  const days = (await db.prepare("SELECT day, visitors, first_time, revisit FROM visit_days WHERE day BETWEEN ? AND ? ORDER BY day").bind(from, to).all()).results;
  const pct = (a, b) => (b ? Math.round((a / b) * 100) + "%" : "-");
  const body = [`아파트 공포탐욕지수 지난주 방문 요약 (${from} ~ ${to}, 한국 시간)`, "",
    `방문한 사람: ${people.toLocaleString("ko-KR")}명 (같은 사람은 한 번)`,
    `날마다 센 방문: ${w.v.toLocaleString("ko-KR")}회 — 처음 온 사람 ${w.n.toLocaleString("ko-KR")} · 다른 날 다시 온 사람 ${w.r.toLocaleString("ko-KR")} (재방문 ${pct(w.r, w.v)})`,
    `누적 방문자: ${(await total(db)).toLocaleString("ko-KR")}명 · 그중 두 번 이상 온 사람 ${loyal.toLocaleString("ko-KR")}명`,
    `데이터 사용 신청: ${regs}건`, "", "날짜별 (방문 · 새 · 재방문):", ...days.map((x) => `  ${x.day}  ${x.visitors} · ${x.first_time} · ${x.revisit}`),
    "", "페이지별 조회:", ...pages.map((x) => `  ${x.page}  ${x.views.toLocaleString("ko-KR")}`),
    "", "자세히: Cloudflare 대시보드 → D1 → aptfeargreed-api → visit_days · page_views"].join("\r\n");
  await send(env, `[주간 방문] ${from.slice(5)}~${to.slice(5)} 방문한 사람 ${people}명 · 재방문 ${pct(w.r, w.v)}`, body);
}

// 보유 기간: 신청은 2년, IP 값은 하루 제한에만 쓰니 하루, 방문자 번호는 400일 동안 안 오면 (방문 수 합계는 남음)
// 사이트 감시: 기준 날짜 = 주간 소식 호·실거래 주간 갱신은 그 주 월요일 (예비 실행이 화요일 낮까지 다시 하므로 8일 넘으면 알림)
const SITE_STATUS = "https://aptfeargreed.com/status.json";
const ACTIONS = "https://github.com/won-topiaa/korean-realestate-fear-and-greed-index/actions";
const ago = (today, d) => Math.round((Date.parse(today) - Date.parse(d)) / 864e5);  // "YYYY-MM-DD"끼리 날 수

async function watch(env, now) {
  const db = env.DB, today = kstDay(now), probs = [];  // [이름, 설명]
  let s = null;
  try {
    const r = await fetch(`${SITE_STATUS}?t=${now}`, { headers: { "Cache-Control": "no-cache" } });
    if (r.ok) s = await r.json(); else probs.push(["status", `사이트의 status.json을 못 읽음 (HTTP ${r.status})`]);
  } catch (e) {
    probs.push(["status", `사이트에 접속하지 못함 (${e.message})`]);
  }
  if (s) {
    const old = (key, label, d) => { if (d && ago(today, d.slice(0, 10)) > 8) probs.push([key, `${label}: ${d.slice(0, 10)} 이후 ${ago(today, d.slice(0, 10))}일째 그대로`]); };
    old("news", "주간 소식", s.news_issue);
    old("trades", "실거래 주간 갱신", s.trades_week);
    old("built", "사이트 배포", s.built);
    if (s.trades_result === "failed") probs.push(["trades_failed", `실거래 주간 갱신 실패 (${s.trades_week} 주, 서울·지역 모두 못 받음)`]);
    else if (s.trades_result === "partial" && s.trades_tries >= 3) probs.push(["trades_partial", `실거래 주간 갱신: ${s.trades_week} 주에 세 번 받아도 일부 달·지역이 빠짐 (그 달은 지난 자료 그대로)`]);
    const [y, m, d] = today.split("-").map(Number), want = new Date(Date.UTC(y, m - 2, 1)).toISOString().slice(0, 7);  // 20일 갱신 뒤엔 지난달 지수
    if (d >= 22 && s.index_month && s.index_month < want) probs.push(["index", `지수: ${want} 지수가 나와야 하는데 아직 ${s.index_month}`]);
  }
  const sig = probs.map((p) => p[0]).join(","), prev = JSON.parse((await db.prepare("SELECT v FROM meta WHERE k = 'watch'").first("v")) || "{}");
  let subject = null;
  if (sig && (sig !== prev.sig || ago(today, prev.day || "2000-01-01") >= 3)) subject = `[사이트 감시] 확인이 필요해요: ${probs.map((p) => p[1].split(":")[0]).join(" · ")}`;
  else if (!sig && prev.sig) subject = "[사이트 감시] 다시 정상이에요";
  if (!subject) return;
  const body = (sig ? ["아파트 공포탐욕지수 사이트의 자료가 제때 바뀌지 않았어요 (매일 새벽 3시 확인).", "", ...probs.map((p) => `- ${p[1]}`), "",
    `GitHub Actions에서 실패한 실행을 보거나 다시 돌릴 수 있어요: ${ACTIONS}`,
    "- 주간 소식·실거래: '주간 갱신' → Run workflow (끝난 일은 건너뛰고 못 한 일만 해요)",
    "- 사이트 배포: '화면만 다시 배포' → Run workflow", "- 지수: '월간 자동 갱신' → Run workflow",
    "", "같은 문제는 3일에 한 번 다시 알리고, 고쳐지면 한 번 알려 드려요."]
    : ["지난번에 알린 문제가 모두 풀렸어요.", "", `사이트 상태: 지수 ${s.index_month} · 주간 소식 ${s.news_issue} · 실거래 ${s.trades_week} · 배포 ${s.built}`]).join("\r\n");
  await send(env, subject, body);
  await db.prepare("INSERT INTO meta (k, v) VALUES ('watch', ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v").bind(JSON.stringify({ sig, day: today })).run();
}

async function cleanup(db) {
  await db.batch([
    ...VISIT_TABLES.map((s) => db.prepare(s)),  // 방문 표가 아직 없을 때도 (신청이 먼저 들어온 경우)
    db.prepare("DELETE FROM registrations WHERE created_kst < datetime('now', '+9 hours', '-2 years')"),
    db.prepare("UPDATE registrations SET ip_hash = NULL WHERE ip_hash IS NOT NULL AND created_kst < datetime('now', '+9 hours', '-1 day')"),
    db.prepare("DELETE FROM visitors WHERE last_day < date('now', '+9 hours', '-400 days')"),
  ]);
}

export default {
  async fetch(req, env, ctx) {
    const origin = req.headers.get("Origin") || "";
    const cors = { "Access-Control-Allow-Origin": ORIGINS.includes(origin) ? origin : ORIGINS[0], "Access-Control-Allow-Methods": "POST, OPTIONS",
                   "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400", Vary: "Origin" };
    const path = new URL(req.url).pathname;
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    if (path === "/visit" && req.method === "POST") {  // 바닥글 스크립트: 본문은 text/plain JSON (미리 묻는 요청 없이)
      if (!ORIGINS.includes(origin)) return json({ ok: false }, 403, cors);
      let v = {};
      try { v = JSON.parse(await req.text()) || {}; } catch {}
      const skip = v.n || typeof v.p !== "string" || limited(req.headers.get("CF-Connecting-IP") || "");
      const run = () => (skip ? total(env.DB) : visit(env.DB, v));  // n: 이 브라우저는 세지 않음 (?nocount=1, 사이트 주인용) · 주소가 없는 본문·너무 잦은 요청은 세지 않음
      let n;
      try { n = await run(); } catch (e) {
        if (!/no such table/.test(e.message)) throw e;
        await env.DB.batch(VISIT_TABLES.map((s) => env.DB.prepare(s)));  // 처음 한 번: 방문 표 만들기
        n = await run();
      }
      return json({ ok: true, total: n }, 200, cors);
    }
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

  // 매일 한 번 (대시보드 → aptfeargreed-register → 설정 → 트리거 이벤트 → Cron "0 18 * * *", 한국 시간 새벽 3시). 월요일이면 지난주 방문 요약 메일도
  async scheduled(event, env, ctx) {
    const t = event.scheduledTime, run = (name, f) => f().catch((e) => console.log(`${name} 실패:`, e.message));  // 하나가 실패해도 나머지는
    ctx.waitUntil((async () => {
      await run("정리", () => cleanup(env.DB));
      if (!env.MAIL) return;
      if (new Date(t + 9 * 3600e3).getUTCDay() === 1) await run("주간 방문 메일", () => weekly(env, t));
      await run("사이트 감시", () => watch(env, t));
    })());
  },
};
