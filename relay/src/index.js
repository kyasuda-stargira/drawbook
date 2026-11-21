// Drawbook relay. GPs send capital call and distribution notices to the LPs who invited them.
// Every notice is encrypted on the GP's machine to the LP's own keys and signed by the GP,
// so this relay stores and forwards ciphertext it cannot read or alter unnoticed.
// The only plain data it holds: account labels, GP firm and fund profiles (shared with Conduit
// only where the GP consents), invite metadata and opt-in "I hold this fund" names.

const MAX_NOTICE_BYTES = 25 * 1024 * 1024;
const CHUNK = 1000 * 1000; // D1 rows must stay under 2 MB
const INVITE_DAYS = 30;
const CODE_MINUTES = 30;
const KEEP_DAYS = 90; // ciphertext is deleted once every member has fetched it, or after this
const FREE_MAIL = new Set(["gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
  "icloud.com", "me.com", "mac.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "gmx.de", "web.de", "qq.com"]);
const DEMAND_FLOOR = 3; // demand counts below this are shown as "fewer than 3"

class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

const now = () => new Date().toISOString();
const later = (ms) => new Date(Date.now() + ms).toISOString();
const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "content-type": "application/json", "cache-control": "no-store" },
});

function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
const randomToken = (prefix) => prefix + b64url(crypto.getRandomValues(new Uint8Array(32)));
const randomId = (prefix) => prefix + b64url(crypto.getRandomValues(new Uint8Array(12)));
async function sha256(text) {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function digits6() {
  const n = crypto.getRandomValues(new Uint32Array(1))[0] % 1000000;
  return String(n).padStart(6, "0");
}

export const normFund = (s) => String(s || "").toLowerCase()
  .replace(/\b(l\.?p\.?|scsp|sca|s\.a\.r\.l\.|gmbh & co\.? kg|kg|llc|ltd|limited|fund|the)\b/g, " ")
  .replace(/[^a-z0-9]+/g, " ").trim();

function str(v, field, max = 200, required = true) {
  if (v === undefined || v === null || v === "") {
    if (required) throw new HttpError(400, `${field} is required`);
    return null;
  }
  const s = String(v).trim();
  if (s.length > max) throw new HttpError(400, `${field} is too long`);
  return s;
}
function key32(v, field) {
  const s = str(v, field, 64);
  // 32-byte keys in standard base64 (44 chars with padding)
  if (!/^[A-Za-z0-9+/]{43}=$/.test(s)) throw new HttpError(400, `${field} must be a 32-byte base64 key`);
  return s;
}
function hostOf(website) {
  let u;
  try { u = new URL(/^https?:\/\//i.test(website) ? website : `https://${website}`); } catch { throw new HttpError(400, "website is not a valid address"); }
  return u.hostname.toLowerCase().replace(/^www\./, "");
}
export function emailMatchesWebsite(email, website) {
  const m = /^[^\s@]+@([^\s@]+\.[^\s@]+)$/.exec(email);
  if (!m) return false;
  const dom = m[1].toLowerCase();
  if (FREE_MAIL.has(dom)) return false;
  const host = hostOf(website);
  return dom === host || dom.endsWith("." + host) || host.endsWith("." + dom);
}

async function body(req) {
  try { return await req.json(); } catch { throw new HttpError(400, "body must be JSON"); }
}
function bearer(req) {
  const h = req.headers.get("authorization") || "";
  const m = /^Bearer\s+(\S+)$/.exec(h);
  if (!m) throw new HttpError(401, "missing bearer token");
  return m[1];
}
async function lpMember(req, env) {
  const t = bearer(req);
  if (!t.startsWith("dbl_")) throw new HttpError(401, "not an LP token");
  const m = await env.DB.prepare("SELECT * FROM lp_members WHERE token_hash = ? AND revoked_at IS NULL").bind(await sha256(t)).first();
  if (!m) throw new HttpError(401, "unknown LP token");
  return m;
}
async function gpFirm(req, env) {
  const t = bearer(req);
  if (!t.startsWith("dbg_")) throw new HttpError(401, "not a GP key");
  const g = await env.DB.prepare("SELECT * FROM gp_firms WHERE key_hash = ?").bind(await sha256(t)).first();
  if (!g) throw new HttpError(401, "unknown GP key");
  return g;
}
async function limit(env, bucket, max, windowMs) {
  const row = await env.DB.prepare("SELECT n, reset_at FROM rate WHERE bucket = ?").bind(bucket).first();
  if (!row || row.reset_at < now()) {
    await env.DB.prepare("INSERT OR REPLACE INTO rate (bucket, n, reset_at) VALUES (?, 1, ?)").bind(bucket, later(windowMs)).run();
    return;
  }
  if (row.n >= max) throw new HttpError(429, "too many requests; try again later");
  await env.DB.prepare("UPDATE rate SET n = n + 1 WHERE bucket = ?").bind(bucket).run();
}

async function sendCode(env, email, code, firm) {
  if (env.DEV_RETURN_CODE === "1") return { dev_code: code };
  if (!env.RESEND_API_KEY) throw new HttpError(503, "email sending is not configured");
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { authorization: `Bearer ${env.RESEND_API_KEY}`, "content-type": "application/json" },
    body: JSON.stringify({
      from: env.MAIL_FROM, to: [email], subject: `Your Drawbook sign-up code: ${code}`,
      text: `Someone asked to connect ${firm} to Drawbook, so its investors can receive notices directly.\n\n` +
        `Your code is ${code}. It works for ${CODE_MINUTES} minutes.\n\nIf this was not you, ignore this email.`,
    }),
  });
  if (!r.ok) throw new HttpError(502, "could not send the code email");
  return {};
}

// ---------------- LP routes ----------------

async function lpRegister(req, env) {
  const b = await body(req);
  await limit(env, "lpreg:" + (req.headers.get("cf-connecting-ip") || "local"), 20, 3600e3);
  const account = randomId("lpa_"), member = randomId("lpm_"), token = randomToken("dbl_");
  await env.DB.batch([
    env.DB.prepare("INSERT INTO lp_accounts (id, label, created_at) VALUES (?, ?, ?)").bind(account, str(b.label, "label", 120), now()),
    env.DB.prepare("INSERT INTO lp_members (id, account_id, label, box_pk, sign_pk, token_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
      .bind(member, account, str(b.member_label || "first device", "member_label", 120), key32(b.box_pk, "box_pk"),
        key32(b.sign_pk, "sign_pk"), await sha256(token), now()),
  ]);
  return json({ account_id: account, member_id: member, token }, 201);
}

async function lpAddMember(req, env) {
  const m = await lpMember(req, env);
  const b = await body(req);
  const id = randomId("lpm_"), token = randomToken("dbl_");
  await env.DB.prepare("INSERT INTO lp_members (id, account_id, label, box_pk, sign_pk, token_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
    .bind(id, m.account_id, str(b.label, "label", 120), key32(b.box_pk, "box_pk"), key32(b.sign_pk, "sign_pk"), await sha256(token), now()).run();
  // Notices already waiting were sealed to the old member set; they stay readable by those members only.
  return json({ member_id: id, token }, 201);
}

async function lpListMembers(req, env) {
  const m = await lpMember(req, env);
  const r = await env.DB.prepare("SELECT id, label, box_pk, sign_pk, created_at, revoked_at FROM lp_members WHERE account_id = ?").bind(m.account_id).all();
  return json({ members: r.results });
}

async function lpRevokeMember(req, env, id) {
  const m = await lpMember(req, env);
  const r = await env.DB.prepare("UPDATE lp_members SET revoked_at = ? WHERE id = ? AND account_id = ? AND revoked_at IS NULL").bind(now(), id, m.account_id).run();
  if (!r.meta.changes) throw new HttpError(404, "no such member");
  return json({ ok: true });
}

async function lpInvite(req, env) {
  const m = await lpMember(req, env);
  const b = await body(req);
  await limit(env, "invite:" + m.account_id, 200, 86400e3);
  const code = randomToken("inv_");
  const fund = str(b.fund_name, "fund_name", 200);
  await env.DB.prepare("INSERT INTO invites (code_hash, account_id, fund_name, lp_label, gp_email, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
    .bind(await sha256(code), m.account_id, fund, str(b.lp_label, "lp_label", 120), str(b.gp_email, "gp_email", 320, false),
      later(INVITE_DAYS * 86400e3), now()).run();
  return json({ code, url: `${env.PUBLIC_BASE}#invite=${encodeURIComponent(code)}`, expires_in_days: INVITE_DAYS }, 201);
}

async function lpLinks(req, env) {
  const m = await lpMember(req, env);
  const r = await env.DB.prepare(
    `SELECT l.id AS link_id, l.gp_lp_ref, l.created_at, l.closed_at, f.id AS fund_id, f.name AS fund_name,
            g.id AS gp_id, g.firm_name, g.website, g.sign_pk AS gp_sign_pk
       FROM links l JOIN gp_funds f ON f.id = l.fund_id JOIN gp_firms g ON g.id = l.gp_id
      WHERE l.account_id = ?`).bind(m.account_id).all();
  return json({ links: r.results });
}

async function lpCloseLink(req, env, id) {
  const m = await lpMember(req, env);
  const r = await env.DB.prepare("UPDATE links SET closed_at = ? WHERE id = ? AND account_id = ? AND closed_at IS NULL").bind(now(), id, m.account_id).run();
  if (!r.meta.changes) throw new HttpError(404, "no such open link");
  return json({ ok: true });
}

async function lpHolding(req, env, add) {
  const m = await lpMember(req, env);
  const b = await body(req);
  const norm = normFund(str(b.fund_name, "fund_name", 200));
  if (!norm) throw new HttpError(400, "fund_name has no usable words");
  if (add) await env.DB.prepare("INSERT OR IGNORE INTO lp_holdings (account_id, fund_norm, created_at) VALUES (?, ?, ?)").bind(m.account_id, norm, now()).run();
  else await env.DB.prepare("DELETE FROM lp_holdings WHERE account_id = ? AND fund_norm = ?").bind(m.account_id, norm).run();
  return json({ ok: true, fund_norm: norm });
}

async function lpNotices(req, env) {
  const m = await lpMember(req, env);
  const r = await env.DB.prepare(
    `SELECT n.id, n.link_id, n.kind, n.size, n.created_at, k.sealed_key, f.name AS fund_name, g.id AS gp_id, g.firm_name
       FROM notice_keys k JOIN notices n ON n.id = k.notice_id JOIN links l ON l.id = n.link_id
       JOIN gp_funds f ON f.id = l.fund_id JOIN gp_firms g ON g.id = l.gp_id
      WHERE k.member_id = ? AND k.acked_at IS NULL AND n.deleted_at IS NULL ORDER BY n.created_at`).bind(m.id).all();
  return json({ notices: r.results });
}

async function memberKey(env, m, id) {
  const k = await env.DB.prepare(
    "SELECT k.* FROM notice_keys k JOIN notices n ON n.id = k.notice_id WHERE k.notice_id = ? AND k.member_id = ? AND n.deleted_at IS NULL")
    .bind(id, m.id).first();
  if (!k) throw new HttpError(404, "no such notice");
  return k;
}

async function lpBlob(req, env, id) {
  const m = await lpMember(req, env);
  await memberKey(env, m, id);
  const rows = (await env.DB.prepare("SELECT data FROM blob_chunks WHERE notice_id = ? ORDER BY seq").bind(id).all()).results;
  if (!rows.length) throw new HttpError(404, "notice content is gone");
  const parts = rows.map((r) => new Uint8Array(r.data));
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return new Response(out, { headers: { "content-type": "application/octet-stream", "cache-control": "no-store" } });
}

async function lpAck(req, env, id) {
  const m = await lpMember(req, env);
  await memberKey(env, m, id);
  await env.DB.prepare("UPDATE notice_keys SET acked_at = ? WHERE notice_id = ? AND member_id = ?").bind(now(), id, m.id).run();
  const left = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM notice_keys k JOIN lp_members mm ON mm.id = k.member_id
      WHERE k.notice_id = ? AND k.acked_at IS NULL AND mm.revoked_at IS NULL`).bind(id).first();
  if (left.n === 0) await dropNotice(env, id);
  return json({ ok: true, deleted: left.n === 0 });
}

async function dropNotice(env, id) {
  await env.DB.prepare("DELETE FROM blob_chunks WHERE notice_id = ?").bind(id).run();
  await env.DB.prepare("UPDATE notices SET deleted_at = ? WHERE id = ?").bind(now(), id).run();
}

// ---------------- GP routes ----------------

async function gpSignup(req, env) {
  const b = await body(req);
  const firm = str(b.firm_name, "firm_name", 200), email = str(b.email, "email", 320).toLowerCase(), website = str(b.website, "website", 300);
  if (!emailMatchesWebsite(email, website))
    throw new HttpError(400, "use an email address at your firm's own website domain (personal mail domains are not accepted)");
  await limit(env, "signup:" + email.split("@")[1], 5, 3600e3);
  const id = randomId("gps_"), code = digits6();
  await env.DB.prepare("INSERT INTO gp_signups (id, firm_name, email, website, code_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
    .bind(id, firm, email, website, await sha256(id + ":" + code), later(CODE_MINUTES * 60e3), now()).run();
  const extra = await sendCode(env, email, code, firm);
  return json({ signup_id: id, sent_to: email, ...extra }, 201);
}

async function gpVerify(req, env) {
  const b = await body(req);
  const s = await env.DB.prepare("SELECT * FROM gp_signups WHERE id = ?").bind(str(b.signup_id, "signup_id", 64)).first();
  if (!s || s.used_at || s.expires_at < now() || s.tries >= 5) throw new HttpError(400, "code expired or used; start the sign-up again");
  await env.DB.prepare("UPDATE gp_signups SET tries = tries + 1 WHERE id = ?").bind(s.id).run();
  if ((await sha256(s.id + ":" + str(b.code, "code", 12))) !== s.code_hash) throw new HttpError(400, "wrong code");
  const gp = randomId("gp_"), key = randomToken("dbg_");
  const profile = b.profile && typeof b.profile === "object" ? b.profile : {};
  await env.DB.batch([
    env.DB.prepare("UPDATE gp_signups SET used_at = ? WHERE id = ?").bind(now(), s.id),
    env.DB.prepare("INSERT INTO gp_firms (id, firm_name, email, website, sign_pk, key_hash, conduit_consent, profile_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
      .bind(gp, s.firm_name, s.email, s.website, key32(b.sign_pk, "sign_pk"), await sha256(key), b.conduit_consent ? 1 : 0,
        JSON.stringify(cleanProfile(profile, FIRM_FIELDS)), now()),
  ]);
  return json({ gp_id: gp, api_key: key }, 201);
}

// Manager-asserted profile fields shared with Conduit when the GP consents. Nothing else is kept.
const FIRM_FIELDS = ["legal_name", "hq_country", "sec_crd", "lei", "companies_house_number", "aum", "aum_currency",
  "aum_as_of", "strategies", "investor_relations_email", "description"];
const FUND_FIELDS = ["legal_name", "vintage", "currency", "target_size", "final_close_size", "strategy", "sub_strategy",
  "geography", "domicile", "legal_form", "lei", "register_number", "status", "first_close", "final_close",
  "fund_administrator", "auditor", "website"];
function cleanProfile(p, fields) {
  const out = {};
  for (const f of fields) {
    if (p[f] === undefined || p[f] === null || p[f] === "") continue;
    const v = Array.isArray(p[f]) ? p[f].slice(0, 20).map((x) => String(x).slice(0, 100)) : String(p[f]).slice(0, f === "description" ? 2000 : 200);
    out[f] = v;
  }
  return out;
}

async function gpMe(req, env) {
  const g = await gpFirm(req, env);
  return json({ gp_id: g.id, firm_name: g.firm_name, website: g.website, conduit_consent: !!g.conduit_consent,
    profile: JSON.parse(g.profile_json), sign_pk: g.sign_pk });
}

async function gpUpdate(req, env) {
  const g = await gpFirm(req, env);
  const b = await body(req);
  const profile = b.profile ? JSON.stringify(cleanProfile(b.profile, FIRM_FIELDS)) : g.profile_json;
  const consent = b.conduit_consent === undefined ? g.conduit_consent : (b.conduit_consent ? 1 : 0);
  await env.DB.prepare("UPDATE gp_firms SET profile_json = ?, conduit_consent = ? WHERE id = ?").bind(profile, consent, g.id).run();
  return json({ ok: true });
}

async function gpRotateKey(req, env) {
  const g = await gpFirm(req, env);
  const b = await body(req);
  const key = randomToken("dbg_");
  // A new signing key makes every linked LP's Drawbook refuse notices until the LP re-pins it (see lp_connect.py).
  await env.DB.prepare("UPDATE gp_firms SET sign_pk = ?, key_hash = ? WHERE id = ?").bind(key32(b.sign_pk, "sign_pk"), await sha256(key), g.id).run();
  return json({ api_key: key });
}

async function gpAddFund(req, env, fundId) {
  const g = await gpFirm(req, env);
  const b = await body(req);
  const name = str(b.name, "name", 200);
  const profile = JSON.stringify(cleanProfile(b.profile || {}, FUND_FIELDS));
  const consent = b.conduit_consent ? 1 : 0;
  if (fundId) {
    const r = await env.DB.prepare("UPDATE gp_funds SET name = ?, fund_norm = ?, profile_json = ?, conduit_consent = ?, updated_at = ? WHERE id = ? AND gp_id = ?")
      .bind(name, normFund(name), profile, consent, now(), fundId, g.id).run();
    if (!r.meta.changes) throw new HttpError(404, "no such fund");
    return json({ fund_id: fundId });
  }
  const id = randomId("fd_");
  await env.DB.prepare("INSERT INTO gp_funds (id, gp_id, name, fund_norm, profile_json, conduit_consent, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
    .bind(id, g.id, name, normFund(name), profile, consent, now(), now()).run();
  return json({ fund_id: id }, 201);
}

async function gpFunds(req, env) {
  const g = await gpFirm(req, env);
  const r = await env.DB.prepare("SELECT id, name, profile_json, conduit_consent FROM gp_funds WHERE gp_id = ?").bind(g.id).all();
  return json({ funds: r.results.map((f) => ({ fund_id: f.id, name: f.name, conduit_consent: !!f.conduit_consent, profile: JSON.parse(f.profile_json) })) });
}

async function gpDemand(req, env) {
  const g = await gpFirm(req, env);
  // Only for the GP's own registered funds, so nobody can probe which funds Drawbook LPs hold.
  const funds = await env.DB.prepare("SELECT id, name, fund_norm FROM gp_funds WHERE gp_id = ?").bind(g.id).all();
  const out = [];
  for (const f of funds.results) {
    const c = await env.DB.prepare("SELECT COUNT(*) AS n FROM lp_holdings WHERE fund_norm = ?").bind(f.fund_norm).first();
    const linked = await env.DB.prepare("SELECT COUNT(*) AS n FROM links WHERE fund_id = ? AND closed_at IS NULL").bind(f.id).first();
    out.push({ fund_id: f.id, name: f.name, investors_asking: c.n >= DEMAND_FLOOR ? String(c.n) : (c.n ? `fewer than ${DEMAND_FLOOR}` : "0"),
      investors_linked: linked.n });
  }
  return json({ funds: out });
}

async function inviteRow(env, code) {
  const i = await env.DB.prepare("SELECT * FROM invites WHERE code_hash = ?").bind(await sha256(code)).first();
  if (!i || i.used_at || i.expires_at < now()) throw new HttpError(404, "invite not found, used or expired");
  return i;
}

async function gpViewInvite(req, env, code) {
  await gpFirm(req, env);
  const i = await inviteRow(env, code);
  return json({ fund_name: i.fund_name, lp_label: i.lp_label, expires_at: i.expires_at });
}

async function gpAcceptInvite(req, env, code) {
  const g = await gpFirm(req, env);
  const b = await body(req);
  const i = await inviteRow(env, code);
  const f = await env.DB.prepare("SELECT id FROM gp_funds WHERE id = ? AND gp_id = ?").bind(str(b.fund_id, "fund_id", 64), g.id).first();
  if (!f) throw new HttpError(404, "no such fund for this GP");
  const existing = await env.DB.prepare("SELECT id FROM links WHERE account_id = ? AND fund_id = ?").bind(i.account_id, f.id).first();
  const link = existing ? existing.id : randomId("lk_");
  const stmts = [env.DB.prepare("UPDATE invites SET used_at = ?, link_id = ? WHERE code_hash = ?").bind(now(), link, i.code_hash)];
  if (existing) stmts.push(env.DB.prepare("UPDATE links SET closed_at = NULL, gp_lp_ref = ? WHERE id = ?").bind(str(b.gp_lp_ref, "gp_lp_ref", 120, false), link));
  else stmts.push(env.DB.prepare("INSERT INTO links (id, account_id, gp_id, fund_id, gp_lp_ref, created_at) VALUES (?, ?, ?, ?, ?, ?)")
    .bind(link, i.account_id, g.id, f.id, str(b.gp_lp_ref, "gp_lp_ref", 120, false), now()));
  await env.DB.batch(stmts);
  return json({ link_id: link, lp_label: i.lp_label }, existing ? 200 : 201);
}

async function gpLinks(req, env) {
  const g = await gpFirm(req, env);
  const links = await env.DB.prepare(
    `SELECT l.id AS link_id, l.fund_id, l.gp_lp_ref, a.label AS lp_label FROM links l JOIN lp_accounts a ON a.id = l.account_id
      WHERE l.gp_id = ? AND l.closed_at IS NULL`).bind(g.id).all();
  const out = [];
  for (const l of links.results) {
    const ms = await env.DB.prepare(
      "SELECT m.id AS member_id, m.box_pk FROM lp_members m JOIN links l ON l.account_id = m.account_id WHERE l.id = ? AND m.revoked_at IS NULL")
      .bind(l.link_id).all();
    out.push({ ...l, members: ms.results });
  }
  return json({ links: out });
}

async function gpSend(req, env) {
  const g = await gpFirm(req, env);
  const linkId = req.headers.get("x-drawbook-link") || "";
  const kind = (req.headers.get("x-drawbook-kind") || "notice").slice(0, 40);
  let keys;
  try { keys = JSON.parse(atob(req.headers.get("x-drawbook-keys") || "")); } catch { throw new HttpError(400, "x-drawbook-keys must be base64 JSON {member_id: sealed_key}"); }
  const link = await env.DB.prepare("SELECT * FROM links WHERE id = ? AND gp_id = ? AND closed_at IS NULL").bind(linkId, g.id).first();
  if (!link) throw new HttpError(404, "no such open link");
  const members = await env.DB.prepare("SELECT id FROM lp_members WHERE account_id = ? AND revoked_at IS NULL").bind(link.account_id).all();
  const want = members.results.map((m) => m.id).sort();
  const got = Object.keys(keys || {}).sort();
  if (JSON.stringify(want) !== JSON.stringify(got))
    throw new HttpError(409, "the investor's devices changed; fetch /v1/gp/links again and seal to every current member");
  const len = Number(req.headers.get("content-length") || "0");
  if (len > MAX_NOTICE_BYTES) throw new HttpError(413, "notice too large");
  const data = await req.arrayBuffer();
  if (!data.byteLength || data.byteLength > MAX_NOTICE_BYTES) throw new HttpError(413, "notice empty or too large");
  const id = randomId("nt_");
  const stmts = [];
  const bytes = new Uint8Array(data);
  for (let i = 0, seq = 0; i < bytes.length; i += CHUNK, seq++)
    stmts.push(env.DB.prepare("INSERT INTO blob_chunks (notice_id, seq, data) VALUES (?, ?, ?)").bind(id, seq, bytes.slice(i, i + CHUNK)));
  stmts.push(env.DB.prepare("INSERT INTO notices (id, link_id, kind, size, created_at) VALUES (?, ?, ?, ?, ?)").bind(id, link.id, kind, data.byteLength, now()));
  for (const mid of want) {
    const sk = String(keys[mid]);
    if (!/^[A-Za-z0-9+/=]{40,200}$/.test(sk)) throw new HttpError(400, "sealed key is not base64");
    stmts.push(env.DB.prepare("INSERT INTO notice_keys (notice_id, member_id, sealed_key) VALUES (?, ?, ?)").bind(id, mid, sk));
  }
  await env.DB.batch(stmts);
  return json({ notice_id: id, members: want.length }, 201);
}

// ---------------- Stargira (Conduit) export ----------------

async function conduitExport(req, env) {
  if (!env.ADMIN_TOKEN || bearer(req) !== env.ADMIN_TOKEN) throw new HttpError(401, "admin only");
  const firms = await env.DB.prepare("SELECT id, firm_name, website, profile_json, created_at FROM gp_firms WHERE conduit_consent = 1").all();
  const out = [];
  for (const f of firms.results) {
    const funds = await env.DB.prepare(
      `SELECT f.id, f.name, f.profile_json, f.updated_at,
              (SELECT COUNT(*) FROM links l WHERE l.fund_id = f.id AND l.closed_at IS NULL) AS investors_linked
         FROM gp_funds f WHERE f.gp_id = ? AND f.conduit_consent = 1`).bind(f.id).all();
    out.push({ gp_id: f.id, firm_name: f.firm_name, website: f.website, source: "manager-asserted via Drawbook",
      verified: "email code at website domain", joined: f.created_at, profile: JSON.parse(f.profile_json),
      funds: funds.results.map((x) => ({ fund_id: x.id, name: x.name, updated_at: x.updated_at, investors_linked: x.investors_linked,
        profile: JSON.parse(x.profile_json) })) });
  }
  return json({ exported_at: now(), firms: out });
}

// ---------------- router ----------------

const ROUTES = [
  ["POST", /^\/v1\/lp\/register$/, lpRegister],
  ["GET", /^\/v1\/lp\/members$/, lpListMembers],
  ["POST", /^\/v1\/lp\/members$/, lpAddMember],
  ["DELETE", /^\/v1\/lp\/members\/([\w-]+)$/, lpRevokeMember],
  ["POST", /^\/v1\/lp\/invites$/, lpInvite],
  ["GET", /^\/v1\/lp\/links$/, lpLinks],
  ["DELETE", /^\/v1\/lp\/links\/([\w-]+)$/, lpCloseLink],
  ["POST", /^\/v1\/lp\/holdings$/, (r, e) => lpHolding(r, e, true)],
  ["DELETE", /^\/v1\/lp\/holdings$/, (r, e) => lpHolding(r, e, false)],
  ["GET", /^\/v1\/lp\/notices$/, lpNotices],
  ["GET", /^\/v1\/lp\/notices\/([\w-]+)\/content$/, lpBlob],
  ["POST", /^\/v1\/lp\/notices\/([\w-]+)\/ack$/, lpAck],
  ["POST", /^\/v1\/gp\/signup$/, gpSignup],
  ["POST", /^\/v1\/gp\/verify$/, gpVerify],
  ["GET", /^\/v1\/gp\/me$/, gpMe],
  ["PATCH", /^\/v1\/gp\/me$/, gpUpdate],
  ["POST", /^\/v1\/gp\/keys$/, gpRotateKey],
  ["GET", /^\/v1\/gp\/funds$/, gpFunds],
  ["POST", /^\/v1\/gp\/funds$/, (r, e) => gpAddFund(r, e, null)],
  ["PUT", /^\/v1\/gp\/funds\/([\w-]+)$/, gpAddFund],
  ["GET", /^\/v1\/gp\/demand$/, gpDemand],
  ["GET", /^\/v1\/gp\/invites\/([\w-]+)$/, gpViewInvite],
  ["POST", /^\/v1\/gp\/invites\/([\w-]+)\/accept$/, gpAcceptInvite],
  ["GET", /^\/v1\/gp\/links$/, gpLinks],
  ["POST", /^\/v1\/gp\/notices$/, gpSend],
  ["GET", /^\/v1\/admin\/conduit-export$/, conduitExport],
];

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (url.pathname === "/v1/health") return json({ ok: true });
    for (const [method, re, fn] of ROUTES) {
      const m = re.exec(url.pathname);
      if (m && req.method === method) {
        try { return await fn(req, env, ...m.slice(1)); } catch (e) {
          if (e instanceof HttpError) return json({ error: e.message }, e.status);
          console.error(e);
          return json({ error: "server error" }, 500);
        }
      }
    }
    return json({ error: "not found" }, 404);
  },
  // Daily: drop ciphertext older than KEEP_DAYS, expired sign-ups and rate buckets.
  async scheduled(_event, env) {
    const cutoff = new Date(Date.now() - KEEP_DAYS * 86400e3).toISOString();
    const old = await env.DB.prepare("SELECT id FROM notices WHERE deleted_at IS NULL AND created_at < ?").bind(cutoff).all();
    for (const n of old.results) await dropNotice(env, n.id);
    await env.DB.prepare("DELETE FROM gp_signups WHERE expires_at < ?").bind(now()).run();
    await env.DB.prepare("DELETE FROM rate WHERE reset_at < ?").bind(now()).run();
  },
};
