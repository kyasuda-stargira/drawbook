# Collecting from GP portals

`drawbook collect portal <config> <folder>` logs in to one GP investor portal with your own login and downloads documents it has not collected before.

Before you use it:
- Many portals' terms of use forbid automated logins. Check the portal's terms. You run this at your own risk.
- Your password stays in the macOS Keychain: `security add-generic-password -s drawbook-example-gp -a lp@example.com -w`. Otherwise Drawbook reads `$DRAWBOOK_PORTAL_PASSWORD`. It is never printed, logged or stored.
- Drawbook never reads or generates two-step codes. When the portal asks for one, Drawbook asks you to type it.
- Add `--headed` to watch the browser.

Example config (`mygp.toml`). The selectors are CSS selectors for the portal's own page: open the login page and document list in your browser, right-click an element and choose Inspect to find them.

```toml
name = "Example GP"
login_url = "https://investors.example-gp.com/login"
username = "lp@example.com"
keychain_service = "drawbook-example-gp"
download_dir = "~/LP-notices/inbox"
# documents_url = "/documents"              # only if the list is not the landing page

[selectors]
username_selector = "#email"
password_selector = "#password"
submit_selector = "button[type=submit]"
code_selector = "input[name=otp]"           # leave out if there is no two-step sign-in
code_submit_selector = "#verify"
error_selector = ".alert-error"
row_selector = "table.documents tr.doc"
link_selector = "a.download"
title_selector = ".title"
date_selector = ".date"
next_selector = "a.next"
```

A portal whose files download only through a script button (no plain link) needs a small `Adapter` subclass in Python. See `src/drawbook/collect/portal.py`.

Tested only against a local mock portal (`tests/mock_portal.py`). No real GP portal has been tried yet.
