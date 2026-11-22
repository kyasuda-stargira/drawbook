# Drawbook

Capital call and distribution PDFs → an ILPA-format ledger.

Drawbook is a free, open-source tool for LPs (limited partners: the investors in a private fund). Point it at a folder of fund documents: capital call notices, distribution notices and capital account statements. It returns one spreadsheet of cash flows, laid out in the structure of ILPA's 2025 Capital Call & Distribution Template. Every figure links back to the file and page it came from.

## What you get

`drawbook-out/lp-ledger.xlsx`, with four sheets:

- **Fund**: fund name, GP, currency, fund size, commitment and ownership share.
- **Transactions**: one row per cash flow: dates, ILPA transaction type, amount, whether it changes your unfunded commitment (the part of your commitment not yet called), inside or outside commitment, recallable or not, source file and page.
- **Balances**: paid-in, unfunded, distributions and recallable capital as each notice states them.
- **Warnings**: balances that don't tie to the notice before, **payment details that changed between notices**, and figures Drawbook could not find on the page it read them from.

Plus `lp-ledger.csv` (the transactions) and `notices.json` (everything read).

Filled ILPA 2025 template workbooks (`.xlsx`) in the same folder are read directly, without AI.

## Install

```bash
pip install drawbook-lp
```

Scanned PDFs also need Tesseract and Poppler (`brew install tesseract poppler`, or your system's package manager).

## Run

Drawbook reads with an AI model running on your own machine. Start any OpenAI-compatible local server, for example:

```bash
mlx_lm.server --model mlx-community/Qwen3-8B-4bit --port 8080     # Apple silicon
ollama serve                                                       # then --local-url http://127.0.0.1:11434/v1
```

Then:

```bash
drawbook ./my-fund-notices --local-model mlx-community/Qwen3-8B-4bit
```

Your documents never leave the machine in this mode. Drawbook refuses a "local" address that is not on this computer.

## Using your own AI provider (opt-in)

Some documents read better with a larger model. You can send chosen documents to your own provider:

```bash
export DRAWBOOK_OUTSIDE_KEY=...        # your key; you pay your provider directly
drawbook ./notices --outside anthropic --outside-model <model> --outside-for "*capital-call*.pdf"
```

Before each document is sent, Drawbook shows a warning and asks you to confirm. Side letters and LPAs often limit sharing fund documents with outside processors, so check yours first. Drawbook first reads the document locally to find the LP's name and ID, and removes them from the text it sends. Add `--redact-figures` to remove figures too. Every send is logged in `drawbook-out/outside-send-log.jsonl`.

## How it reads

1. Text from the PDF's text layer; pages with no text go through OCR.
2. The model fills a fixed schema mapped from the ILPA template (see `docs/field-map.md`).
3. Code then checks every figure appears on the page the model cited. A figure found on no page is dropped and listed in Warnings. Drawbook never fills a figure the document does not print.
4. Balances are tied from one notice to the next, and payment details are compared across notices.

**Always confirm changed payment details with the GP by phone before you pay.**

## Getting the documents in

You can drop PDFs into the folder yourself, or let Drawbook collect them. All three routes run on your machine.

**Straight from your GP, through the Drawbook relay.** Your GP sends each notice encrypted to your own devices and signed with the GP's key. Stargira runs the relay but cannot read the notices.

```bash
drawbook connect init --label "Example Pension Scheme"
drawbook connect invite "Example Growth Fund I" --gp-email ir@example-capital.com
drawbook fetch ./my-fund-notices
```

`invite` prints an email you send to your GP yourself. `drawbook connect hold "<fund>"` tells GPs, by fund name only, that an investor wants that fund's notices through Drawbook. A team shares one account: run `drawbook connect join` on a new device and `drawbook connect approve` on one already connected. The first notice from a GP pins its signing key. Check the fingerprint with the GP by phone. If the key ever changes, Drawbook stops opening that GP's notices until you confirm the new one (`drawbook connect pin`). `drawbook connect delete` deletes your account on the relay, with every device, link and notice not yet fetched; documents already on your computer stay. GPs: see `docs/gp-api.md`.

**From email.** Drawbook reads an IMAP mailbox (read-only, nothing marked as read) or a folder of saved `.eml` / Apple Mail `.emlx` files, and keeps only PDF and Excel attachments from notice emails:

```bash
drawbook collect inbox ./my-fund-notices --imap-host imap.example.com --imap-user me@example.com --sender example-capital.com
```

The password comes from the macOS Keychain (`--keychain-service`) or `$DRAWBOOK_IMAP_PASSWORD`, never from the command line.

**From GP portals.** `pip install "drawbook-lp[portal]"`, then describe the portal's login page and document list in a small config file (example in `docs/portals.md`):

```bash
drawbook collect portal mygp.toml ./my-fund-notices
```

It logs in with your own username, takes the password from the Keychain, and asks you to type any two-step code. Many portals' terms of use forbid automated logins: check the portal's terms first. You run it at your own risk.

Every route skips documents it has already collected.

## After reading

- **Documents sheet:** for each fund, quarters with no capital account statement and calls with nothing after their due date, marked missing or late. Add `expected.toml` to the folder to list what each fund should send (`docs/expected.md`).
- **Review:** `drawbook review ./my-fund-notices` walks the Warnings one by one. You accept a figure, correct it or mark it "asked GP". Decisions apply on the next run and show in Warnings as "corrected by reviewer".
- **Filing:** `--file-to ./filed` copies each document to `<fund>/<date>-<kind>.pdf`. Originals are never moved.
- **Reporting currency:** `--reporting-currency GBP --fx-rates rates.csv` adds converted amounts using your own rates (date,from,to,rate). Nothing is fetched. A missing rate becomes a warning, not a guess.
- **Feeds:** `--feed mapping.toml` writes a CSV in another system's import layout. See `docs/feeds.md`.

## Accuracy

Drawbook is tested on made-up notices in varied GP layouts, because real notices are confidential. With Qwen3 8B (4-bit) running locally, it read 98.0% of fields exactly (348 of 355) on 10 notices in three layouts it had never seen. Scanned copies scored within 5 points of their text versions.

Scores on made-up documents may flatter it on real ones. Always check the Warnings sheet. See `docs/test-results.md` for how the test set was built and scored.

## Licence

Apache 2.0. Not investment, tax or accounting advice. It reorganises your own documents; check the output against them.
