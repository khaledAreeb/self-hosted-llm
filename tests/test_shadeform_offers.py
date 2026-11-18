"""Checks how shadeform_deploy.py picks offers, from a saved /instances/types
sample: no network, no key, no cost.

    python3 tests/test_shadeform_offers.py
"""

import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import shadeform_deploy as sd  # noqa: E402

TYPES = json.load(open(os.path.join(HERE, "data", "shadeform_types_sample.json")))["instance_types"]


def rows(offers):
    return [(r["cloud"], r["region"], r["price_cents"]) for r in offers]


# 1. Usable: 1 GPU, 80 GB+, available now, a CUDA 13+ image; cheapest first,
#    then by provider and region. One row per available region.
usable, not_usable = sd.split_offers(TYPES)
assert rows(usable) == [
    ("massedcompute", "beltsville-usa-1", 138),
    ("massedcompute", "desmoines-usa-1", 138),
    ("massedcompute", "kansascity-usa-1", 138),
    ("scaleway", "paris-france-1", 330),
], rows(usable)

# The CUDA 13 image is the one chosen, even when an older one is listed first.
paris = usable[-1]
assert paris["os"] == "ubuntu24.04_cuda13.0_shade_os", paris
assert all(r["os"] == "ubuntu22.04_cuda13.0_shade_os" for r in usable[:3]), usable

# 2. Not usable: they pass every rule except the host CUDA, and say why.
assert [(c, r, p, x["reason"]) for (c, r, p), x in zip(rows(not_usable), not_usable)] == [
    ("denvr", "houston-usa-1", 150, "newest host CUDA is 12.4"),
    ("crusoe", "culpeper-usa-1", 200, "newest host CUDA is 12.2"),
    ("paperspace", "newyork-usa-1", 599, "newest host CUDA is 12.2"),
], not_usable

# 3. Never shown at all: 8 GPUs (imwt A6000x8), 24 GB (scaleway L4),
#    and offers with no region available now (hyperstack, lambdalabs GH200,
#    massedcompute A100_80G and H100).
shown = {(r["cloud"], r["instance_type"]) for r in usable + not_usable}
for hidden in [("imwt", "A6000x8"), ("scaleway", "L4"), ("hyperstack", "A100_80G"),
               ("lambdalabs", "GH200"), ("massedcompute", "A100_80G"), ("massedcompute", "H100")]:
    assert hidden not in shown, hidden

# 4. Region filter matches any part of the name; cloud filter is exact.
u, n = sd.split_offers(TYPES, regions=["france"])
assert rows(u) == [("scaleway", "paris-france-1", 330)] and n == [], (u, n)
u, n = sd.split_offers(TYPES, regions=["DESMOINES-usa-1", "kansascity"])
assert rows(u) == [("massedcompute", "desmoines-usa-1", 138),
                   ("massedcompute", "kansascity-usa-1", 138)], rows(u)
u, n = sd.split_offers(TYPES, clouds=["denvr", "crusoe"])
assert u == [] and rows(n) == [("denvr", "houston-usa-1", 150), ("crusoe", "culpeper-usa-1", 200)], (u, n)
u, n = sd.split_offers(TYPES, clouds=["massed"])            # not a prefix match
assert u == [] and n == [], (u, n)

# 4b. GPU filter matches any part of the GPU or instance type, any case.
u, n = sd.split_offers(TYPES, gpus=["h100"])
assert rows(u) == [("scaleway", "paris-france-1", 330)], rows(u)
assert rows(n) == [("paperspace", "newyork-usa-1", 599)], rows(n)
u, n = sd.split_offers(TYPES, gpus=["A100"])
assert [r["cloud"] for r in u] == ["massedcompute"] * 3 and len(n) == 2, (u, n)
u, n = sd.split_offers(TYPES, gpus=["DGX"])
assert rows(u) == [("massedcompute", "beltsville-usa-1", 138), ("massedcompute", "kansascity-usa-1", 138)], rows(u)
u, n = sd.split_offers(TYPES, gpus=["H100", "A100"], regions=["france", "desmoines"])
assert rows(u) == [("massedcompute", "desmoines-usa-1", 138), ("scaleway", "paris-france-1", 330)], rows(u)

# 4c. Tensor parallel: exactly N GPUs, 80 GB+ each, the same CUDA rule.
#     The one-GPU result on the phase 4 sample is the same with N=1 given explicitly.
assert sd.split_offers(TYPES, tensor_parallel=1) == sd.split_offers(TYPES)
MULTI = json.load(open(os.path.join(HERE, "data", "shadeform_types_multigpu_sample.json")))["instance_types"]
u, n = sd.split_offers(MULTI)                                   # default: one GPU only
assert rows(u) == [("massedcompute", "desmoines-usa-1", 138)] and n == [], (rows(u), n)
u, n = sd.split_offers(MULTI, tensor_parallel=2)
assert rows(u) == [("massedcompute", "desmoines-usa-1", 270),   # whole-VM price, cheapest first
                   ("scaleway", "paris-france-1", 660)], rows(u)
assert all(r["num_gpus"] == 2 and r["link"] == "PCIe, no NVLink" for r in u), u
assert u[1]["os"] == "ubuntu24.04_cuda13.0_shade_os", u[1]           # the CUDA 13 image is chosen
assert [(r["cloud"], r["region"], r["price_cents"], r["reason"]) for r in n] == [
    ("crusoe", "culpeper-usa-1", 400, "newest host CUDA is 12.2")], n
shown = {(r["cloud"], r["instance_type"]) for r in u + n}
for hidden in [("massedcompute", "A6000x2"),       # 48 GB per GPU: too small
               ("crusoe", "A100_80Gx4"),           # 4 GPUs for a 2-way split
               ("hyperstack", "A100_80Gx2"),       # not available now
               ("massedcompute", "A100_sxm4_80G")]: # one GPU
    assert hidden not in shown, hidden
u, n = sd.split_offers(MULTI, tensor_parallel=4)                 # the 4-GPU VM has a CUDA 12 host
assert u == [] and [(r["cloud"], r["num_gpus"]) for r in n] == [("crusoe", 4)], (u, n)
u, n = sd.split_offers(MULTI, tensor_parallel=2, gpus=["H100"])
assert rows(u) == [("scaleway", "paris-france-1", 660)] and n == [], (u, n)
u, n = sd.split_offers(MULTI, tensor_parallel=2, gpus=["A100"], regions=["desmoines"])
assert rows(u) == [("massedcompute", "desmoines-usa-1", 270)] and n == [], (u, n)
assert sd.split_offers(MULTI, tensor_parallel=8) == ([], [])
assert sd.link_text({"nvlink": True, "interconnect": "sxm5"}) == "NVLink"
assert sd.gpu_summary(sd.split_offers(MULTI, tensor_parallel=2)[0][0], 2) == \
    "2 x A100_80G (80 GB each), tensor parallel 2, link: PCIe, no NVLink (per Shadeform)"

# 5. Nothing suitable: empty lists, so `up` creates nothing.
assert sd.split_offers(TYPES, regions=["nowhere"]) == ([], [])
assert sd.split_offers([]) == ([], [])

# 6. Spot capacity does not count: only on-demand availability is used.
spot_only = copy.deepcopy([t for t in TYPES if t["cloud"] == "massedcompute"
                           and t["shade_instance_type"] == "A100_sxm4_80G"])
for a in spot_only[0]["availability"]:
    a["rental_type"] = "spot"
assert sd.split_offers(spot_only) == ([], []), sd.split_offers(spot_only)

# 7. CUDA parsing: newer than 13.0 is fine, 12.9 is not, no CUDA is not.
assert sd.host_cuda("ubuntu24.04_cuda13.1_shade_os") == (13, 1)
assert sd.host_cuda("ubuntu22.04_cuda12.9_shade_os") == (12, 9)
assert sd.host_cuda("ubuntu22.04") is None
fake = copy.deepcopy(spot_only[0])
fake["availability"][0].update(available=True, rental_type="on_demand")
fake["configuration"]["os_options"] = ["ubuntu22.04"]
u, n = sd.split_offers([fake])
assert u == [] and n[0]["reason"] == "no CUDA image offered", n

print("ok: offer filtering, ordering, filters and not-usable reasons")
