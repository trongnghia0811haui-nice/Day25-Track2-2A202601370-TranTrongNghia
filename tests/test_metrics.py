import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from finops import metrics


def test_mfu_basic():
    assert metrics.compute_mfu(200, 990) == round(200 / 990, 10) or abs(metrics.compute_mfu(200, 990) - 0.20202) < 1e-3
    assert metrics.compute_mfu(0, 990) == 0.0
    assert metrics.compute_mfu(-200, 990) == 0.0
    assert metrics.compute_mfu(100, 0) == 0.0           # guard against div-by-zero
    assert metrics.compute_mfu(2000, 990) == 1.0        # clamped


def test_mbu_and_roofline():
    assert abs(metrics.compute_mbu(2.0, 4.0) - 0.5) < 1e-9
    assert metrics.compute_mbu(-1.0, 4.0) == 0.0
    assert metrics.roofline_regime(1.5, 295) == "memory-bound"
    assert metrics.roofline_regime(455, 295) == "compute-bound"


def test_arithmetic_intensity_guards_invalid_inputs():
    assert metrics.arithmetic_intensity(10, 0) == 0.0
    assert metrics.arithmetic_intensity(10, -2) == 0.0
    assert metrics.arithmetic_intensity(-10, 2) == 0.0


def test_flag_util_lies():
    rows = [{"gpu_util_pct": 98, "mfu": 0.2}, {"gpu_util_pct": 95, "mfu": 0.8}, {"gpu_util_pct": 40, "mfu": 0.1}]
    lies = metrics.flag_util_lies(rows)
    assert len(lies) == 1 and lies[0]["gpu_util_pct"] == 98


def test_idle_waste():
    assert metrics.idle_waste_usd(12, 2.5) == 30.0
    assert metrics.idle_waste_usd(-5, 2.5) == 0.0
