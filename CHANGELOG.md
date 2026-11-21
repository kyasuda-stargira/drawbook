# Changelog

## 0.2.0 (2026-11-21)

- **GPs can send notices straight to you** through the Drawbook relay: `drawbook connect`, `drawbook fetch`, and `drawbook-gp` for GPs. Each notice is encrypted to your devices and signed by the GP; the relay cannot read it. A notice signed with any key other than the GP's confirmed one is rejected. Relay source: `relay/`. GP guide: `docs/gp-api.md`.
- **Collection:** `drawbook collect inbox` (IMAP or saved .eml/.emlx) and `drawbook collect portal` (your own portal login; extra `[portal]`).
- **Documents sheet:** missing or late statements and calls (`expected.toml`).
- **Review:** `drawbook review` to accept, correct or mark "asked GP" for each warning; decisions apply on the next run.
- **Filing** (`--file-to`), **reporting currency** from your own rates (`--reporting-currency`, `--fx-rates`).
- **Feeds:** `ledger.json` on every run, `--feed` mapping CSV, `drawbook feed addepar` (Addepar transactions API).
- Reads `.drawbook.json` notice files a GP sends, exactly, with no AI reading.

## 0.1.0 (2026-11-21)

First release: PDFs and ILPA 2025 template workbooks to an ILPA-shaped ledger, every figure linked to its page.
