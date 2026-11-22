-- Last time each account used the relay; accounts idle for 24 months are deleted by the daily job.
ALTER TABLE lp_accounts ADD COLUMN last_seen_at TEXT;
ALTER TABLE gp_firms ADD COLUMN last_seen_at TEXT;
UPDATE lp_accounts SET last_seen_at = created_at;
UPDATE gp_firms SET last_seen_at = created_at;
