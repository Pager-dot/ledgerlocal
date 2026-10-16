# Why open innovation matters for LedgerLocal

A longer version of the argument in the README, written for anyone deciding whether to build their own small tool on open weights.

## The product only exists because the weights are open

LedgerLocal's pitch to a freelancer is one sentence: *your client invoices never leave your laptop.* Everything else — the categorisation, the folder tree, the CSV export — is table stakes that a dozen SaaS products already do, several of them better funded.

That one sentence is not a feature bolted onto a cloud product. It is a structural property, and `ledgerlocal/offline.py` is where it becomes real:

```python
def _check(address):
    if not _host_allowed(host):
        raise OfflineViolation(...)

socket.socket.connect = connect          # installed before any command runs
```

Every command patches the socket layer so that only loopback (plus hosts the user explicitly allowlisted) can be reached. The local model lives on loopback, so inference works. Nothing else can open a connection — not our code, not a transitive dependency, not a telemetry SDK someone adds in two years.

**A hosted-API version of this tool cannot ship that guard**, because the guard would block the very call the product depends on. The best a cloud competitor can offer is a promise in a privacy policy, which is a different kind of thing than a `raise`. This is not open weights being a cheaper substitute for a closed model. It is open weights enabling a product that could not otherwise be built.

## Unmetered inference changes the engineering, not just the bill

The interesting consequence of "costs nothing per call" is not that it's cheap. It's that it removes a constraint from the design.

**The repair pass.** When the first answer fails validation — a missing total, arithmetic that doesn't add up — we hand the model its own answer plus the specific complaint and ask again:

```
Problem: subtotal + tax differs from total by 0.09
```

On a metered API, doubling your calls on every uncertain document is something you'd A/B test and probably ration. Here it's unconditional, and it's most of why a 7B model is good enough for this job at all.

**Replaying history.** Extraction results live in SQLite. Change your `rules.toml` and `ledgerlocal recategorise` re-files three years of documents in under a second with **zero** model calls. A test asserts exactly this:

```python
assert len(provider.calls) == calls_before  # the model was never asked again
```

With per-document pricing, "I changed my mind about how to categorise hosting" is a bill, so you don't change your mind. Free re-runs make the rule system something users will actually iterate on.

**Running it on everything.** No rate limit and no cost means the right move with a shoebox of 800 receipts is to run it on all 800 overnight. A metered tool makes you triage first, which is the tedious part you were trying to avoid.

## Swappability is leverage you keep

The provider interface is three methods. Two implementations ship — Ollama's native API and the OpenAI-compatible one that llama.cpp, vLLM and LM Studio all speak — so switching runtimes is one config line, and adding a third is an afternoon.

That matters more than it sounds. It means:

- A laptop on battery runs a 3B; the same install on a desktop at year-end runs a 32B.
- An accountant with a recurring client whose invoices have a bizarre layout can fine-tune a LoRA on fifty examples and point `vision_model` at it. With a closed API that is a feature request to a vendor who will never prioritise one firm's supplier.
- When a better open vision model lands — and one does every few months — adopting it is `ollama pull` and editing a string. No migration, no re-pricing, no deprecation notice.

The prompt is a 60-line file in the repo. With a closed API, the prompt is the *only* lever you have. Here it is one of several, and the least important.

## Where the open approach costs something

It would be dishonest to claim open weights won on every axis.

A frontier model reads a crumpled, badly-lit, half-thermal receipt more reliably than a 7B does. That gap is real. Three things close most of it:

1. **Schema-constrained decoding.** The JSON schema is passed to the runtime, so the model physically cannot emit malformed JSON. This is available precisely *because* we control the decoder.
2. **Deterministic parsing.** The model finds the total; Python decides that `"1.234,56 €"` is `Decimal("1234.56")`. Small models are good at the first job and unreliable at the second, so we stop asking them to do the second.
3. **Audits instead of trust.** Subtotal plus tax must equal total. Line items must not exceed the subtotal. A due date must not precede its issue date. Anything that fails goes to `ledgerlocal review`.

What's left after that is the honest residue, and the product surfaces it rather than hiding it. In the bundled demo, the model misreads `$65.09` as `$65.00` and the tool says so:

```
2026-01-07  Adobe Inc.    65.00 USD
    · subtotal + tax differs from total by 0.09
```

A tool that catches its own nine-cent error is worth more to someone filing taxes than one that is silently right most of the time. The design discipline that a smaller model forces — never trust the output, always check the arithmetic — produced a better product than a frontier model would have, because a frontier model would have tempted us to skip the checks.

## Would someone pay for this?

The buyer is a freelancer or a one-person studio who currently has a folder called `receipts` with 300 unsorted files in it, and who spends a weekend each year turning it into a spreadsheet. The tools that automate this are subscriptions that want the documents uploaded. A meaningful number of those people — consultants under NDA, contractors doing defence or medical work, anyone whose clients would object, anyone in a jurisdiction with data-residency rules — cannot use those tools at any price.

For them the choice isn't "cheaper SaaS versus local". It's "local tool versus the weekend". That is a product, and it is one that open weights made possible.
