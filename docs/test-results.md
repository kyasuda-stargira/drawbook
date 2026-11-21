# How Drawbook is tested

Real capital call notices are confidential, so Drawbook is tested on made-up notices that look like real ones. Each one comes with an answer key: every figure the notice prints, and the page it is on.

## The test set

- **Four layout families: 39 made-up notices, plus ILPA's own published sample letter.** Each family has three funds in different GP house styles: one-page tables, multi-page prose letters, Luxembourg and US administrator schedules, a fund-portal print-out, a German-first manager letter and an email-style notice. They cover capital calls, distributions, combined call-and-distribution notices and quarterly capital account statements, in US dollars, euros and pounds.
- **Balances tie.** Within each fund, every notice's "before" balances equal the previous notice's "after" balances, as on real notices.
- **Answer keys are checked.** A script confirms every figure and date in a key is printed on the page the key cites. Independent reviewers then checked 9 keys by reading page images, without seeing the generator code.
- **Scanned copies.** Five notices also exist as image-only PDFs with slight skew, blur and noise, to test the OCR route.

## Scoring

A field counts when the answer key fills it. It is right only when the value matches exactly: figures to the cent, dates equal, names equal ignoring case and spacing. Each transaction line counts as four fields (type, amount, inside or outside commitment, effect on unfunded commitment). Fields Drawbook fills that the key leaves empty are counted separately.

## Results (v0.1.0, November 2026)

Model: Qwen3 8B, 4-bit, running locally. No outside AI.

| Set | Role | Fields right |
|---|---|---|
| Three practice families (29 made-up notices + ILPA's sample letter) | used to develop the reader | 1,055 of 1,096 (96.3%) |
| **Held-out family (10 notices)** | **scored once, never used to develop the reader** | **348 of 355 (98.0%)** |
| Scanned copies (5 notices) | OCR route | 94.7%, against 92.1% for the same notices as text |

An earlier held-out family scored 77.8% on the first version. It then became a practice family, and a new held-out family was built by a separate author for the final score.

## Limits

- Made-up notices may be more regular than real ones, so these scores may flatter Drawbook on real documents.
- The held-out family is kept private so it can be used for one more honest re-test. The practice families and their generators are in `testset/`. ILPA's sample letter is not included (it is ILPA's copyright); `tools/fetch_ilpa.py` downloads it.
- After scoring, one contact address in three family B letters was changed to a reserved `example.com` domain. The answer keys and every figure are unchanged.
- Always check the Warnings sheet, and confirm changed payment details with the GP by phone before paying.
