# vision-label-read@litellm (vision)

| metric | value |
|---|---|
| prompt_tokens | 1122 |
| completion_tokens | 479 |
| reasoning_tokens | 299 |
| ttft_s | 1.46 |
| total_s | 5.13 |
| finish_reason | stop |
| answer_words | 90 |
| empty_answer | False |
| truncated | False |

attach: `eval/images/shipping-label.jpg`  max_tokens: 2500

## Prompt

Read this shipping label. Give the tracking number, destination warehouse and dock, weight, and piece count. Is this the complete shipment?

## Good answer looks like (written before running)

- Tracking **HH7-2025-0921-44817** exactly.
- **W7 Ismailia, Gate 3, Dock 12**; **18.6 kg**; **2 of 3**.
- **Not complete**: this is piece 2 of 3, so one piece is outstanding or labelled separately.
- The label is rotated 90° and slightly skewed; reading it correctly is the test.

## Answer

**Extracted label data**

- **Tracking number:** HH7‑2025‑0921‑44817
- **Destination warehouse:** Harbor & Hale – **W7 Ismailia**
- **Dock:** Dock 12 (Gate 3)
- **Weight:** 18.6 kg
- **Piece count:** 2 of 3

**Is this the complete shipment?**
No. The label reads **"Pieces: 2 of 3,"** meaning this is the *second* of three pieces. One additional piece (piece 3 of 3) is still outstanding, so the shipment is not yet complete.

*(For reference, the label also lists the sender as Orient Textiles, El Mahalla El Kubra, and a reference of PO‑45402.)*

## Reasoning

The user wants specific fields extracted from a rotated shipping label image, plus a judgment on whether it's the complete shipment. Let me read the label carefully.

The label is rotated 90° (text runs vertically). Reading it:
- "EXPRESS"
- "Pieces: 2 of 3"
- "FROM: Orient Textiles, El Mahalla El Kubra"
- "SHIP TO: Harbor & Hale -- W7 Ismailia"
- "Gate 3, Dock 12"
- "Weight: 18.6 kg"
- "Ref: PO-45402"
- Barcode with number "HH7-2025-0921-44817"

Now map to requested fields:
- Tracking number: HH7-2025-0921-44817
- Destination warehouse: W7 Ismailia (Harbor & Hale)
- Dock: Dock 12 (Gate 3)
- Weight: 18.6 kg
- Piece count: 2 of 3

Complete shipment? No — "Pieces: 2 of 3" means this is the second piece out of three, so one more piece is expected. Not complete.

I need a self-contained answer. Provide the fields clearly and answer the completeness question with reasoning. Keep concise but complete.
