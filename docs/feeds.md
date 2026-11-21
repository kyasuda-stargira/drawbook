# Feeds into other systems

Every run writes `drawbook-out/ledger.json`: one object per notice with its transactions, amounts as exact decimal strings, no bank details. Any system's import script can read it.

## Your own system's CSV layout

`--feed mapping.toml` writes `drawbook-out/<mapping name>.csv` in the column layout your system's import template uses. Start from `src/drawbook/feeds/template.toml`. Rename each `header` to your system's column name. Fill `lookup` with your system's transaction codes. A transaction type missing from the lookup with no `default` stops the export, so nothing is mislabelled silently.

No vendor mapping ships, because none of Addepar, Tamarac, Black Diamond or Orion publishes its transaction import columns openly. Details and sources: `docs/feeds-research.md`.

Tamarac records a private fund's activity as one Manual Security Snapshot row per security and date. The exporter writes one row per transaction, so you may need to sum a notice's lines first.

## Addepar (write API)

```bash
drawbook feed addepar ./my-fund-notices --owner <portfolio entity id> --funds addepar-funds.json
```

`addepar-funds.json` maps each fund name, as it appears in the ledger, to its Addepar entity ID. The command writes `drawbook-out/addepar-payloads.json` (request bodies for `POST /v1/transactions`, up to 500 per body). It lists anything it skipped, such as in-kind distributions.

Add `--send https://yourfirm.addepar.com/api` with `$ADDEPAR_TOKEN` (base64 of key:secret) and `$ADDEPAR_FIRM` to write them, after a confirmation. Some type and bucket choices are Drawbook's judgment, not Addepar's wording (see `docs/feeds-research.md`). Send one test transaction to your firm first. This route has not been tried against a live Addepar firm.
