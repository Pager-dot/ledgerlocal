"""Prompts and the JSON schema we constrain the local model to.

Kept in one short, readable module on purpose: swapping or fine-tuning the
model is the point of this project, and the first thing anyone does when they
swap a model is adjust the prompt. With a closed API this file would be the
only lever available; here it is one of several.
"""

from __future__ import annotations

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["invoice", "receipt", "credit_note", "statement", "other"]},
        "vendor": {"type": "string"},
        "vendor_address": {"type": "string"},
        "invoice_number": {"type": "string"},
        "issue_date": {"type": "string"},
        "due_date": {"type": "string"},
        "currency": {"type": "string"},
        "subtotal": {"type": "string"},
        "tax": {"type": "string"},
        "total": {"type": "string"},
        "tax_id": {"type": "string"},
        "payment_method": {"type": "string"},
        "client": {"type": "string"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": "string"},
                    "unit_price": {"type": "string"},
                    "amount": {"type": "string"},
                },
                "required": ["description"],
            },
        },
        "confidence": {"type": "number"},
        "notes": {"type": "string"},
    },
    "required": ["kind", "vendor", "issue_date", "currency", "total", "confidence"],
}

SYSTEM = (
    "You read invoices and receipts and return structured JSON. You are a careful "
    "bookkeeper: you transcribe what the document actually says and you never "
    "invent a number that is not printed on it."
)

_RULES = """Rules:
- Copy values verbatim from the document. If a field is not printed, return "".
- `total` is the final amount payable, after tax and discounts.
- `subtotal` is the amount before tax. `tax` is the tax amount only, never a rate.
- Keep amounts as plain numbers with a decimal point and no currency symbol.
- `currency` is a 3-letter code inferred from the symbol or text on the document.
- `issue_date` should be YYYY-MM-DD. If the day/month order is ambiguous on the
  document, keep the printed order and we will resolve it.
- `vendor` is who was paid, never the customer.
- `client` is only filled in when the document names a client or project that
  this expense was incurred for. Otherwise "".
- `confidence` is 0.0-1.0: how legible the document was and how sure you are of
  the total. A blurry photo with a guessed total is 0.3, not 0.9.
Return only the JSON object."""

VISION_PROMPT = f"""Read this {{page_note}} of a business document and extract its fields as JSON.

{_RULES}

JSON schema:
{{schema}}"""

TEXT_PROMPT = f"""Read the business document below and extract its fields as JSON.

{_RULES}

JSON schema:
{{schema}}

--- DOCUMENT ---
{{document}}
--- END DOCUMENT ---"""

REPAIR_PROMPT = """Your previous answer could not be used.

Problem: {problem}

Your previous answer:
{previous}

Return a corrected JSON object only, matching this schema:
{schema}"""
