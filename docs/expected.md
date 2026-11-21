# Expected documents (`expected.toml`)

Drawbook's Documents sheet lists, per fund, the capital account statements it expected and whether each arrived (received, late or missing). It also lists calls with no later document after their due date.

Without a file, Drawbook expects a quarterly statement from every fund that has sent at least one, due 60 days after quarter end. To change that, put `expected.toml` in the notices folder (or pass `--expected <path>`):

```toml
due_days = 60                     # default for every fund

[funds."Example Growth Fund I"]
kinds = ["capital_account_statement"]
due_days = 45
```

Fund names match ignoring case and spacing. A fund listed here with no statements yet is tracked from the quarter of its first document.
