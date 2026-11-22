# Drawbook GP API

GPs and fund administrators use this API to send capital call notices, distribution notices and capital account statements straight to the investors who asked for them. It is free.

**What Stargira can and cannot see.** Each notice is encrypted on the GP's own machine to the investor's own device keys, and signed with the GP's own key. The relay that Stargira runs stores the encrypted file and passes it on. It cannot read the notice. It cannot change one without the investor's Drawbook rejecting it. Stargira does see your firm's name, website and the fund names you register. It sees the fund and firm facts you choose to share; those appear in the Conduit directory only if you tick consent, labelled "manager-asserted".

Words used here:
- **Relay:** the Stargira service in the middle, at `https://drawbook-relay.kyasuda-183.workers.dev`. It holds encrypted files only. The `drawbook-gp` command uses it by default; set `DRAWBOOK_RELAY` or `--relay` to use another.
- **Link:** one investor's account joined to one of your funds. An investor creates it by sending you an invite.
- **Device (member):** one computer in the investor's team. A notice is sealed to every device on the account.
- **Fingerprint:** a short code that identifies your signing key. Investors check it with you by phone, as they would check bank details.

## The quick way: the `drawbook-gp` command

```bash
pip install drawbook-lp
```

```bash
drawbook-gp signup --firm "Example Capital" --email ir@example-capital.com --website example-capital.com
```

The email address must be at your website's domain; personal mail domains are refused. You get a 6-digit code by email (valid 30 minutes, 5 tries).

```bash
drawbook-gp verify <signup_id> <code> --profile firm.json --conduit
```

This prints your signing-key fingerprint. Keep `~/.drawbook-gp/gp.json` safe: it holds your API key and signing key.

```bash
drawbook-gp fund "Example Growth Fund I" --profile fund.json --conduit
```

```bash
drawbook-gp accept <invite code> --fund-id <fund_id> --lp-ref "your own investor id"
```

```bash
drawbook-gp send <link_id> notice.pdf ilpa-template.xlsx --kind capital_call
```

`drawbook-gp delete` deletes your firm on the relay, with its funds, investor links and notices not yet fetched, and removes `gp.json` from your computer. It asks you to type `delete` first.

`drawbook-gp funds` shows, for each of your funds, how many investors are linked and how many have said they want that fund's notices through Drawbook ("fewer than 3" below three, so no single investor stands out).

Kinds: `capital_call`, `distribution`, `combined`, `capital_account_statement`, `other`. You may send the PDF, ILPA's 2025 Capital Call & Distribution Template (.xlsx), and/or a `<name>.drawbook.json` file holding the notice in Drawbook's own schema (`drawbook.schema.Notice`). Structured files are read exactly, with no AI reading.

## Profile fields (shared with Conduit only with consent)

Any other field is dropped.

- **Firm:** legal_name, hq_country, sec_crd, lei, companies_house_number, aum, aum_currency, aum_as_of, strategies (list), investor_relations_email, description
- **Fund:** legal_name, vintage, currency, target_size, final_close_size, strategy, sub_strategy, geography, domicile, legal_form, lei, register_number, status, first_close, final_close, fund_administrator, auditor, website

## The HTTP API (for fund administration systems)

Every call uses JSON over HTTPS. After sign-up, send `Authorization: Bearer <api_key>` (GP keys start `dbg_`).

| Method and path | Body | Returns |
|---|---|---|
| `POST /v1/gp/signup` | firm_name, email, website | signup_id (code is emailed) |
| `POST /v1/gp/verify` | signup_id, code, sign_pk, profile, conduit_consent | gp_id, api_key |
| `GET /v1/gp/me`, `PATCH /v1/gp/me` | profile, conduit_consent | firm record |
| `DELETE /v1/gp/me` | confirm (your gp_id) | deletes the firm, funds, links and waiting notices |
| `POST /v1/gp/keys` | sign_pk | new api_key (investors must re-confirm the fingerprint) |
| `GET /v1/gp/funds`, `POST /v1/gp/funds`, `PUT /v1/gp/funds/{id}` | name, profile, conduit_consent | fund_id |
| `GET /v1/gp/demand` | | per fund: investors_asking, investors_linked |
| `GET /v1/gp/invites/{code}` | | fund_name, lp_label |
| `POST /v1/gp/invites/{code}/accept` | fund_id, gp_lp_ref | link_id |
| `GET /v1/gp/links` | | per link: link_id, fund_id, lp_label, gp_lp_ref, members [{member_id, box_pk}] |
| `POST /v1/gp/notices` | raw ciphertext (headers below) | notice_id |

### Sealing a notice (any language with libsodium)

1. Build a manifest: `{"v":1, "link_id", "gp_id", "fund_id", "kind", "created_at" (ISO 8601), "files": [{"name", "sha256" (hex), "data" (base64)}]}`.
2. Sign the canonical manifest (JSON with sorted keys, no spaces, UTF-8) with your Ed25519 key: `sig = crypto_sign_detached`.
3. Inner = canonical JSON `{"manifest": ..., "sig": base64(sig)}`.
4. Pick a random 32-byte content key. Ciphertext = `crypto_secretbox_easy` (XSalsa20-Poly1305) with the random nonce prepended, as PyNaCl's `SecretBox.encrypt` does.
5. For every member of the link: `crypto_box_seal(content_key, member.box_pk)`, base64.
6. `POST /v1/gp/notices` with the ciphertext as the body and these headers:
   - `x-drawbook-link: <link_id>`
   - `x-drawbook-kind: <kind>`
   - `x-drawbook-keys: base64(JSON {member_id: sealed_key})`

You must seal to every current member. If the investor's devices changed, the relay answers 409; fetch `/v1/gp/links` again. The size limit is 25 MB per notice. The relay deletes the encrypted file once every device has fetched it, and after 90 days in any case. A GP or investor account that makes no request for 24 months is deleted, with its funds, links and waiting notices.

The reference code is `src/drawbook/relay/gp.py` and `crypto.py` (Apache 2.0).
