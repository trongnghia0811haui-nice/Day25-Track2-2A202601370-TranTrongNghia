import os, sys
import pytest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from data import generate
from missions import m1_efficiency_audit, m2_inference_levers, m3_purchasing, m4_allocation, m5_report


def test_data_generates_deterministically():
    generate.main()
    p = os.path.join(ROOT, "data", "gpu_telemetry.csv")
    a = open(p).read()
    generate.main()
    assert open(p).read() == a                 # seeded -> identical


def test_missions_end_to_end():
    generate.main()
    r1 = m1_efficiency_audit.run(verbose=False)
    assert any(l["gpu_id"] == "gpu-h100-4" for l in r1["lies"])
    r2 = m2_inference_levers.run(verbose=False)
    assert 60 <= r2["savings_pct"] <= 95
    r3 = m3_purchasing.run(verbose=False)
    assert r3["savings_pct"] > 0
    r4 = m4_allocation.run(verbose=False)
    assert 0.85 <= r4["tag_coverage"] <= 1.0
    r5 = m5_report.run(verbose=False)
    assert 40 <= r5["total_savings_pct"] <= 95


def test_m2_rejects_unknown_route_tier(monkeypatch):
    row = {
        "input_tokens": "100",
        "output_tokens": "20",
        "cached_input_tokens": "0",
        "is_batch": "0",
        "is_reasoning": "0",
        "route_tier": "experimental",
    }
    monkeypatch.setattr(m2_inference_levers, "load_csv", lambda _name: [row])
    with pytest.raises(ValueError, match="unsupported route_tier"):
        m2_inference_levers.run(verbose=False)
