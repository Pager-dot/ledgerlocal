# Architecture

One pass over the codebase, module by module. Roughly 1,400 lines of Python, no required runtime dependencies.

```
          ┌───────────┐
 folder → │  render   │  PDF → text layer, or page images at 180 dpi
          └─────┬─────┘  photo → downscaled PNG
                │        sha256 content hash
          ┌─────▼─────┐
          │  extract  │  prompt + JSON schema → local model → parse → audit
          └─────┬─────┘  one repair pass if the audit fails
                │
          ┌─────▼─────┐
          │ categorize│  your rules.toml first, model suggestion second
          └─────┬─────┘
          ┌─────▼─────┐
          │ organize  │  year/quarter/category/date_vendor_amount.ext
          └─────┬─────┘
          ┌─────▼─────┐
          │   store   │  one SQLite file
          └─────┬─────┘
          ┌─────▼─────┐
          │  export   │  CSV, per-category summary, markdown
          └───────────┘
```

| Module | Does | Notes |
| --- | --- | --- |
| `offline.py` | Socket allowlist | Installed before any command runs. The load-bearing privacy guarantee. |
| `config.py` | TOML config | Every value overridable by CLI flag. Unknown keys are an error, not a shrug. |
| `render.py` | Files → model input | Text-layer PDFs skip the vision pass entirely, which is ~10× faster. |
| `prompts.py` | Prompt + JSON schema | Deliberately short, because swapping models means editing this. |
| `providers/` | Inference | `ollama`, `openai-compatible`, `fake`. Three methods each, stdlib `urllib` only. |
| `parsing.py` | Money and date normalisation | Deterministic and heavily unit-tested. The model never formats anything. |
| `models.py` | `Extraction` + audits | `audit()` is where arithmetic is checked. |
| `categorize.py` | Rules then model | Longest keyword match wins. User rules merge with built-in defaults. |
| `organize.py` | Filing | Never overwrites; copies by default. |
| `store.py` | SQLite | Content hash is the primary key, which gives dedupe for free. |
| `export.py` | CSV / markdown | Currencies are never summed together. |
| `ingest.py` | Orchestration | One failed document never aborts a batch. |
| `cli.py` | Nine commands | No daemon, no login, no background process. |

## Decisions worth knowing about

**Zero required dependencies.** The whole model client is `urllib` against localhost. When the pitch is "audit this yourself and see that nothing leaves", a dependency tree of 40 packages undermines it. PyMuPDF and Pillow are optional extras, needed only for PDFs and image downscaling respectively.

**Proxies are explicitly disabled.** Both HTTP providers build their opener with `ProxyHandler({})`. A corporate `http_proxy` environment variable must never intercept a call we promised stays on the machine.

**`None` is not zero.** `parse_money` returns `None` when it cannot read a value. Conflating "not found" with `0.00` is how a tax export silently loses money, so the two are kept distinct all the way through to the CSV.

**Currencies are never mixed.** Summaries bucket on `category [EUR]` and `category [USD]` separately. Silently adding them would be worse than refusing to total at all, and we don't ship an FX rate source because that would require network access.

**Partial line items are not an error.** Models routinely transcribe some rows and not others. A shortfall against the subtotal is incomplete, not wrong, and we bill from `total` anyway. Items summing to *more* than the subtotal is a genuine contradiction and is flagged. This distinction came directly from watching the demo produce four false positives.

**Content hash as primary key.** Re-running the same folder is a no-op; the same receipt saved under two filenames is stored once. Both are tested.

## Testing

89 tests, no GPU, no network, no downloads. The `FakeProvider` returns scripted JSON, so the full ingest → file → export path runs in CI on three Python versions.

The tests that matter most:

- `test_offline.py` — the egress guard actually blocks, including refusing to *resolve* a hostname it hasn't allowlisted.
- `test_parsing.py` — every money and date format we claim to read.
- `test_extract.py` — a bad first answer triggers exactly one repair, and a worse repair is discarded.
- `test_ingest.py` — dedupe, batch resilience, and that `recategorise` makes zero model calls.
