"""
Generate the synthetic documents and images used by eval/tasks.md.

    python3 eval/make_data.py

Writes eval/docs/*.txt and eval/images/*. Everything is deterministic (fixed
seeds), so the same files -- and therefore the same ground truth -- come out
on every machine with the same fonts. Needs Pillow for the images.

The company, people and suppliers are fictional. Each document hides a small
number of facts the evaluation asks about; the ground truth is printed at the
end so eval/tasks.md can state the expected answer before the model runs.

Why synthetic: the operator chose it over real company files for this phase.
It means grading is objective (the right answer is known exactly), at the cost
of saying less about the model's value on the company's own documents.
"""

import datetime
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "docs")
IMAGES = os.path.join(HERE, "images")
COMPANY = "Harbor & Hale Distribution S.A.E."

SUPPLIERS = [
    "Qasr Foods", "Delta Paper Co.", "Nile Plastics", "Sinai Beverages",
    "Orient Textiles", "Cairo Cleaning Supplies", "Red Sea Packaging",
    "Luxor Dairy", "Alex Electronics", "Giza Hardware",
]
WAREHOUSES = {
    "W1": "10th of Ramadan City", "W2": "Sadat City", "W3": "6th of October City",
    "W4": "Obour", "W5": "Borg El Arab", "W6": "Ain Sokhna",
    "W7": "Ismailia", "W8": "Tanta", "W9": "Asyut",
}
MANAGERS = {
    "W1": "Omar Shalaby", "W2": "Hoda Mansour", "W3": "Tarek Zaki",
    "W4": "Mona Fathy", "W5": "Samir Naguib", "W6": "Karim Farouk",
    "W7": "Rania Helmy", "W8": "Youssef Amer", "W9": "Salma Ragab",
}
DEPUTIES = {
    "W1": "Ahmed Lotfy", "W2": "Dina Kamal", "W3": "Hany Sabry",
    "W4": "Mariam Adel", "W5": "Wael Rashad", "W6": "Nadia Soliman",
    "W7": "Sherif Anwar", "W8": "Laila Mostafa", "W9": "Bassem Fouad",
}

truth = {}  # ground truth, printed at the end


def write(name, text):
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, name), "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------------------
# Document A -- a year of shipment records (~120K tokens)
#
# Hidden: which supplier had the most LATE deliveries in Q3 (a count across
# ~700 lines, with a different supplier leading the full year as a
# distractor), and four REJECTED shipments spread from January to late
# December.
# ---------------------------------------------------------------------------

def shipment_log():
    rng = random.Random(101)
    day = datetime.date(2025, 1, 1)
    rows = []
    while day.year == 2025:
        for _ in range(rng.randint(6, 9)):
            supplier = rng.choice(SUPPLIERS)
            late_p = 0.15 if supplier == "Nile Plastics" else 0.05
            late = rng.random() < late_p
            rows.append(
                {
                    "date": day,
                    "supplier": supplier,
                    "wh": rng.choice(list(WAREHOUSES)),
                    "pallets": rng.randint(2, 26),
                    "late_days": rng.randint(1, 6) if late else 0,
                    "rejected": None,
                }
            )
        day += datetime.timedelta(days=1)

    # Force exact Q3 late counts so the answer is unambiguous.
    q3 = [r for r in rows if 7 <= r["date"].month <= 9]
    targets = {"Sinai Beverages": 21, "Red Sea Packaging": 14}
    for s in SUPPLIERS:
        mine = [r for r in q3 if r["supplier"] == s]
        want = targets.get(s, min(11, sum(r["late_days"] > 0 for r in mine)))
        if s == "Nile Plastics":
            want = 9
        late = [r for r in mine if r["late_days"]]
        ontime = [r for r in mine if not r["late_days"]]
        while len(late) > want:
            late.pop()["late_days"] = 0
        rng.shuffle(ontime)
        while len(late) < want:
            r = ontime.pop()
            r["late_days"] = rng.randint(1, 6)
            late.append(r)

    # Four rejections, none in Q3 and none from the two Q3 leaders.
    rejections = [
        ("2025-01-19", "Delta Paper Co.", "W5",
         "seal broken on 4 pallets; load returned to supplier"),
        ("2025-05-07", "Luxor Dairy", "W2",
         "temperature log showed 11.4 C on arrival (limit 6 C); entire load refused"),
        ("2025-10-22", "Alex Electronics", "W7",
         "delivered quantity did not match advance shipping notice; 3 cartons missing serial labels"),
        ("2025-12-29", "Qasr Foods", "W9",
         "expiry dates on 2 pallets shorter than the 60% minimum remaining shelf life"),
    ]
    rejected_ids = []
    for date, supplier, wh, reason in rejections:
        d = datetime.date.fromisoformat(date)
        r = next(r for r in rows if r["date"] == d)  # first shipment that day
        r.update(supplier=supplier, wh=wh, rejected=reason, late_days=0)

    lines = [
        f"{COMPANY} -- Inbound shipment register, calendar year 2025",
        "Exported from the WMS. One line per inbound shipment.",
        "Columns: delivery date | shipment id | supplier | warehouse | pallets | due date | status",
        "Status is ON TIME, LATE (n days) when delivered after the due date, or REJECTED.",
        "",
    ]
    for i, r in enumerate(rows, 1):
        r["id"] = f"SHP-{i:05d}"
        due = r["date"] - datetime.timedelta(days=r["late_days"])
        if r["rejected"]:
            status = f"REJECTED -- {r['rejected']}"
            rejected_ids.append((r["id"], r["date"].isoformat(), r["supplier"], r["wh"], r["rejected"]))
        elif r["late_days"]:
            status = f"LATE ({r['late_days']} day{'s' if r['late_days'] > 1 else ''})"
        else:
            status = "ON TIME"
        lines.append(
            f"{r['date'].isoformat()} | {r['id']} | {r['supplier']} | {r['wh']} | "
            f"{r['pallets']} pallets | due {due.isoformat()} | {status}"
        )
        if rng.random() < 0.01:
            lines.append(
                f"   note: {r['wh']} dock {rng.randint(1, 14)} closed for maintenance "
                f"on {r['date'].isoformat()}; receipts moved to the next dock."
            )
    write("shipment-register-2025.txt", "\n".join(lines) + "\n")

    counts_q3 = {s: 0 for s in SUPPLIERS}
    counts_year = {s: 0 for s in SUPPLIERS}
    for r in rows:
        if r["late_days"] and not r["rejected"]:
            counts_year[r["supplier"]] += 1
            if 7 <= r["date"].month <= 9:
                counts_q3[r["supplier"]] += 1
    truth["A: Q3 late counts"] = sorted(counts_q3.items(), key=lambda kv: -kv[1])
    truth["A: full-year late counts"] = sorted(counts_year.items(), key=lambda kv: -kv[1])
    truth["A: rejected shipments"] = rejected_ids
    truth["A: total shipments"] = len(rows)


# ---------------------------------------------------------------------------
# Document B -- a supplier agreement (~70K tokens)
#
# Hidden: the body says payment within 30 days of invoice date, a schedule
# says 45 days from receipt of goods, and a precedence clause says the body
# wins. The termination-for-convenience notice is 90 days in the body but an
# amendment at the very end changes it to 60.
# ---------------------------------------------------------------------------

PRODUCTS = [
    ("Full-cream milk", "1 L"), ("Low-fat milk", "1 L"), ("Skimmed milk", "1 L"),
    ("Plain yogurt", "170 g"), ("Greek yogurt", "150 g"), ("Strawberry yogurt", "120 g"),
    ("White cheese", "500 g"), ("Feta cheese", "250 g"), ("Cheddar slices", "200 g"),
    ("Processed cheese", "8 portions"), ("Butter", "200 g"), ("Ghee", "800 g"),
    ("Cooking cream", "200 ml"), ("Whipping cream", "500 ml"), ("Labneh", "400 g"),
    ("Rayeb", "1 L"), ("Chocolate milk", "250 ml"), ("Kids yogurt drink", "200 ml"),
]
DEFINITIONS = [
    ("Affiliate", "any entity that directly or indirectly controls, is controlled by, or is under common control with a Party"),
    ("Agreement", "this Master Supply Agreement together with its Schedules and any Amendment executed in writing by both Parties"),
    ("Business Day", "any day other than a Friday, a Saturday or an official public holiday in the Arab Republic of Egypt"),
    ("Cold Chain", "the uninterrupted series of refrigerated production, storage and distribution activities that maintain the Goods within their Temperature Range"),
    ("Delivery Point", "each warehouse of the Buyer listed in Schedule B, at the dock assigned by the Buyer's dock coordinator"),
    ("Delivery Window", "the time slot allocated to the Supplier for a delivery at a Delivery Point, as set out in Schedule B"),
    ("Goods", "the dairy products described in Schedule A, as updated from time to time in accordance with clause 4"),
    ("Order", "a purchase order issued by the Buyer through the Buyer's procurement portal"),
    ("Order Confirmation", "the Supplier's written acceptance of an Order, including any agreed quantity adjustments"),
    ("Quality Standards", "the specifications, tolerances and testing requirements set out in Schedule A and clause 10"),
    ("Remaining Shelf Life", "the period between the date of delivery and the expiry date printed on the Goods, expressed as a percentage of total shelf life"),
    ("Service Credit", "a reduction in the amount payable by the Buyer calculated in accordance with Schedule C"),
    ("Temperature Range", "for chilled Goods, between 2 C and 6 C inclusive, and for ambient Goods, below 30 C"),
    ("Term", "the period described in clause 18"),
]
BODY_SECTIONS = [
    ("Supply of Goods", [
        "The Supplier shall supply the Goods to the Buyer in accordance with each Order accepted under this Agreement.",
        "The Buyer is not obliged to place any minimum volume of Orders, save as expressly stated in Schedule D.",
        "Each Order constitutes a separate contract incorporating the terms of this Agreement.",
        "The Supplier shall maintain sufficient production capacity to meet the forecast volumes shared by the Buyer on a rolling basis.",
    ]),
    ("Forecasts and Orders", [
        "The Buyer shall provide a non-binding rolling forecast of expected volumes by product line.",
        "The Supplier shall issue an Order Confirmation or a reasoned rejection for each Order through the procurement portal.",
        "An Order not rejected through the procurement portal within the period stated in Schedule B is deemed accepted.",
        "Changes to confirmed Orders require the written agreement of both Parties' procurement contacts listed in Schedule E.",
    ]),
    ("Product Changes", [
        "The Supplier shall not change the formulation, packaging or labelling of any Goods without the Buyer's prior written approval.",
        "Where a change is approved, the Supplier shall provide updated specifications for inclusion in Schedule A.",
        "The Buyer may request samples of any changed Goods for testing before approval is given.",
    ]),
    ("Delivery", [
        "The Supplier shall deliver the Goods to the Delivery Point within the Delivery Window.",
        "Each delivery shall be accompanied by a delivery note stating the Order number, product codes, quantities, batch numbers and expiry dates.",
        "The Buyer may refuse any delivery that arrives outside its Delivery Window without prior agreement of the dock coordinator.",
        "Risk in the Goods passes to the Buyer on signed acceptance at the Delivery Point.",
    ]),
    ("Cold Chain", [
        "The Supplier shall maintain the Goods within their Temperature Range at all times until acceptance.",
        "Each refrigerated vehicle shall carry a calibrated temperature logger whose record is available to the Buyer on arrival.",
        "The Buyer may reject any Goods whose logger record shows an excursion outside the Temperature Range.",
    ]),
    ("Price", [
        "The prices for the Goods are set out in Schedule D and are exclusive of value added tax.",
        "Prices may be reviewed no more than once in each contract year in accordance with the mechanism in Schedule D.",
    ]),
    ("Invoicing and Payment", [
        "The Supplier shall invoice the Buyer after each accepted delivery, quoting the Order number and delivery note number.",
        "PAYMENT_CLAUSE",
        "The Buyer may withhold payment of any amount disputed in good faith, provided it notifies the Supplier of the dispute and its grounds.",
        "Late payment of undisputed amounts shall bear interest at the Central Bank of Egypt corridor lending rate plus one percent.",
    ]),
    ("Remaining Shelf Life", [
        "Chilled Goods shall have a Remaining Shelf Life of at least sixty percent on delivery.",
        "Ambient Goods shall have a Remaining Shelf Life of at least seventy-five percent on delivery.",
        "Goods not meeting these thresholds may be rejected or accepted at a discount agreed by the Buyer's category manager.",
    ]),
    ("Quality", [
        "The Goods shall conform to the Quality Standards and to all applicable Egyptian food safety legislation.",
        "The Supplier shall hold and maintain food safety certification to a recognised international standard.",
        "The Buyer may audit the Supplier's production facilities on reasonable prior notice.",
        "The Supplier shall provide a certificate of analysis for each batch on request.",
    ]),
    ("Recalls", [
        "The Supplier shall notify the Buyer immediately on becoming aware of any safety issue affecting the Goods.",
        "The Parties shall cooperate in any product recall, and the Supplier shall bear its reasonable costs where the recall results from the Supplier's default.",
    ]),
    ("Service Levels", [
        "The Supplier shall meet the key performance indicators set out in Schedule C.",
        "Where a key performance indicator is missed, Service Credits apply as calculated in Schedule C.",
        "Service Credits are a price adjustment and not an estimate of loss.",
    ]),
    ("Warranties", [
        "The Supplier warrants that the Goods are of satisfactory quality and fit for sale to consumers.",
        "The Supplier warrants that it has good title to the Goods and that the Goods are free from encumbrances.",
    ]),
    ("Indemnity", [
        "The Supplier shall indemnify the Buyer against losses arising from any claim that the Goods caused injury or illness to a consumer, save to the extent caused by the Buyer's failure to store the Goods within their Temperature Range.",
    ]),
    ("Limitation of Liability", [
        "Neither Party limits its liability for death or personal injury caused by its negligence, or for fraud.",
        "Subject to the preceding sentence, each Party's total liability in each contract year shall not exceed the total amounts paid and payable under this Agreement in that contract year.",
        "Neither Party is liable for indirect or consequential loss.",
    ]),
    ("Insurance", [
        "The Supplier shall maintain product liability insurance with a reputable insurer for the Term.",
        "The Supplier shall provide evidence of insurance on request.",
    ]),
    ("Confidentiality", [
        "Each Party shall keep confidential all information disclosed by the other Party in connection with this Agreement.",
        "This obligation does not apply to information that is public, independently developed, or required to be disclosed by law.",
    ]),
    ("Term", [
        "This Agreement commences on 1 January 2025 and continues for an initial period of three years.",
        "It renews automatically for successive periods of one year unless terminated in accordance with clause 19.",
    ]),
    ("Termination", [
        "Either Party may terminate this Agreement with immediate effect by written notice if the other Party commits a material breach that is not remedied within the cure period stated in the notice.",
        "Either Party may terminate this Agreement with immediate effect if the other Party becomes insolvent.",
        "TERMINATION_CLAUSE",
        "Termination does not affect Orders accepted before the termination date, which shall be fulfilled on the terms of this Agreement.",
    ]),
    ("Force Majeure", [
        "Neither Party is liable for delay caused by events beyond its reasonable control, provided it notifies the other Party promptly and uses reasonable efforts to mitigate.",
    ]),
    ("Assignment", [
        "Neither Party may assign this Agreement without the other Party's prior written consent, save to an Affiliate.",
    ]),
    ("Notices", [
        "Notices shall be in writing and delivered by hand, by courier or by email to the contacts set out in Schedule E.",
    ]),
    ("Governing Law and Disputes", [
        "This Agreement is governed by the laws of the Arab Republic of Egypt.",
        "Disputes shall first be referred to the Parties' senior managers and, failing resolution, to arbitration at the Cairo Regional Centre for International Commercial Arbitration.",
    ]),
]
PAYMENT_BODY = ("The Buyer shall pay each undisputed invoice within thirty (30) days of the "
                "invoice date by bank transfer to the account stated in Schedule E.")
TERMINATION_BODY = ("Either Party may terminate this Agreement for convenience by giving not less "
                    "than ninety (90) days' prior written notice to the other Party.")


def agreement():
    rng = random.Random(202)
    out = [
        "MASTER SUPPLY AGREEMENT",
        "",
        f"between {COMPANY} (the \"Buyer\")",
        "and Luxor Dairy Products S.A.E. (the \"Supplier\")",
        "dated 15 December 2024",
        "",
        "1. DEFINITIONS AND INTERPRETATION",
        "",
        "1.1 In this Agreement the following terms have the following meanings:",
    ]
    for term, meaning in DEFINITIONS:
        out.append(f"    \"{term}\" means {meaning}.")
    out += [
        "1.2 Headings are for convenience only and do not affect interpretation.",
        "1.3 References to clauses and Schedules are to the clauses of and Schedules to this Agreement.",
        "1.4 If there is any conflict or inconsistency between the clauses of this Agreement and any Schedule, the clauses prevail.",
        "",
    ]
    for n, (title, sentences) in enumerate(BODY_SECTIONS, 2):
        out.append(f"{n}. {title.upper()}")
        out.append("")
        for k, s in enumerate(sentences, 1):
            s = s.replace("PAYMENT_CLAUSE", PAYMENT_BODY).replace("TERMINATION_CLAUSE", TERMINATION_BODY)
            out.append(f"{n}.{k} {s}")
        out.append("")

    # Schedule A: product specifications -- the bulk of the document.
    out += ["SCHEDULE A -- PRODUCT SPECIFICATIONS", ""]
    code = 1000
    for variant in ["Standard", "Private label", "Catering", "Export-grade", "Hotel and restaurant", "Institutional"]:
        for name, size in PRODUCTS:
            for pack in ["single unit", "multipack of 4", "case of 12", "case of 24"]:
                code += rng.randint(1, 9)
                fat = rng.choice(["0.1", "1.5", "3.0", "3.5", "10", "18", "25", "35", "82"])
                life = rng.choice([7, 10, 14, 21, 28, 45, 90, 180])
                out.append(f"A.{code} {variant} {name}, {size}, {pack}")
                out.append(
                    f"    Product code LD-{code}. Fat content {fat}%. Total shelf life {life} days "
                    f"from production. Stored {'chilled' if life < 60 else 'ambient'}. "
                    f"Outer carton {rng.randint(20, 45)} x {rng.randint(15, 35)} x {rng.randint(10, 30)} cm, "
                    f"{rng.randint(4, 12)} layers per pallet, {rng.randint(6, 14)} cartons per layer. "
                    f"Label must show batch number, production date and expiry date in both Arabic and English. "
                    f"Microbiological limits: total plate count below {rng.choice(['10,000', '50,000', '100,000'])} cfu/g; "
                    f"coliforms below {rng.choice(['10', '50', '100'])} cfu/g; no Listeria detected in 25 g. "
                    f"Sensory: {rng.choice(['clean, fresh dairy aroma', 'mild, slightly acidic taste', 'smooth texture without whey separation', 'uniform white colour without discolouration'])}. "
                    f"Tolerance on declared net content: minus {rng.choice(['1', '1.5', '2'])}%, no upper limit."
                )
        out.append("")

    out += ["SCHEDULE B -- DELIVERY POINTS AND WINDOWS", ""]
    for wh, city in WAREHOUSES.items():
        start = rng.choice([5, 6, 7, 8])
        out.append(
            f"B.{wh[1]} Delivery Point {wh}, {city}. Chilled receiving docks {rng.randint(1, 4)} to {rng.randint(5, 9)}. "
            f"Delivery Windows from {start:02d}:00 to {start + 4:02d}:00 on Business Days. "
            f"Orders must be confirmed or rejected in the procurement portal by 16:00 on the Business Day after issue."
        )
    out.append("")

    out += [
        "SCHEDULE C -- KEY PERFORMANCE INDICATORS AND SERVICE CREDITS", "",
        "C.1 On-time delivery: at least 95% of deliveries within the Delivery Window, measured monthly.",
        "C.2 Order fill rate: at least 98% of ordered units delivered, measured monthly.",
        "C.3 Remaining Shelf Life compliance: at least 99% of delivered units meeting clause 9, measured monthly.",
        "C.4 For each full percentage point below a target, a Service Credit of 0.5% of that month's invoiced value applies, capped at 5% per month in total.",
        "C.5 Service Credits are applied as a deduction on the next invoice.",
        "",
        "SCHEDULE D -- PRICING AND PAYMENT", "",
        "D.1 Prices are as listed in the Supplier's price file version 2025-01, which forms part of this Schedule.",
        "D.2 Prices are fixed for the first contract year.",
        "D.3 From the second contract year, prices may be adjusted by no more than the annual change in the Egyptian urban consumer price index published by CAPMAS.",
        "D.4 Payment of each invoice shall be made within forty-five (45) days of receipt of the Goods at the Delivery Point.",
        "D.5 A minimum annual purchase volume of 2,000 pallets applies from the second contract year.",
        "",
        "SCHEDULE E -- CONTACTS", "",
        "E.1 Buyer procurement: Category Manager, Dairy and Chilled.",
        "E.2 Supplier sales: Key Account Director, Modern Trade.",
        "E.3 Bank details are provided separately on the Supplier's letterhead and confirmed by telephone before first payment.",
        "",
        "AMENDMENT No. 1 -- dated 20 March 2025", "",
        "1. Schedule B is amended by adding Delivery Point W9, Asyut, with the same Delivery Windows as W8.",
        "2. All other terms of the Agreement remain in full force and effect.",
        "",
        "AMENDMENT No. 2 -- dated 12 May 2025, effective 1 June 2025", "",
        "1. In clause 19.3, the words \"ninety (90) days'\" are replaced by the words \"sixty (60) days'\".",
        "2. Schedule C, paragraph C.4 is amended so that the monthly cap on Service Credits is 7% instead of 5%.",
        "3. All other terms of the Agreement remain in full force and effect.",
        "",
    ]
    text = "\n".join(out)
    write("supply-agreement-luxor-dairy.txt", text)
    term_clause = next(l for l in out if TERMINATION_BODY in l).split()[0]
    pay_clause = next(l for l in out if PAYMENT_BODY in l).split()[0]
    truth["B: termination clause"] = f"{term_clause} says 90 days; Amendment No. 2 changes it to 60 days, effective 2025-06-01"
    truth["B: payment conflict"] = f"{pay_clause} = 30 days from invoice date vs Schedule D.4 = 45 days from receipt of goods; clause 1.4 says the clauses prevail"
    assert term_clause == "19.3", term_clause  # the amendment text refers to 19.3


# ---------------------------------------------------------------------------
# Document C -- operations manual plus 2025 audit results (~190K tokens)
#
# Hidden, multi-hop: the warehouse that failed its March fire-safety audit
# (W6, found ~85% of the way in), its manager at the start (Karim Farouk,
# near the top), and a staffing update at the very end that moves him and
# names Nadia Soliman as the current manager.
# ---------------------------------------------------------------------------

PROCEDURES = {
    "Receiving": [
        "The dock coordinator allocates dock {dock} to the arriving vehicle and records the arrival time in {sys}.",
        "The receiving clerk checks the seal number against the advance shipping notice before the doors are opened.",
        "Pallets are unloaded into staging lane {lane} and counted before any label is applied.",
        "The receiving clerk scans every pallet label with {sys}; unreadable labels are replaced from the reprint station at dock {dock}.",
        "Any visible damage is photographed and recorded against the delivery note before the driver leaves.",
        "Quantities are compared with the purchase order; differences above {pct}% are escalated to the shift supervisor.",
        "Chilled deliveries are probed with a calibrated thermometer; the reading is entered in {sys}.",
        "The driver receives a signed copy of the delivery note with any remarks written on it.",
    ],
    "Putaway": [
        "{sys} proposes a putaway location in zone {zone} based on product velocity and pallet height.",
        "The forklift operator scans the pallet and the location label to confirm the move.",
        "Pallets heavier than {kg} kg are placed only on the bottom two beam levels.",
        "Locations flagged as blocked in {sys} are skipped and reported to the inventory controller.",
        "Putaway must be completed within {mins} minutes of the pallet leaving the staging lane.",
        "Mixed-SKU pallets are broken down in lane {lane} before putaway.",
    ],
    "Replenishment": [
        "{sys} triggers a replenishment task when a pick face drops below {n} cases.",
        "Replenishment tasks are prioritised ahead of putaway during the picking wave.",
        "The forklift operator brings the full pallet from reserve in zone {zone} to the pick face.",
        "Empty pallets are returned to the pallet stack at the end of aisle {aisle}.",
        "The picker confirms the pick face is correctly labelled before resuming picking.",
    ],
    "Picking": [
        "Pick lists are released by {sys} in waves of {n} orders.",
        "Pickers follow the sequence shown on the handheld scanner, starting from aisle {aisle}.",
        "Each pick is confirmed by scanning the location and then the product barcode.",
        "Short picks are recorded immediately so the inventory controller can investigate.",
        "Picked cases are stacked with heavier items at the bottom and liquids upright.",
        "Completed pick trolleys are delivered to packing station {station}.",
    ],
    "Packing": [
        "The packer checks the trolley against the pick list on {sys}.",
        "Fragile items are wrapped individually before being placed in the carton.",
        "Cartons are sealed with branded tape and labelled with the shipping label printed at station {station}.",
        "Each outbound pallet is stretch-wrapped with at least {n} turns at the base.",
        "The packer weighs each pallet; a deviation of more than {pct}% from the system weight is re-checked.",
    ],
    "Dispatch": [
        "The dock coordinator confirms the vehicle booking in {sys} before loading starts at dock {dock}.",
        "Pallets are loaded in reverse drop order so the first delivery is nearest the doors.",
        "The driver signs the manifest and the seal number is recorded before departure.",
        "Vehicles must leave the yard within {mins} minutes of loading completion.",
        "The shift supervisor reviews any vehicle that departs after its booked slot.",
    ],
    "Cycle counting": [
        "{sys} generates the daily count list based on ABC classification.",
        "Class A locations are counted every {n} weeks; class B and C less frequently.",
        "The inventory controller counts blind, without seeing the system quantity.",
        "Variances above {pct}% are recounted by a second person before adjustment.",
        "Adjustments above EGP {money} require approval from the site manager.",
    ],
    "Returns": [
        "Customer returns are received at dock {dock} only, separated from supplier deliveries.",
        "The returns clerk inspects each item and grades it as resaleable, repairable or scrap.",
        "Resaleable items are returned to stock in zone {zone} after relabelling.",
        "Scrap is recorded in {sys} and moved to the scrap cage at the end of aisle {aisle}.",
        "Credit to the customer is released only after inspection is recorded.",
    ],
    "Cold chain handling": [
        "Chilled products must remain between 2 C and 6 C from receipt to dispatch.",
        "Temperature loggers in the chiller report to {sys} every {mins} minutes.",
        "An excursion alarm is acknowledged by the shift supervisor within {mins} minutes.",
        "Chiller doors must not remain open longer than {n} minutes during loading.",
        "Products affected by an excursion are quarantined in zone {zone} pending a quality decision.",
    ],
    "Hazardous goods storage": [
        "Cleaning chemicals are stored in the dedicated bunded area in zone {zone}.",
        "Oxidisers and flammables are separated by at least {n} metres.",
        "Safety data sheets are kept at the entrance to the hazardous area and in {sys}.",
        "Spills are contained using the spill kit at the end of aisle {aisle} and reported immediately.",
    ],
    "Fire safety and evacuation": [
        "Emergency exits and the routes to them must be kept clear at all times.",
        "Fire extinguishers are inspected monthly and the inspection tag is signed and dated.",
        "The site holds an evacuation drill every {n} months and records attendance.",
        "The assembly point is at the {side} car park; fire wardens carry the attendance list.",
        "Sprinkler systems are inspected by an accredited contractor according to the maintenance plan.",
    ],
    "Forklift operation": [
        "Only operators holding a current licence may operate forklifts.",
        "Pre-use checks are completed at the start of each shift and recorded in {sys}.",
        "The speed limit inside the warehouse is {n} km/h and pedestrians have priority.",
        "Forklifts are charged only in the charging bay next to dock {dock}.",
        "Any fault is reported and the forklift tagged out of service until repaired.",
    ],
    "Housekeeping": [
        "Aisles are swept at the end of every shift.",
        "Shrink wrap and cardboard are collected in the recycling area next to dock {dock}.",
        "Pallets must never be stored in marked walkways.",
        "The shift supervisor completes a housekeeping walk every {n} hours and records findings in {sys}.",
    ],
    "Damage handling": [
        "Damaged stock is moved to the damage cage in zone {zone} and recorded in {sys}.",
        "Photographs of damage are attached to the record within {mins} minutes.",
        "Damage above EGP {money} per event is reported to the site manager the same day.",
        "Recoverable items are repacked at station {station}.",
    ],
}
SYSTEMS = ["the WMS", "the handheld scanner", "the yard management screen", "the ERP", "the site dashboard"]
LOCAL_NOTES = [
    "Because of the site layout, the {proc} area shares space with the {other} area during peak season.",
    "Night shift at this site follows the same {proc} procedure with one supervisor covering two zones.",
    "Temporary staff at this site must be paired with an experienced colleague for their first {n} shifts of {proc} work.",
    "This site trialled a paperless {proc} process in 2024; the trial results are kept by the site manager.",
    "During Ramadan, {proc} shift start times at this site move one hour later.",
]

AUDIT_CATEGORIES = ["Fire safety", "Housekeeping", "Inventory accuracy", "Cold chain", "Forklift safety", "Documentation"]
AUDIT_FAILS = {
    ("Q1", "W6", "Fire safety"): ("two emergency exits in zone C were obstructed by pallets and four fire extinguisher inspection tags were more than two months out of date",
                                  "clear and mark exit routes, re-inspect all extinguishers", "2025-04-15"),
    ("Q1", "W2", "Inventory accuracy"): ("location accuracy measured 96.1% against a 98.5% target",
                                        "full recount of zones A and B and retraining of the count team", "2025-04-30"),
    ("Q1", "W9", "Cold chain"): ("temperature logger records had gaps of up to 3 hours on two nights",
                                "replace logger gateway and add alarm on missing data", "2025-04-10"),
    ("Q2", "W8", "Fire safety"): ("the sprinkler system inspection was 5 months overdue",
                                 "book accredited contractor inspection", "2025-07-15"),
    ("Q2", "W2", "Documentation"): ("12 of 40 sampled receiving records had no driver signature",
                                   "reinforce delivery note signing at all docks", "2025-07-31"),
}
PASS_REMARKS = [
    "no findings", "one minor observation, closed on the day", "meets standard",
    "good practice noted", "meets standard; records complete", "minor labelling observation, closed on the day",
]


def ops_manual():
    rng = random.Random(303)
    out = [
        f"{COMPANY}",
        "WAREHOUSE OPERATIONS MANUAL AND 2025 AUDIT RECORD",
        "Controlled document OPS-M-001, revision 7",
        "",
        "PART 1 -- NETWORK OVERVIEW",
        "",
        "The distribution network consists of nine warehouses. Each is led by a site manager supported by a deputy.",
        "",
    ]
    for wh, city in WAREHOUSES.items():
        out.append(
            f"{wh} -- {city}. Site manager: {MANAGERS[wh]}. Deputy site manager: {DEPUTIES[wh]}. "
            f"Floor area {rng.randint(8, 42) * 1000:,} square metres, {rng.randint(6, 24)} docks, "
            f"{'chilled and ambient' if rng.random() < 0.6 else 'ambient only'} storage."
        )
    out += ["", "PART 2 -- STANDARD OPERATING PROCEDURES BY SITE", ""]

    procs = list(PROCEDURES)
    for wh, city in WAREHOUSES.items():
        out += [f"SECTION {wh} -- {city.upper()}", ""]
        for p_i, proc in enumerate(procs, 1):
            out.append(f"{wh}.{p_i} {proc}")
            out.append(
                f"This procedure applies to all {proc.lower()} activity at the {city} warehouse and is owned by the site manager."
            )
            step_no = 0
            for _ in range(8):  # several passes of the step pool, varied parameters
                for tmpl in PROCEDURES[proc]:
                    step_no += 1
                    s = tmpl.format(
                        dock=rng.randint(1, 18), lane=rng.choice("ABCDEFGH"), zone=rng.choice("ABCDEFG"),
                        aisle=rng.randint(1, 40), station=rng.randint(1, 12), sys=rng.choice(SYSTEMS),
                        pct=rng.choice([1, 2, 3, 5]), kg=rng.choice([800, 900, 1000, 1200]),
                        mins=rng.choice([10, 15, 20, 30, 45]), n=rng.randint(2, 8),
                        money=f"{rng.choice([5, 10, 20, 25, 50])},000", side=rng.choice(["north", "south", "east", "west"]),
                    )
                    out.append(f"  Step {step_no}. {s}")
            note = rng.choice(LOCAL_NOTES).format(
                proc=proc.lower(), other=rng.choice(procs).lower(), n=rng.randint(2, 6)
            )
            out.append(f"  Local note: {note}")
            out.append("")

    out += ["PART 3 -- INTERNAL AUDIT RESULTS, 2025", ""]
    fails_found = []
    for quarter, month in [("Q1", "March"), ("Q2", "June")]:
        out += [f"{quarter} audit round, conducted in {month} 2025", ""]
        for wh, city in WAREHOUSES.items():
            day = rng.randint(3, 27)
            out.append(f"Audit {quarter}-{wh}: {city}, {day} {month} 2025. Lead auditor: Regional Quality team.")
            for cat in AUDIT_CATEGORIES:
                key = (quarter, wh, cat)
                if key in AUDIT_FAILS:
                    finding, action, deadline = AUDIT_FAILS[key]
                    out.append(
                        f"  {cat}: FAIL. Finding: {finding}. Corrective action: {action}. Deadline: {deadline}."
                    )
                    fails_found.append(f"{quarter} ({month}) {wh} {cat}, deadline {deadline}")
                else:
                    out.append(f"  {cat}: PASS -- {rng.choice(PASS_REMARKS)}.")
            if quarter == "Q2" and wh == "W6":
                out.append("  Follow-up: corrective actions from the March fire safety finding were verified as closed.")
            out.append("")

    out += ["PART 4 -- EQUIPMENT REGISTER", ""]
    kinds = ["Reach truck", "Counterbalance forklift", "Pallet jack", "Fire extinguisher (CO2)",
             "Fire extinguisher (powder)", "Chiller unit", "Dock leveller", "Handheld scanner",
             "Label printer", "Stretch wrapper", "Battery charger", "Temperature logger"]
    for wh, city in WAREHOUSES.items():
        out += [f"Equipment at {wh} -- {city}", ""]
        for i in range(1, 171):
            kind = rng.choice(kinds)
            out.append(
                f"  {wh}-EQ-{i:04d} | {kind} | location zone {rng.choice('ABCDEFG')}, aisle {rng.randint(1, 40)} | "
                f"last inspected 2025-{rng.randint(1, 6):02d}-{rng.randint(1, 28):02d} | "
                f"{'In service' if rng.random() < 0.95 else 'Out of service, awaiting repair'}"
            )
        out.append("")

    out += [
        "PART 5 -- STAFFING UPDATES",
        "",
        "Notice dated 10 June 2025, effective 15 June 2025:",
        f"- {MANAGERS['W6']}, site manager of W6 ({WAREHOUSES['W6']}), transfers to W2 ({WAREHOUSES['W2']}) as site manager.",
        f"- {MANAGERS['W2']}, previously site manager of W2, moves to the regional quality team.",
        f"- {DEPUTIES['W6']}, previously deputy site manager of W6, is appointed site manager of W6.",
        f"- {DEPUTIES['W3']} is appointed deputy site manager of W6 and is replaced as deputy at W3 by Ola Hamdy.",
        "",
        "End of document.",
        "",
    ]
    write("operations-manual-2025.txt", "\n".join(out))
    truth["C: March fire-safety failure"] = (
        f"W6 {WAREHOUSES['W6']}; manager at audit time {MANAGERS['W6']}; current manager "
        f"{DEPUTIES['W6']} (from 2025-06-15); deadline 2025-04-15"
    )
    truth["C: every audit failure"] = fails_found


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------

FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation",
             "/usr/share/fonts/truetype/comic-relief-zorin-os"]


def font(name, size):
    for d in FONT_DIRS:
        path = os.path.join(d, name)
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    raise SystemExit(f"font {name} not found in {FONT_DIRS}")


def as_scan(img, angle, seed):
    """Make a clean render look like a mediocre office scan."""
    rng = random.Random(seed)
    img = img.convert("L").rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=235)
    px = img.load()
    for _ in range(img.width * img.height // 60):
        x, y = rng.randrange(img.width), rng.randrange(img.height)
        px[x, y] = max(0, px[x, y] - rng.randint(30, 90))
    return img.filter(ImageFilter.GaussianBlur(0.6)).convert("RGB")


def money(v):
    return f"{v:,.2f}"


def invoice(filename, supplier, number, date, due, lines, printed_totals=None, seed=1, angle=1.2):
    W, H = 1240, 1754
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    bold, reg, small = font("DejaVuSans-Bold.ttf", 40), font("DejaVuSans.ttf", 24), font("DejaVuSans.ttf", 20)
    d.text((80, 80), supplier, font=bold, fill="black")
    d.text((80, 140), "Industrial Zone 3, Plot 17  |  Tax Reg. No. 512-448-907", font=small, fill="black")
    d.text((W - 420, 80), "TAX INVOICE", font=bold, fill="black")
    y = 240
    for label, value in [("Invoice No.", number), ("Invoice date", date), ("Due date", due), ("PO reference", "PO-45120")]:
        d.text((W - 480, y), f"{label}:", font=reg, fill="black")
        d.text((W - 280, y), value, font=reg, fill="black")
        y += 38
    d.text((80, 240), "Bill to:", font=reg, fill="black")
    d.text((80, 278), COMPANY, font=reg, fill="black")
    d.text((80, 316), "Accounts Payable, 6th of October City", font=reg, fill="black")

    y = 470
    cols = [80, 250, 700, 830, 1000]
    for x, h in zip(cols, ["Code", "Description", "Qty", "Unit price", "Amount"]):
        d.text((x, y), h, font=font("DejaVuSans-Bold.ttf", 24), fill="black")
    d.line((70, y + 40, W - 70, y + 40), fill="black", width=2)
    y += 60
    computed = 0.0
    for code, desc, qty, price, amount in lines:
        for x, v in zip(cols, [code, desc, f"{qty:,}", money(price), money(amount)]):
            d.text((x, y), v, font=reg, fill="black")
        computed += amount
        y += 48
    d.line((70, y, W - 70, y), fill="black", width=2)
    subtotal, vat, total = printed_totals or (computed, round(computed * 0.14, 2), round(computed * 1.14, 2))
    y += 30
    for label, v in [("Subtotal", subtotal), ("VAT 14%", vat), ("TOTAL (EGP)", total)]:
        f = font("DejaVuSans-Bold.ttf", 26) if label.startswith("TOTAL") else reg
        d.text((760, y), label, font=f, fill="black")
        d.text((1000, y), money(v), font=f, fill="black")
        y += 44
    d.text((80, H - 160), "Payment by bank transfer. Please quote the invoice number.", font=small, fill="black")
    os.makedirs(IMAGES, exist_ok=True)
    as_scan(img, angle, seed).save(os.path.join(IMAGES, filename), quality=70)
    return subtotal, vat, total


def delivery_note():
    W, H = 1240, 1500
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    bold, reg = font("DejaVuSans-Bold.ttf", 36), font("DejaVuSans.ttf", 24)
    d.text((80, 70), "LUXOR DAIRY PRODUCTS", font=bold, fill="black")
    d.text((80, 125), "DELIVERY NOTE  DN-77410", font=font("DejaVuSans-Bold.ttf", 28), fill="black")
    for i, (k, v) in enumerate([("Date", "2025-09-21"), ("Deliver to", "Harbor & Hale, W4 Obour, dock 3"),
                                ("Order ref.", "PO-45388"), ("Vehicle", "Reefer truck, plate 7431")]):
        d.text((80, 200 + i * 38), f"{k}: {v}", font=reg, fill="black")
    y = 400
    for x, h in zip([80, 320, 900], ["Product code", "Description", "Qty delivered"]):
        d.text((x, y), h, font=font("DejaVuSans-Bold.ttf", 24), fill="black")
    d.line((70, y + 40, W - 70, y + 40), fill="black", width=2)
    y += 60
    for code, desc, qty in [("LD-1004", "Full-cream milk 1 L", "480"),
                            ("LD-1013", "Plain yogurt 170 g", "1,080"),
                            ("LD-1021", "White cheese 500 g", "300"),
                            ("LD-1033", "Butter 200 g", "240"),
                            ("LD-1007", "Low-fat milk 1 L", "120")]:
        for x, v in zip([80, 320, 900], [code, desc, qty]):
            d.text((x, y), v, font=reg, fill="black")
        y += 52
    d.line((70, y, W - 70, y), fill="black", width=2)
    d.text((80, H - 260), "Received by: ______________________", font=reg, fill="black")
    d.text((80, H - 200), "Driver signature: __________________", font=reg, fill="black")

    # Handwritten remark in blue, slightly rotated, under the table -- clear
    # of the printed quantities so every number stays readable.
    note = Image.new("RGBA", (620, 110), (0, 0, 0, 0))
    ImageDraw.Draw(note).text((5, 5), "Butter: 2 cartons crushed -\nrefused. M. Adel", font=font("ComicRelief-Regular.ttf", 34), fill=(20, 40, 170, 255))
    note = note.rotate(4, expand=True, resample=Image.BICUBIC)
    img.paste(note, (540, y + 40), note)
    sig = Image.new("RGBA", (400, 80), (0, 0, 0, 0))
    ImageDraw.Draw(sig).text((5, 5), "M. Adel", font=font("ComicRelief-Regular.ttf", 40), fill=(20, 40, 170, 255))
    img.paste(sig, (330, H - 290), sig)
    img = img.rotate(-0.8, resample=Image.BICUBIC, expand=True, fillcolor="white")
    img.save(os.path.join(IMAGES, "delivery-note-DN-77410.jpg"), quality=72)


def chart():
    values = [93, 94, 92, 91, 93, 92, 88, 78, 86, 87, 92, 94]
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    W, H, left, right, top, bottom = 1400, 800, 120, 60, 110, 110
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((left, 30), "On-time delivery rate by month, 2025 (%)", font=font("DejaVuSans-Bold.ttf", 32), fill="black")
    lo, hi = 70, 100
    ypx = lambda v: top + (hi - v) / (hi - lo) * (H - top - bottom)
    for g in range(lo, hi + 1, 5):
        d.line((left, ypx(g), W - right, ypx(g)), fill=(210, 210, 210), width=1)
        d.text((left - 60, ypx(g) - 12), str(g), font=font("DejaVuSans.ttf", 22), fill="black")
    slot = (W - left - right) / 12
    for i, (m, v) in enumerate(zip(months, values)):
        x0 = left + i * slot + slot * 0.18
        d.rectangle((x0, ypx(v), x0 + slot * 0.64, ypx(lo)), fill=(52, 101, 164))
        d.text((x0 + 8, H - bottom + 14), m, font=font("DejaVuSans.ttf", 22), fill="black")
    x = left
    while x < W - right:  # dashed target line
        d.line((x, ypx(90), min(x + 18, W - right), ypx(90)), fill=(200, 30, 30), width=3)
        x += 30
    d.text((W - right - 150, ypx(90) - 36), "target 90%", font=font("DejaVuSans.ttf", 22), fill=(200, 30, 30))
    img.save(os.path.join(IMAGES, "ontime-chart-2025.png"))
    truth["V: chart values"] = dict(zip(months, values))


def terminal():
    lines = [
        "$ python3 stock_sync.py --warehouse W4 exports/stock_2025-09-21.csv",
        "Loaded 1,842 rows from exports/stock_2025-09-21.csv",
        "Traceback (most recent call last):",
        '  File "/opt/hh/stock_sync.py", line 88, in <module>',
        "    main()",
        '  File "/opt/hh/stock_sync.py", line 81, in main',
        "    sync_rows(rows, args.warehouse)",
        '  File "/opt/hh/stock_sync.py", line 57, in sync_rows',
        '    qty = int(row["qty_on_hand"])',
        "KeyError: 'qty_on_hand'",
        "$ head -3 exports/stock_2025-09-21.csv",
        "sku,description,location,qty_onhand,uom",
        "HH-DRY-10231,Rice 5kg,W4-A-03-2,340,bag",
        "HH-DRY-10232,Rice 1kg,W4-A-03-3,1200,bag",
        "$ ",
    ]
    f = font("DejaVuSansMono.ttf", 22)
    W, H = 1300, 60 + 34 * len(lines) + 40
    img = Image.new("RGB", (W, H), (30, 30, 36))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 36), fill=(58, 58, 66))
    d.text((W // 2 - 110, 6), "ops@wh-04: ~/hh", font=font("DejaVuSans.ttf", 20), fill=(200, 200, 200))
    for i, line in enumerate(lines):
        colour = (240, 110, 110) if line.startswith("KeyError") else (220, 220, 220)
        d.text((24, 56 + i * 34), line, font=f, fill=colour)
    img.save(os.path.join(IMAGES, "terminal-stock-sync.png"))


def shipping_label():
    W, H = 1200, 800
    img = Image.new("RGB", (W, H), (250, 248, 240))
    d = ImageDraw.Draw(img)
    d.rectangle((20, 20, W - 20, H - 20), outline="black", width=4)
    d.text((50, 45), "EXPRESS", font=font("DejaVuSans-Bold.ttf", 54), fill="black")
    d.text((W - 330, 60), "Pieces: 2 of 3", font=font("DejaVuSans-Bold.ttf", 34), fill="black")
    d.line((20, 130, W - 20, 130), fill="black", width=3)
    d.text((50, 150), "FROM: Orient Textiles, El Mahalla El Kubra", font=font("DejaVuSans.ttf", 26), fill="black")
    d.text((50, 200), "SHIP TO:", font=font("DejaVuSans-Bold.ttf", 30), fill="black")
    d.text((50, 245), "Harbor & Hale -- W7 Ismailia", font=font("DejaVuSans-Bold.ttf", 40), fill="black")
    d.text((50, 300), "Gate 3, Dock 12", font=font("DejaVuSans.ttf", 34), fill="black")
    d.text((50, 370), "Weight: 18.6 kg     Ref: PO-45402", font=font("DejaVuSans.ttf", 28), fill="black")
    rng = random.Random(7)
    x = 60
    while x < W - 80:  # barcode-ish stripes
        w = rng.choice([3, 3, 5, 7])
        d.rectangle((x, 450, x + w, 640), fill="black")
        x += w + rng.choice([3, 4, 6])
    d.text((300, 660), "HH7-2025-0921-44817", font=font("DejaVuSansMono.ttf", 40), fill="black")
    img = img.rotate(90, expand=True).rotate(3, resample=Image.BICUBIC, expand=True, fillcolor=(120, 110, 95))
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    img.save(os.path.join(IMAGES, "shipping-label.jpg"), quality=68)


def images():
    lines = [
        ("CB-4030", "Corrugated box 40x30x30", 1200, 6.75, 8100.00),
        ("SF-23500", "Stretch film 23mic 500mm", 85, 214.00, 18190.00),
        ("PL-A5", "Pallet labels A5", 5000, 0.42, 2100.00),
        ("PT-48", "Packing tape 48mm", 360, 18.50, 6660.00),
        ("EP-100", "Edge protector 1m", 900, 3.20, 2880.00),
    ]
    st, vat, tot = invoice("invoice-RSP-2025-08817.jpg", "RED SEA PACKAGING S.A.E.", "RSP-2025-08817",
                           "2025-09-03", "2025-10-03", lines, seed=11)
    truth["V: invoice RSP"] = f"subtotal {money(st)}, VAT {money(vat)}, total {money(tot)}"

    wrong = [
        ("SH-5T", "Steel shelving unit 5-tier", 12, 1450.00, 17400.00),
        ("SB-20", "Shelf bracket", 48, 37.50, 1900.00),  # should be 1,800.00
        ("AB-M10", "Anchor bolts M10, box of 50", 20, 96.00, 1920.00),
        ("SS-01", "Safety signage set", 6, 310.00, 1860.00),
    ]
    printed = (23080.00, 3231.20, 26311.20)
    invoice("invoice-GH-11932.jpg", "GIZA HARDWARE", "GH-11932", "2025-09-10", "2025-10-10",
            wrong, printed_totals=printed, seed=12, angle=-0.9)
    truth["V: invoice GH error"] = "SB-20: 48 x 37.50 = 1,800.00 not 1,900.00; correct subtotal 22,980.00, VAT 3,217.20, total 26,197.20 (overcharge 114.00)"

    delivery_note()
    chart()
    terminal()
    shipping_label()


if __name__ == "__main__":
    shipment_log()
    agreement()
    ops_manual()
    images()
    print("Wrote", sorted(os.listdir(DOCS)), sorted(os.listdir(IMAGES)))
    print("\nGROUND TRUTH")
    for k, v in truth.items():
        print(f"- {k}: {v}")
