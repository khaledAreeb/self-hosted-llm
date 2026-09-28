# longdoc-rejections (long-document)

| metric | value |
|---|---|
| prompt_tokens | 136720 |
| completion_tokens | 583 |
| reasoning_tokens | 332 |
| ttft_s | 3.4 |
| total_s | 23.23 |
| finish_reason | stop |
| answer_words | 124 |
| empty_answer | False |
| truncated | False |

attach: `eval/docs/shipment-register-2025.txt`  max_tokens: 4000

## Prompt

List every REJECTED shipment in the register above: shipment id, date, supplier, warehouse and reason. State how many there are in total.

## Good answer looks like (written before running)

Exactly 4, none invented:
- SHP-00141, 2025-01-19, Delta Paper Co., W5: seal broken on 4 pallets.
- SHP-00952, 2025-05-07, Luxor Dairy, W2: temperature 11.4 C on arrival.
- SHP-02221, 2025-10-22, Alex Electronics, W7: quantity did not match the ASN; missing serial labels.
- SHP-02748, 2025-12-29, Qasr Foods, W9: short remaining shelf life.

The last one sits 99.9% of the way through the document, which tests whether the end is read. This task shares a document with longdoc-q3-late, so prefix caching should make its prefill much faster; record whether it does.

## Answer

There are **4** rejected shipments in the register:

| # | Shipment ID | Date | Supplier | Warehouse | Reason |
|---|-------------|------|----------|-----------|--------|
| 1 | SHP-00141 | 2025-01-19 | Delta Paper Co. | W5 | Seal broken on 4 pallets; load returned to supplier |
| 2 | SHP-00952 | 2025-05-07 | Luxor Dairy | W2 | Temperature log showed 11.4 °C on arrival (limit 6 °C); entire load refused |
| 3 | SHP-02221 | 2025-10-22 | Alex Electronics | W7 | Delivered quantity did not match advance shipping notice; 3 cartons missing serial labels |
| 4 | SHP-02748 | 2025-12-29 | Qasr Foods | W9 | Expiry dates on 2 pallets shorter than the 60% minimum remaining shelf life |

## Reasoning

The user wants me to find every REJECTED shipment in the register and list them with shipment id, date, supplier, warehouse, and reason. Let me scan through the data carefully.

Looking through the data:

1. 2025-01-19 | SHP-00141 | Delta Paper Co. | W5 | 4 pallets | due 2025-01-19 | REJECTED -- seal broken on 4 pallets; load returned to supplier

2. 2025-05-07 | SHP-00952 | Luxor Dairy | W2 | 25 pallets | due 2025-05-07 | REJECTED -- temperature log showed 11.4 C on arrival (limit 6 C); entire load refused

3. 2025-10-22 | SHP-02221 | Alex Electronics | W7 | 8 pallets | due 2025-10-22 | REJECTED -- delivered quantity did not match advance shipping notice; 3 cartons missing serial labels

4. 2025-12-29 | SHP-02748 | Qasr Foods | W9 | 13 pallets | due 2025-12-29 | REJECTED -- expiry dates on 2 pallets shorter than the 60% minimum remaining shelf life

So there are 4 rejected shipments in total.
