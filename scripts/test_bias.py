#!/usr/bin/env python
"""Validate bias logic against SPEC.md §10 test vectors."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from liqmap.bias import Inputs, _components, bias_score, cascade_gate, state

# ----- Case A: slight downside risk, CALM -----
A = Inputs(
    price=62480, price_24h_ago=64200, funding_8h=+0.0001,
    oi_now=2.08e9, oi_24h_ago=1.95e9,
    long_cluster_total=228e6, short_cluster_total=185e6,
    clusters=[(58000, "long", 65e6), (57000, "long", 29e6), (55000, "long", 28e6),
              (59000, "long", 15e6), (61000, "long", 13e6), (62000, "long", 8e6)],
    smart_money_net=-0.30,
)
cA = _components(A)
sA = bias_score(A)
gA = cascade_gate(A, sA)
stA = state(sA, gA)
print(f"A components: C1={cA[0]:.2f} C2={cA[1]:.2f} C3={cA[2]:.2f} C4={cA[3]:.2f}")
print(f"A score={sA} gate={gA} state={stA}")
assert abs(cA[0] - (-8.0)) < 0.05, cA
assert abs(cA[1] - (-16.67)) < 0.05, cA
assert abs(cA[2] - (-2.08)) < 0.05, cA
assert abs(cA[3] - (-4.5)) < 0.05, cA
assert sA == -31, sA
assert gA["open"] is False and gA["trigger_px"] == 58000, gA
assert stA == "静観", stA

# ----- Case B: short squeeze, FIRE -----
B = Inputs(
    price=62480, price_24h_ago=60000, funding_8h=-0.0006,
    oi_now=2.30e9, oi_24h_ago=2.00e9,
    long_cluster_total=150e6, short_cluster_total=300e6,
    clusters=[(63500, "short", 100e6), (64000, "short", 60e6), (66000, "short", 40e6)],
    smart_money_net=+0.50,
)
cB = _components(B)
sB = bias_score(B)
gB = cascade_gate(B, sB)
stB = state(sB, gB)
print(f"B components: C1={cB[0]:.2f} C2={cB[1]:.2f} C3={cB[2]:.2f} C4={cB[3]:.2f}")
print(f"B score={sB} gate={gB} state={stB}")
assert abs(cB[0] - 40.0) < 0.05, cB
assert abs(cB[1] - 25.0) < 0.05, cB
assert abs(cB[2] - 6.67) < 0.05, cB
assert abs(cB[3] - 7.5) < 0.05, cB
assert sB == 79, sB
assert gB["open"] is True and gB["trigger_px"] == 63500, gB
assert stB == "発火", stB

print("\nALL TESTS PASSED ✓")
