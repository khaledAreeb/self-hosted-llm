# vision-invoice-audit (vision)

| metric | value |
|---|---|
| prompt_tokens | 2274 |
| completion_tokens | 1447 |
| reasoning_tokens | 847 |
| ttft_s | 2.26 |
| total_s | 14.02 |
| finish_reason | stop |
| answer_words | 211 |
| empty_answer | False |
| truncated | False |

attach: `eval/images/invoice-GH-11932.jpg`  max_tokens: 3000

## Prompt

Check the arithmetic on this invoice, line by line and in the totals. Report any error, the correct figure, and what the correct invoice total should be.

## Good answer looks like (written before running)

- **SB-20 Shelf bracket:** 48 × 37.50 = 1,800.00, not the printed 1,900.00.
- Corrected: subtotal 22,980.00, VAT 3,217.20, total **26,197.20**. The overcharge is 114.00 (100 plus 14 VAT).
- The printed VAT (3,231.20) is correctly 14% of the printed subtotal; it is wrong only as a consequence. Flagging other lines as wrong is a deduction.

## Answer

## Line‑by‑line check (Qty × Unit price)

| Code | Qty | Unit price | Correct amount | Printed amount | OK? |
|---|---|---|---|---|---|
| SH‑5T | 12 | 1,450.00 | 17,400.00 | 17,400.00 | ✅ |
| SB‑20 | 48 | 37.50 | **1,800.00** | 1,900.00 | ❌ |
| AB‑M10 | 20 | 96.00 | 1,920.00 | 1,920.00 | ✅ |
| SS‑01 | 6 | 310.00 | 1,860.00 | 1,860.00 | ✅ |

**Error found:** Line **SB‑20 (Shelf bracket)**. 48 × 37.50 = **1,800.00**, but the invoice shows **1,900.00** (overstated by 100.00).

## Totals check

The printed totals are internally consistent with the *wrong* line amount, so the error cascades:

| Item | Printed | Correct |
|---|---|---|
| Subtotal | 23,080.00 | **23,000.00** |
| VAT 14% | 3,231.20 | **3,220.00** |
| **TOTAL (EGP)** | 26,311.20 | **26,220.00** |

- Printed VAT (3,231.20) = 14% of the printed subtotal 23,080.00 → correct *for that subtotal*.
- Correct VAT = 14% × 23,000.00 = **3,220.00**.

## Conclusion

The single arithmetic mistake is the **SB‑20 line amount (should be 1,800.00, not 1,900.00)**. Correcting it gives:

- Correct subtotal: **23,000.00**
- Correct VAT (14%): **3,220.00**
- **Correct invoice total: 26,220.00 EGP** (the invoice overstates the total by 91.20 EGP).

## Reasoning

The user wants me to verify the arithmetic on this invoice line by line and in the totals. Let me carefully extract each line and compute.

Line 1: SH-5T, Qty 12, Unit price 1,450.00. 12 * 1450 = 17,400.00. Matches amount 17,400.00. Correct.

Line 2: SB-20, Qty 48, Unit price 37.50. 48 * 37.50 = 1,800.00. But the invoice shows 1,900.00. That's an error! 48 * 37.5 = 48 * 30 = 1440, 48 * 7.5 = 360, total 1800. Yes, 1,800.00. Invoice says 1,900.00. Error of +100.

Line 3: AB-M10, Qty 20, Unit price 96.00. 20 * 96 = 1,920.00. Matches 1,920.00. Correct.

Line 4: SS-01, Qty 6, Unit price 310.00. 6 * 310 = 1,860.00. Matches 1,860.00. Correct.

Now subtotal: sum of amounts as printed = 17,400 + 1,900 + 1,920 + 1,860 = 23,080.00. That matches the printed subtotal 23,080.00. So the subtotal is consistent with the (erroneous) line amounts.

But the correct subtotal should be 17,400 + 1,800 + 1,920 + 1,860 = 23,000.00.

Now VAT 14%: printed VAT = 3,231.20. Check 14% of 23,080 = 0.14 * 23,080 = 3,231.20. Yes matches printed subtotal. Correct relative to printed subtotal.

Correct VAT on correct subtotal 23,000 = 0.14 * 23,000 = 3,220.00.

Correct total = 23,000 + 3,220 = 26,220.00.

Printed total = 26,311.20 = 23,080 + 3,231.20. Consistent with printed figures.

So the only arithmetic error is line 2 (SB-20) amount: should be 1,800.00 not 1,900.00. This cascades: correct subtotal 23,000.00, correct VAT 3,220.00, correct total 26,220.00.

Let me double check 14% of 23,000: 23,000 * 0.1 = 2,300; *0.04 = 920; sum 3,220. Yes.

Thus correct invoice total = 26,220.00 EGP.

I'll present line-by-line verification, identify the error, give correct figures, and the correct total.

Format: a clear table or list. Keep concise but complete and self-contained.
