# vision-invoice-extract (vision)

| metric | value |
|---|---|
| prompt_tokens | 2343 |
| completion_tokens | 818 |
| reasoning_tokens | 327 |
| ttft_s | 3.04 |
| total_s | 9.07 |
| finish_reason | stop |
| answer_words | 95 |
| empty_answer | False |
| truncated | False |

attach: `eval/images/invoice-RSP-2025-08817.jpg`  max_tokens: 3000

## Prompt

Extract this invoice as JSON with keys: supplier, invoice_number, invoice_date, due_date, po_reference, line_items (a list of objects with code, description, qty, unit_price, amount), subtotal, vat, total. Write numbers as plain numbers without thousands separators. Output only the JSON.

## Good answer looks like (written before running)

Passes `eval/checks/vision-invoice-extract.py`: Red Sea Packaging S.A.E., RSP-2025-08817, 2025-09-03, due 2025-10-03, PO-45120. Exactly 5 lines (CB-4030 1200 × 6.75 = 8100; SF-23500 85 × 214 = 18190; PL-A5 5000 × 0.42 = 2100; PT-48 360 × 18.50 = 6660; EP-100 900 × 3.20 = 2880). Subtotal 37930.00, VAT 5310.20, total 43240.20.

## Answer

{
  "supplier": "RED SEA PACKAGING S.A.E.",
  "invoice_number": "RSP-2025-08817",
  "invoice_date": "2025-09-03",
  "due_date": "2025-10-03",
  "po_reference": "PO-45120",
  "line_items": [
    {
      "code": "CB-4030",
      "description": "Corrugated box 40x30x30",
      "qty": 1200,
      "unit_price": 6.75,
      "amount": 8100.00
    },
    {
      "code": "SF-23500",
      "description": "Stretch film 23mic 500mm",
      "qty": 85,
      "unit_price": 214.00,
      "amount": 18190.00
    },
    {
      "code": "PL-A5",
      "description": "Pallet labels A5",
      "qty": 5000,
      "unit_price": 0.42,
      "amount": 2100.00
    },
    {
      "code": "PT-48",
      "description": "Packing tape 48mm",
      "qty": 360,
      "unit_price": 18.50,
      "amount": 6660.00
    },
    {
      "code": "EP-100",
      "description": "Edge protector 1m",
      "qty": 900,
      "unit_price": 3.20,
      "amount": 2880.00
    }
  ],
  "subtotal": 37930.00,
  "vat": 5310.20,
  "total": 43240.20
}

## Reasoning

The user wants the invoice extracted into a specific JSON schema. I need to read each field carefully from the image and convert numbers to plain numeric values (no commas). Let me transcribe: supplier "RED SEA PACKAGING S.A.E.", invoice_number "RSP-2025-08817", invoice_date "2025-09-03", due_date "2025-10-03", po_reference "PO-45120". Line items: CB-4030 / Corrugated box 40x30x30 / 1200 / 6.75 / 8100.00; SF-23500 / Stretch film 23mic 500mm / 85 / 214.00 / 18190.00; PL-A5 / Pallet labels A5 / 5000 / 0.42 / 2100.00; PT-48 / Packing tape 48mm / 360 / 18.50 / 6660.00; EP-100 / Edge protector 1m / 900 / 3.20 / 2880.00. Subtotal 37930.00, vat 5310.20, total 43240.20. I'll output only JSON.
