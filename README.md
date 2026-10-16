# LedgerLocal

**Sort a year of invoices and receipts into a clean, accountant-ready archive — on your own laptop, with an open-weight model, with no network access at all.**

Point it at the folder where your receipts pile up. It reads each one with a local vision model, pulls out vendor, date, tax and total, categorises it against rules you control, files it into a sane folder tree, and exports the CSV your accountant actually wants.

```console
$ ledgerlocal ingest ~/Downloads/receipts

  read    hetzner-feb.pdf
  read    coffee-with-northwind.jpg
  read    adobe-jan.pdf
  read    legal-invoice.pdf

  2026-02-14  Hetzner Online GmbH             32.73 EUR  hosting
  2026-04-03  Blue Fox Coffee                 11.77 EUR  meals
  2026-01-07  Adobe Inc.                      65.00 USD  software      review
  2026-03-02  Bright Path Legal LLP          990.00 USD  professional_fees

4 ingested, 0 already known, 0 failed, 1 need review

$ ledgerlocal review

1 document(s) the pipeline is not confident about:

  2026-01-07  Adobe Inc.                       65.00 USD
      · subtotal + tax differs from total by 0.09
```

That last line is the point. The model misread `65.09` as `65.00`, and the tool caught it by checking the arithmetic rather than trusting the model. You get told, instead of finding out at tax time.

---

## Why this is built on open weights

Freelancers' receipts are among the most sensitive documents they own. They name clients, reveal rates, show where someone was on a given day, and carry card digits and tax IDs. Handing that archive to an API — one that may log prompts, train on them, change its terms, or get breached — is a real cost that "it's more accurate" does not cover.

So LedgerLocal doesn't ask you to trust a privacy promise. It removes the capability:

```python
# ledgerlocal/offline.py — enabled by default on every command
with enforced():
    socket.create_connection(("api.example.com", 443))   # OfflineViolation
    socket.create_connection(("127.0.0.1", 11434))       # fine, that's your model
```

Every command installs a process-wide socket allowlist before it does anything else. Loopback works, so the model works. Nothing else can open a connection — not this code, not a dependency, not a future refactor by someone careless. **A closed API cannot ship this feature, because the egress it needs is exactly what the guard forbids.** This isn't a nicer version of a cloud tool; it's a thing a cloud tool structurally cannot be.

Four more places the open approach won outright:

**Retrying is free, so accuracy is an engineering problem, not a budget one.** When the model's first answer fails validation, we send it back with the specific complaint and let it try again. On a metered API, a second call on every uncertain document is a line item you'd think twice about. On your own hardware it costs a few seconds of a fan spinning up, so we do it unconditionally — and a 7B model with one repair pass beats a 7B model with none by a wide margin.

**Re-running history is free, so your rules can change.** Your filing rules live in a TOML file you own. Decide in November that "hosting" should have been split into "hosting" and "infrastructure", and `ledgerlocal recategorise` replays your whole archive against the new rules in under a second — without a single model call, because the extraction is already on disk. On a per-document-priced service, re-processing three years of receipts because you changed your mind is a bill.

**The model is a config line.** `vision_model = "qwen2.5vl:7b"` — swap it for a larger one when you're doing year-end on a desktop, a smaller one on a laptop on battery, or a LoRA you fine-tuned on your own handwriting and your own suppliers' invoice layouts. The provider seam is 40 lines and already speaks Ollama *and* the OpenAI-compatible API, so llama.cpp, vLLM and LM Studio all work. Fine-tuning on a client's weird invoice format is a Tuesday afternoon, not a support ticket to a vendor who will never prioritise it.

**It works where the work happens.** On a plane, on a train, in a cafe with captive-portal wifi, in a country where the API isn't available, in an accounting firm whose policy forbids uploading client documents anywhere. There is no account, no API key, no rate limit, no "service degraded" page, and no per-document cost — so the correct thing to do with a shoebox of 800 receipts is just run it on all 800.

Where closed models would genuinely win: a frontier model would read a crumpled, badly-lit photo more reliably than a 7B does. We close most of that gap with structure rather than scale — schema-constrained decoding, deterministic parsing in Python, arithmetic audits, and the free repair pass — and then we're honest about the rest, which is what the `review` queue is for. A tool that flags its own 9-cent misread is more useful than one that is silently right 97% of the time.

---

## Install

```bash
# 1. a local model runtime
curl -fsSL https://ollama.com/install.sh | sh     # or: brew install ollama
ollama pull qwen2.5vl:7b    # reads photos and scans  (~6 GB)
ollama pull qwen2.5:7b      # reads text-layer PDFs   (~4.7 GB)

# 2. LedgerLocal itself — no required dependencies beyond the standard library
pip install "ledgerlocal[all] @ git+https://github.com/Pager-dot/ledgerlocal"

ledgerlocal init
ledgerlocal doctor
```

`doctor` tells you exactly what is missing and the command to fix it.

**Try it with no model at all** — this runs the full pipeline over the bundled samples using a scripted stand-in, so you can see the output before downloading 6 GB:

```bash
git clone https://github.com/Pager-dot/ledgerlocal && cd ledgerlocal
python scripts/demo.py
```

Runs on anything with ~8 GB of RAM. A 7B vision model reads a receipt in roughly 5–15 seconds on Apple Silicon or a modern laptop GPU; text-layer PDFs take about a second, because we read the embedded text and skip the vision pass entirely.

---

## Using it

```bash
ledgerlocal ingest ~/Downloads/receipts     # read, categorise, file
ledgerlocal ingest ~/scans --move           # move originals instead of copying
ledgerlocal review                          # everything the audits flagged
ledgerlocal list --period 2026-Q1
ledgerlocal stats --by client
ledgerlocal export --period 2026-Q1         # CSV + summary + markdown
ledgerlocal recategorise                    # replay your rules, no model needed
ledgerlocal show a3f91b2c                   # full JSON for one document
```

Reads PDFs, JPEG/PNG/HEIC photos, and plain text or `.eml`. PDFs with a text layer skip the vision model.

### What you get on disk

```
~/Documents/LedgerLocal/
├── ledger.sqlite3                     # open it in any SQLite browser; it's yours
├── filed/
│   └── 2026/Q1/hosting/
│       └── 2026-02-14_hetzner-online-gmbh_r0029481773_32-73-eur.pdf
└── exports/
    ├── ledgerlocal-2026-Q1.csv
    ├── ledgerlocal-2026-Q1-by-category.csv
    └── ledgerlocal-2026-Q1.md
```

Plain folders, plainly named files, one SQLite file. If this project is abandoned tomorrow, you still have a sorted archive and a database you can read. Nothing is locked in a format only we understand.

### Your rules beat the model

`~/.config/ledgerlocal/rules.toml`:

```toml
[categories]
studio_rent = ["blackwell properties", "unit 4b"]
hosting     = ["my-colo-provider"]

[clients]
"Northwind Trading" = ["northwind", "po-2026-nw"]
```

Keyword rules are checked first and the longest match wins, so `google ads` lands in `marketing` rather than `software`. The model's suggestion is only the fallback for the long tail. You know your books; a rule you write once keeps working forever at zero cost.

### Swapping the model

`~/.config/ledgerlocal/config.toml`:

```toml
[model]
provider     = "ollama"              # or openai-compatible (llama.cpp, vLLM, LM Studio)
host         = "http://127.0.0.1:11434"
vision_model = "qwen2.5vl:7b"        # or your own fine-tune
text_model   = "qwen2.5:7b"

[behaviour]
date_order       = "dmy"             # tie-breaker for 03/04/2026
review_threshold = 0.55
enforce_offline  = true
allow_hosts      = []                # ["192.168.1.40"] for a GPU box on your LAN
```

---

## How a document becomes a row

1. **Render.** PDFs with a text layer are read directly; everything else is rasterised at 180 dpi and downscaled.
2. **Ask.** One prompt, with a JSON schema handed to the runtime so decoding is constrained. This is what makes a 7B model return parseable JSON reliably.
3. **Parse in Python, not in the model.** `"1.234,56 €"`, `"$1,234.56"`, `"(42.00)"` and `"14.02.2026"` are normalised by deterministic, unit-tested code. Small models are good at *finding* the total and bad at *formatting* it, so we only ask them for the part they're good at.
4. **Audit.** Does subtotal + tax equal total? Do line items exceed the subtotal? Is the due date before the issue date? Is anything essential missing?
5. **Repair, once.** If something's wrong, the model gets told exactly what and tries again. The better of the two answers wins. Free, because it's your hardware.
6. **Categorise, file, store.** Your rules, then the model's suggestion. Content-hashed, so re-running the same folder is a no-op and the same receipt under two filenames is stored once.

Anything that fails an audit is flagged rather than quietly accepted. `ledgerlocal review` is the whole human-in-the-loop story.

---

## Development

```bash
git clone https://github.com/Pager-dot/ledgerlocal && cd ledgerlocal
pip install -e ".[dev,all]"
pytest          # 89 tests, no GPU and no network needed
ruff check .
```

The test suite runs against a fake provider, so contributors don't need to download weights. `tests/test_offline.py` asserts the egress guard actually holds — that one is the load-bearing test.

## Licence

Apache-2.0. See [LICENSE](LICENSE).
