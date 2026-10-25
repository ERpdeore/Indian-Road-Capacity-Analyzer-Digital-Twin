"""
Checks the code against Indo-HCM 2017 Chapter 5's own tables and worked
examples (Section 5.5). Run:  cd road_analyzer_deploy && python -m pytest -q
"""
import math
import random

import pytest

from road_analyzer import indo_hcm as hcm
from road_analyzer import extensions as ext
from road_analyzer import field_validation as fv
from road_analyzer import core

EX551 = {"two_wheeler": 1441, "auto": 379, "car": 1985, "mini_bus": 44, "bus": 56,
         "lcv": 15, "tat": 42, "bicycle": 21, "cycle_rickshaw": 21}


# ---------------- tables ----------------
def test_table_5_4_dsv_is_70_percent_of_capacity():
    for rt in hcm.ROAD_TYPES.values():
        assert rt["dsv_pcu_h"] == pytest.approx(0.70 * rt["capacity_pcu_h"])
        assert rt["capacity_pcu_h"] == pytest.approx(rt["lane_capacity_pcu_h"] * rt["lanes"])


@pytest.mark.parametrize("v,expected", [(55, 1317), (60, 1417), (65, 1518), (70, 1619), (75, 1719)])
def test_table_5_5_from_eq_5_4(v, expected):
    assert round(hcm.lane_capacity_from_operating_speed(v)) == pytest.approx(expected, abs=1)


def test_eq_5_4_not_used_for_undivided():
    b = hcm.base_capacity("undivided_2lane", 60)
    assert b["method"] == "Table 5.4" and b["c0_pcu_h"] == 2400


def test_dynamic_pcu_bus_reproduces_table_order_of_magnitude():
    # bus slower than car by ~14 % -> PCU close to the Table 5.3 median 4.6
    assert hcm.dynamic_pcu(v_subject_kmh=37.0, v_car_kmh=43.0, vehicle="bus") == pytest.approx(4.6, abs=0.1)


# ---------------- Example 5.5.1 (six-lane divided) ----------------
def test_example_5_5_1_dynamic_pcu_flow():
    # Manual prints 3153, but its own column of products sums to ~3214;
    # with Table 5.3 medians the exact sum is 3205.6.
    assert hcm.flow_pcu(EX551, "divided_6lane")["flow_pcu_h"] == pytest.approx(3205.6, abs=0.5)


def test_example_5_5_1_stream_equivalency():
    shares, n = hcm.se_shares(EX551)
    se = hcm.stream_equivalency_factor(True, shares, n)
    assert se == pytest.approx(0.755, abs=0.002)          # manual: 0.755
    assert se * n == pytest.approx(3023, abs=6)            # manual: 3023 PCU/h


def test_example_5_5_1_capacity_and_los():
    a = hcm.actual_capacity(4200)
    b = hcm.actual_capacity(4200, bus_stop="kerbside_high")
    assert a["c_pcu_h"] == 4200 and b["c_pcu_h"] == pytest.approx(2520)
    assert hcm.los_from_vc(3023 / 4200, divided=True) == "C"   # 0.72
    assert hcm.los_from_vc(3023 / 2520, divided=True) == "F"


def test_example_5_5_2_los_d():
    assert hcm.los_from_vc(5228 / 6800, divided=True) == "D"    # 0.77


def test_example_5_5_3_needs_six_lane():
    demand = 2638
    assert demand > hcm.ROAD_TYPES["divided_4lane"]["dsv_pcu_h"]
    assert demand <= hcm.ROAD_TYPES["divided_6lane"]["dsv_pcu_h"]


def test_example_5_5_4_spare_capacity():
    # 1890 - 1459 = 431 (the manual subtracts 1457 and prints 433)
    assert hcm.ROAD_TYPES["divided_4lane"]["dsv_pcu_h"] - 1459 == 431


def test_parking_classes():
    assert hcm.parking_class_by_length(80, 400) == "len_lt25"
    assert hcm.parking_class_by_length(150, 400) == "len_25_50"
    assert hcm.parking_class_by_manoeuvres(150, 0.4) == "man_le500"
    assert hcm.parking_class_by_manoeuvres(250, 0.4) == "man_gt500"


def test_width_check():
    assert hcm.check_road_width("divided_4lane", 7.3) is None
    assert hcm.check_road_width("divided_4lane", 9.0) is not None
    assert hcm.check_road_width("undivided_2lane", 6.5) is not None   # < 7 m not studied


# ---------------- extensions ----------------
def test_width_factor_overlap_and_shy():
    fw = ext.width_factor([(0.0, 1.0), (0.7, 1.2)], 7.0, 2700, True)
    assert fw["obstruction_width_m"] == pytest.approx(1.2)
    assert fw["blocked_with_shy_m"] == pytest.approx(1.45)   # one free side
    assert fw["F_W"] == pytest.approx((7.0 - 1.45) / 7.0)


def test_width_factor_table_slope():
    fw = ext.width_factor([(0.0, 1.0)], 7.0, 2700, True, method="table_slope")
    assert fw["F_W"] == pytest.approx((2700 - 1.25 * 1500 / 3.5) / 2700)


def test_roughness_not_applied_on_base_quality_road():
    assert ext.roughness_factor(2.5, 56)["F_R"] == 1.0


def test_parking_never_in_width():
    assert "illegal_parking" not in ext.WIDTH_CLASSES


def test_core_two_capacities():
    inp = core.resolve_road_inputs({"road_type": "divided_4lane", "total_width_m": 7.0,
                                    "bus_stop": "kerbside_low", "observed_volume_pcu_h": 1500})
    cap = core.compute_capacity(inp, [(0.0, 1.0)], parking_detected=True)
    assert cap["c_hcm"] == pytest.approx(2700 * 0.70 * 0.80)           # parking (assumed class) + bus stop
    assert cap["c_ext"] == pytest.approx(cap["c_hcm"] * (7 - 1.25) / 7)
    assert cap["los"]["table"] == "5.7"


# ---------------- field validation ----------------
def test_operating_speed_filters_free_cars():
    speeds = [40 + i * 0.2 for i in range(150)]
    heads = [10 if i % 2 else 3 for i in range(150)]     # half of the cars are following
    r = hcm.operating_speed(speeds, heads)
    assert r["n_free_cars"] == 75 and r["warning"]


def test_greenshields_recovers_known_capacity():
    vf, kj = 60.0, 200.0                                  # true capacity 3000
    rnd = random.Random(1)
    periods = []
    for k in [10, 20, 35, 50, 65, 80, 90, 100, 110]:
        v = vf * (1 - k / kj) + rnd.uniform(-0.5, 0.5)
        periods.append({"density_pcu_km": k, "sms_kmh": v, "flow_pcu_h": k * v})
    fit = fv.greenshields_fit(periods)
    assert fit["capacity_pcu_h"] == pytest.approx(3000, rel=0.03)


def test_error_metrics():
    m = fv.error_metrics([110, 90], [100, 100])
    assert m["mape_pct"] == pytest.approx(10) and m["bias"] == pytest.approx(0) and m["n"] == 2
