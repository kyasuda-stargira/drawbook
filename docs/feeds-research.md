# Downstream feeds: what each vendor publishes (2026-11-21)

Only Addepar publishes enough to build a real feed: a write API for capital calls and distributions, documented in the open. None of the four vendors publishes the column list of a transaction import file. So Drawbook ships one Addepar payload builder, one generic mapping exporter with a starter template, and `ledger.json`. It ships no vendor CSV mapping.

Every claim below gives the URL fetched on 2026-11-21. Items marked **[unverified]** were not confirmed in a fetched vendor document.

## Summary

| Vendor | Public import file format? | Public write API? | What Drawbook ships |
|---|---|---|---|
| Addepar | No. The CSV columns sit in the Help Center (not found in public), and the bulk Import Tool API is closed beta | Yes: `POST /v1/transactions` | `drawbook.addepar.build_payloads` + `send` |
| Envestnet Tamarac | Partly. The upload data set and its UI field names are public; the exact CSV headers come from a bulk report made inside Tamarac | No public write API found | Nothing vendor-specific; use the generic mapping |
| Black Diamond (SS&C) | None found | One exists (REST, writes allowed), but no public reference found | Nothing vendor-specific |
| Orion | None found | One exists (`POST /Portfolio/Transactions/Verbose`); the transaction type codes and full docs need credentials | Nothing vendor-specific |

## Addepar

**Write API: public.** https://developers.addepar.com/docs/transactions.md
- `POST /v1/transactions` creates transactions. A batch takes up to 500 per request.
- On POST, `type`, `currency` and `trade_date` (`YYYY-MM-DD`) are required. `amount` is required for value-based assets and contributions. `id` and `vendor_id` must be left out.
- A capital call is `"type": "contribution"`. A reversed call is `"type": "recalled_contribution"`.
- A contribution splits its amount across `contribution_generic`, `contribution_investment`, `contribution_management_fee` and `contribution_expense`.
- A distribution splits across `generic`, `dividend`, `interest`, `ordinary`, `short_term`, `long_term`, `cap_gain`, `return_of_capital`, `recallable` and `recallable_paid_in`.
- `affects_unfunded_commitment` (boolean) controls whether a contribution reduces unfunded commitment. Contributions reduce it by default.
- Relationships: `owner` is the owning portfolio, legal entity or account. `owned` is the fund holding. Both are `{"type": "entities", "id": ...}`.
- Body content type: `application/vnd.api+json`. The example request also carries a `comment` attribute.
- The page's response example shows the breakdown as a flat attribute, for example `"generic": 100000.0` next to `"type": "distribution"`. Drawbook follows that layout.

**Type names.** https://developers.addepar.com/docs/transaction-types.md
- Lists `capital_call` (managed funds only), `contribution`, `commitment`, `commitment_reduction`, `distribution`, `recalled_contribution`, `unfunded_adjustment`, `tax_withholding` and `tax_withholding_refund`. The page calls the list "for reference only".

**Authentication.** https://developers.addepar.com/docs/basic-authentication.md
- HTTP Basic auth: Base64 of `key:secret`. Every request also needs an `Addepar-Firm` header holding the firm ID. A POST also needs `Content-Type: application/vnd.api+json`. Example base URL: `https://terrabella.addepar.com/api/v1`.
- The API needs an active Addepar firm login with API permissions, so a free tool can build the payload but only the firm can send it.

**Import file: not public.** https://developers.addepar.com/docs/import-tool
- The Import Tool API (`/v1/imports`, `import_type` `TRANSACTIONS`) is "closed beta" for pre-selected clients. Its payload is "the same CSV format as the in-app import", and the required columns are in the Help Center. A web search turned up no public Help Center page, so the CSV columns are **[unverified]**.

**What Drawbook builds.** `drawbook/addepar.py`:
- Each Drawbook transaction becomes one Addepar transaction, with the whole amount in one bucket.
- Investments go to `contribution_investment`, management fees to `contribution_management_fee`, partnership expenses to `contribution_expense`, and other call types to `contribution_generic`.
- Return of capital (cash) goes to `return_of_capital`, dividends to `dividend`, and realised gain (cash) to `cap_gain`. A recallable distribution goes to `recallable`. Other distributions go to `generic`.
- Return of excess capital becomes `recalled_contribution`. Tax withheld becomes `tax_withholding`, and its refund becomes `tax_withholding_refund`.
- Stock (in-kind) distributions are skipped and listed back to the caller.
- `affects_unfunded_commitment` is false when the ILPA impact is "No Impact" (for example, fees charged outside the commitment).
- Mapping choices that are Drawbook's judgment, not Addepar's words **[unverified]**: using `contribution` rather than `capital_call` (Addepar says `capital_call` is for managed funds); income → `generic` rather than `interest`/`ordinary`; tax withheld → `tax_withholding`; trade date = the notice's due date, else its notice date. An LP should check these against one test transaction in their own firm before a bulk send.

## Envestnet Tamarac

**Write API: none public.** https://developer.envestnet.com/products/tamarac/external-api
- The page describes retrieving clients, households, groups, accounts, holdings and documents. It does not mention writing or transactions. The page says reference docs and credentials need Envestnet Developer Portal credentials.

**Upload file: partly public.** https://help.tamaracinc.com/help/content/tamarac_reporting/export___upload_bulk_data/available_upload_data_sets.htm
- Tamarac Reporting lists upload data sets named "Account Capital Calls" (capital call amounts, dates, symbols, account numbers) and "Account Committed Capital". Its "Transactions" data set only marks transactions as intra-group flows. The page does not list column headers.

https://help.tamaracinc.com/help/content/tamarac_reporting/data_setup___calculations/data_setup/cash___securities/create_edit_delete_a_manual_security_snapshot.htm
- Capital calls and distributions for a private fund are recorded as a **Manual Security Snapshot**. The page shows how to load them in bulk: build a Manual Security Snapshot bulk report, edit the CSV, then upload it under Setup > Upload.
- The page names these columns: `Account Number`, `Symbol` (for new snapshots), `Upload Security ID` (to edit existing ones), `Upload Actions`, `Global Notes` and `Is Valuation`.
- The snapshot's value fields are given as screen labels: Return Of Principal, Contributions/Capital Called, Other Contributions, Withdrawals/Distributions, Fees, Misc Expense, Tax Withheld, Interest Paid, Dividends Paid, Long Term Realized Gains, Short Term Realized Gains, Reinvested Distributions, Recallable Distributions.
- Whether the CSV headers match those labels letter for letter is **[unverified]**: the headers come from a bulk report generated inside Tamarac. The bulk report description (https://help.tamaracinc.com/help/content/tamarac_reporting/export___upload_bulk_data/bulk_report_descriptions.htm) lists the report but not its columns. The data dictionary page for capital call dates sits behind a login (https://help.tamaracinc.com/help/content/tamarac_reporting/data_dictionary/c/capital_call_dates.htm).

**What Drawbook builds.** No Tamarac mapping file. An LP can generate the Manual Security Snapshot bulk report in Tamarac, copy its header row into a mapping file, and point each column at a Drawbook field. One example would be `Contributions/Capital Called` → `lp_amount` for capital-call rows. The generic exporter writes one row per transaction, but a snapshot holds one row per security per date, so an LP may need to sum a notice's lines first. That step is not built.

## Black Diamond (SS&C)

**API: exists, reference not public.** https://www.sscblackdiamond.com/media/vvigpui2/ssc-black-diamond-product-brief-api.pdf
- The brief says Black Diamond uses REST calls, including POST, PUT, PATCH and DELETE, documented "in OAPI3 spec". Access uses OAuth 2.0. Transactions are listed under "Reporting Information".
- The brief offers a developer portal and a testing environment "for your firm and trusted partners". It does not name a transaction-create endpoint.
- A web search for a public Black Diamond API reference or OpenAPI file found none. Whether the API can create private-fund transactions is **[unverified]**.

**Import file: none found.** Searches turned up no public Black Diamond transaction import template.

**What Drawbook builds.** Nothing vendor-specific. An LP with Black Diamond can fill a mapping file from the template their SS&C contact gives them.

## Orion

**Write API: exists, partly public.** https://developers.orionadvisor.com/?p=1263 ("Adding Transactions")
- `GET /Portfolio/Tranactions/Verbose/New` (spelled that way on the page) returns a template. `POST /Portfolio/Transactions/Verbose` creates one or more transactions in "Advisor Maintained" accounts, and an optional `?createOffset=true` creates cash offsets. The page warns against writing into normally downloading accounts.
- The example body nests fields under `portfolio`, including `transDate` (shown as `"05/28/2025"`), `transAmount`, `transTypeId`, `contributionCodeId`, `distributionCodeId`, `accountId`, `assetId`, `clientId` and `notes`.
- The page says required fields are coloured green, but the colours do not survive as text, so which fields are required is **[unverified]**.
- The page does not define the `transTypeId` codes, so the codes for a capital call or a distribution are **[unverified]**.

https://developers.orionadvisor.com/quick-start/
- "To get the full api and integration documentation, you must have api credentials." Base URLs: `https://testapi.orionadvisor.com/api/v1` and `https://api.orionadvisor.com/api/v1`.

**Import file: none found.**

**What Drawbook builds.** No Orion client. Without the `transTypeId` codes, a payload builder would guess the one field that decides what each line means. An Orion firm with credentials can read the codes and either fill a mapping file or ask for a client like `addepar.py`.

## What ships

- `drawbook.feeds.export(notices, mapping_path, out_path)` writes a CSV in any column layout that a TOML or JSON mapping file describes. Transforms: date format, sign flip (always, outflows or inflows), constants, a type → code lookup, and first-non-empty field lists.
- `src/drawbook/feeds/template.toml` is a starter mapping using Drawbook's own column names. It is not a vendor format.
- `drawbook.feeds.write_json(notices, out_path)` writes `ledger.json`: `{"drawbook_ledger_version": 1, "notices": [...]}`. Each notice holds every field except bank details, and its `transactions` add `net_called_distributed` and `unfunded_impact_value`. Amounts are exact decimal strings.
- `drawbook.addepar.build_payloads(notices, owner_id, owned_ids)` returns `(payloads, skipped)` without touching the network. `drawbook.addepar.send(payloads, base_url, token, firm_id)` posts them and is never called in tests.

## Caveats / unverified

- Addepar's in-app transaction import columns, Tamarac's exact snapshot CSV headers, Black Diamond's endpoints and Orion's type codes were not found in any public document.
- The Addepar type and bucket mapping has not been tried against a live Addepar firm.
- Canoe's "300+ integrations" figure is quoted from Canoe's own product page as cited on stargira.com/canoe-alternative; it was not re-checked here.
