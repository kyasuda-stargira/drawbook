-- LP side: an account (one investor) has one or more member devices (a team shares the ledger).
CREATE TABLE lp_accounts (id TEXT PRIMARY KEY, label TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE lp_members (
  id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES lp_accounts(id),
  label TEXT NOT NULL, box_pk TEXT NOT NULL, sign_pk TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, revoked_at TEXT);
-- Opt-in "I hold this fund" (normalised fund name only; no figures).
CREATE TABLE lp_holdings (account_id TEXT NOT NULL, fund_norm TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (account_id, fund_norm));

-- GP side.
CREATE TABLE gp_signups (id TEXT PRIMARY KEY, firm_name TEXT NOT NULL, email TEXT NOT NULL, website TEXT NOT NULL,
  code_hash TEXT NOT NULL, tries INTEGER NOT NULL DEFAULT 0, expires_at TEXT NOT NULL, created_at TEXT NOT NULL, used_at TEXT);
CREATE TABLE gp_firms (id TEXT PRIMARY KEY, firm_name TEXT NOT NULL, email TEXT NOT NULL, website TEXT NOT NULL,
  sign_pk TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE, conduit_consent INTEGER NOT NULL DEFAULT 0,
  profile_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE gp_funds (id TEXT PRIMARY KEY, gp_id TEXT NOT NULL REFERENCES gp_firms(id), name TEXT NOT NULL,
  fund_norm TEXT NOT NULL, profile_json TEXT NOT NULL, conduit_consent INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

-- LP invites its GP; GP accepts with one of its funds -> a link.
CREATE TABLE invites (code_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL, fund_name TEXT NOT NULL,
  lp_label TEXT NOT NULL, gp_email TEXT, expires_at TEXT NOT NULL, created_at TEXT NOT NULL, used_at TEXT, link_id TEXT);
CREATE TABLE links (id TEXT PRIMARY KEY, account_id TEXT NOT NULL, gp_id TEXT NOT NULL, fund_id TEXT NOT NULL,
  gp_lp_ref TEXT, created_at TEXT NOT NULL, closed_at TEXT, UNIQUE (account_id, fund_id));

-- Notices: ciphertext in R2; one sealed content key per member in notice_keys.
CREATE TABLE notices (id TEXT PRIMARY KEY, link_id TEXT NOT NULL REFERENCES links(id), kind TEXT NOT NULL,
  size INTEGER NOT NULL, created_at TEXT NOT NULL, deleted_at TEXT);
CREATE TABLE notice_keys (notice_id TEXT NOT NULL, member_id TEXT NOT NULL, sealed_key TEXT NOT NULL, acked_at TEXT,
  PRIMARY KEY (notice_id, member_id));

CREATE TABLE rate (bucket TEXT PRIMARY KEY, n INTEGER NOT NULL, reset_at TEXT NOT NULL);
