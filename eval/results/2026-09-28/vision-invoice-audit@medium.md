# vision-invoice-audit@medium (vision)

| metric | value |
|---|---|
| prompt_tokens | 2244 |
| completion_tokens | 1409 |
| reasoning_tokens | 878 |
| ttft_s | 2.22 |
| total_s | 13.62 |
| finish_reason | stop |
| answer_words | 179 |
| empty_answer | False |
| truncated | False |

attach: `eval/images/invoice-GH-11932.jpg`  max_tokens: 12000

## Prompt

Check the arithmetic on this invoice, line by line and in the totals. Report any error, the correct figure, and what the correct invoice total should be.

## Good answer looks like (written before running)

- **SB-20 Shelf bracket:** 48 × 37.50 = 1,800.00, not the printed 1,900.00.
- Corrected: subtotal 22,980.00, VAT 3,217.20, total **26,197.20**. The overcharge is 114.00 (100 plus 14 VAT).
- The printed VAT (3,231.20) is correctly 14% of the printed subtotal; it is wrong only as a consequence. Flagging other lines as wrong is a deduction.

## Answer

**Line‑by‑line check (Qty × Unit price = Amount)**

| Code | Qty | Unit price | Stated amount | Correct amount | OK? |
|---|---|---|---|---|---|
| SH‑5T | 12 | 1,450.00 | 17,400.00 | 17,400.00 | ✓ |
| SB‑20 | 48 | 37.50 | 1,900.00 | **1,800.00** | ✗ |
| AB‑M10 | 20 | 96.00 | 1,920.00 | 1,920.00 | ✓ |
| SS‑01 | 6 | 310.00 | 1,860.00 | 1,860.00 | ✓ |

**The error:** the SB‑20 line. 48 × 37.50 = **1,800.00**, but the invoice shows 1,900.00 (overstated by 100.00).

**Corrected totals**

- Subtotal: 17,400.00 + 1,800.00 + 1,920.00 + 1,860.00 = **22,980.00** (invoice shows 23,080.00)
- VAT 14%: 22,980.00 × 0.14 = **3,217.20** (invoice shows 3,231.20)
- **Correct TOTAL (EGP): 22,980.00 + 3,217.20 = 26,197.20** (invoice shows 26,311.20)

The invoice total is therefore **114.00 too high** (the 100.00 line error plus 14% VAT on it). Note that the invoice's own subtotal, VAT, and total are internally consistent with its (wrong) line amounts — the single source of the error is the SB‑20 line.

## Reasoning

The user wants me to verify the arithmetic on this invoice line by line and in the totals. Let me carefully extract each line item and recompute.

Line items (Code, Description, Qty, Unit price, Amount):
1. SH-5T: 12 × 1,450.00 = 17,400.00. Check: 12 × 1450 = 17,400. Correct.
2. SB-20: 48 × 37.50 = 1,900.00? 48 × 37.5 = 48 × 37 + 48 × 0.5 = 1776 + 24 = 1,800. So 48 × 37.50 = 1,800.00, not 1,900.00. Error here. The invoice says 1,900.00. Correct is 1,800.00.
3. AB-M10: 20 × 96.00 = 1,920.00. Correct.
4. SS-01: 6 × 310.00 = 1,860.00. Correct.

Now subtotal. Invoice subtotal = 23,080.00. Let's sum the invoice's listed amounts: 17,400 + 1,900 + 1,920 + 1,860 = 23,080. Yes that matches the invoice's own (erroneous) line amounts. So the subtotal is consistent with the listed line amounts, but one line amount is wrong.

Correct line amounts sum: 17,400 + 1,800 + 1,920 + 1,860 = 22,980.00.

Now VAT 14%: invoice shows 3,231.20. Check 14% of 23,080 = 0.14 × 23,080 = 3,231.20. Correct relative to invoice subtotal.

Correct VAT on 22,980 = 0.14 × 22,980 = 3,217.20.

Total: invoice 26,311.20 = 23,080 + 3,231.20. Correct relative to its subtotal.

Correct total = 22,980 + 3,217.20 = 26,197.20.

So the only arithmetic error is the SB-20 line: 48 × 37.50 should be 1,800.00, not 1,900.00. This propagates to subtotal (should be 22,980.00), VAT (3,217.20), and total (26,197.20).

Let me double check 48 × 37.5: 37.5 × 50 = 1875, minus 37.5 × 2 = 75, gives 1800. Yes.

Thus the error is a 100.00 overstatement on that line, leading to total overstated by 100 × 1.14 = 114.00. Indeed 26,311.20 - 26,197.20 = 114.00. Good consistency check.

Now I'll present line-by-line verification, identify the error, give correct figures, and the correct total.

Format: a clear table or list. Keep concise but complete. The response must stand alone.
