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
        assert rt["dsv_pcu_h"] == pytest.approx(rt["dsv_vc_ratio"] * rt["capacity_pcu_h"])
        if rt["chapter"] == 5:
            assert rt["dsv_vc_ratio"] == 0.70
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


EX552 = {"two_wheeler": 2640, "auto": 858, "car": 2239, "mini_bus": 11, "bus": 81,
         "lcv": 120, "tat": 10, "mat": 12, "tractor_trailer": 16}


def test_example_5_5_2_corrected():
    # The manual prints MAT 12 x 5.90 = 710 (should be 70.8), total 5228 and
    # LOS D. With correct arithmetic the flow is ~4582 PCU/h, V/C 0.67, LOS C.
    q = hcm.flow_pcu(EX552, "divided_8lane")["flow_pcu_h"]
    assert q == pytest.approx(4582, abs=2)
    assert hcm.los_from_vc(q / 6800, divided=True) == "C"
    assert hcm.los_from_vc(5228 / 6800, divided=True) == "D"   # the printed (wrong) figure


def test_example_5_5_3_needs_six_lane():
    demand = 2638
    assert demand > hcm.ROAD_TYPES["divided_4lane"]["dsv_pcu_h"]
    assert demand <= hcm.ROAD_TYPES["divided_6lane"]["dsv_pcu_h"]


EX554 = {"two_wheeler": 369, "auto": 168, "car": 236, "bus": 58, "mini_bus": 20, "lcv": 78,
         "tat": 25, "mat": 75, "tractor_trailer": 2, "bicycle": 25, "cycle_rickshaw": 12}


def test_example_5_5_4_spare_capacity():
    # Manual prints 1459 and 433; Table 5.3 medians give 1453.7 -> 436 spare.
    q = hcm.flow_pcu(EX554, "divided_4lane")["flow_pcu_h"]
    assert q == pytest.approx(1453.7, abs=0.5)
    assert round(hcm.ROAD_TYPES["divided_4lane"]["dsv_pcu_h"] - q) == 436


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
def test_width_factor_overlap_and_kerb_shy_counted_once():
    # clear effective width 7.0 - 2 x 0.25 = 6.5; kerb obstruction [0, 1.2]
    # (merged overlap) leaves 1.45 .. 6.75 = 5.3 m usable
    fw = ext.width_factor([(0.0, 1.0), (0.7, 1.2)], 7.0, 2700, True)
    assert fw["obstruction_width_m"] == pytest.approx(1.2)
    assert fw["usable_width_m"] == pytest.approx(5.3)
    assert fw["F_W"] == pytest.approx(5.3 / 6.5)


def test_width_factor_mid_road():
    fw = ext.width_factor([(3.0, 3.4)], 7.0, 2700, True)        # loses 0.4 + 2 x 0.25
    assert fw["F_W"] == pytest.approx(5.6 / 6.5)


def test_width_factor_table_slope():
    fw = ext.width_factor([(0.0, 1.0)], 7.0, 2700, True, method="table_slope")
    assert fw["F_W"] == pytest.approx((2700 - 1.0 * 1500 / 3.5) / 2700)


def test_width_factor_no_obstruction_is_one():
    assert ext.width_factor([], 7.0, 2700, True)["F_W"] == 1.0


def test_roughness_not_applied_on_base_quality_road():
    assert ext.roughness_factor(2.5, 56)["F_R"] == 1.0


def test_parking_never_in_width():
    assert "illegal_parking" not in ext.WIDTH_CLASSES


def test_core_two_capacities():
    inp = core.resolve_road_inputs({"road_type": "divided_4lane", "total_width_m": 7.0,
                                    "bus_stop": "kerbside_low", "observed_volume_pcu_h": 1500})
    cap = core.compute_capacity(inp, [(0.0, 1.0)], parking_detected=True)
    assert cap["c_hcm"] == pytest.approx(2700 * 0.70 * 0.80)           # parking (assumed class) + bus stop
    assert cap["c_ext"] == pytest.approx(cap["c_hcm"] * 5.5 / 6.5)
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


# ---------------- regressions from the independent review ----------------
import json

from road_analyzer.digital_twin_engine import generate_twin_data
from road_analyzer.roadrunner_export import lateral_to_t


def _result(c0, c, volume=None, v=56.6, lanes=2):
    return {"base_capacity_pcu_h": c0, "reduced_capacity_pcu_h": c, "capacity_loss_pct": 0,
            "capacity_basis": {"operating_speed_kmh": v}, "road_config": {"num_lanes": lanes},
            "capacity_calculation": {"roughness": {"speed_ratio": 1.0}},
            "level_of_service": {"observed_volume_pcu_h": volume} if volume else None}


def test_los_band_edges():
    assert hcm.los_from_vc(0.15, divided=True) == "B"       # Table 5.7: A is "< 0.15"
    assert hcm.los_from_vc(0.149, divided=True) == "A"
    assert hcm.los_from_vc(1.0, divided=True) == "E"
    assert hcm.los_from_vc(1.01, divided=True) == "F"


def test_full_blockage_is_json_safe_and_twin_survives():
    inp = core.resolve_road_inputs({"road_type": "divided_4lane", "total_width_m": 7.0,
                                    "observed_volume_pcu_h": 1500})
    cap = core.compute_capacity(inp, [(0.0, 7.0)], parking_detected=False)
    assert cap["c_ext"] == 0 and cap["los"]["los_ext"] == "F" and cap["los"]["vc_ext"] is None
    json.dumps(cap["los"], allow_nan=False)
    t = generate_twin_data(_result(2700, 0.0, 1500))
    assert t["defect"]["state"] == "fully blocked" and t["defect"]["shockwave_kmh"] < 0
    json.dumps(t, allow_nan=False)


def test_twin_delay_formula():
    # q = 2400, C = 2000, T = 1 h: mean delay = (q - C) T / (2 C) = 6.0 min
    t = generate_twin_data(_result(2700, 2000, 2400))
    assert t["defect"]["mean_queue_delay_min"] == pytest.approx(6.0, abs=0.05)


def test_twin_demand_above_c0_is_consistent():
    t = generate_twin_data(_result(2700, 2000, 3000))
    assert t["warnings"] and t["arrival_pcu_h"] == 2700
    assert t["ideal"]["queue_growth_pcu_h"] == 0
    d = t["defect"]
    assert d["queue_growth_pcu_h"] == pytest.approx(700)
    assert (d["queue_after_horizon_pcu"] > 0) == (d["queue_length_after_horizon_m"] > 0)


def test_lateral_to_t_divided_stays_on_road():
    for lat in (0.0, 1.0, 3.5, 6.0, 7.0):
        t = lateral_to_t(lat, 7.0, 2, divided=True)
        assert -7.0 <= t <= 0.0
    assert lateral_to_t(0.0, 7.0, 2, divided=True) == 0.0          # image-left = reference line


def test_lateral_to_t_undivided_not_mirrored():
    assert lateral_to_t(0.0, 7.0, 2, divided=False) == pytest.approx(3.5)   # image-left = +t edge
    assert lateral_to_t(7.0, 7.0, 2, divided=False) == pytest.approx(-3.5)


def test_measured_speed_kept_for_undivided_twin():
    inp = core.resolve_road_inputs({"road_type": "undivided_2lane", "total_width_m": 7.5,
                                    "operating_speed_kmh": 42})
    assert inp["c0"] == 2400 and inp["v_ref"] == 42


def test_no_free_cars_does_not_crash():
    r = hcm.operating_speed([40, 42, 45], [2, 3, 4])
    assert r["operating_speed_kmh"] is None and r["warning"]


def test_first_vehicle_headway_not_counted_as_free():
    vs = [{"type": "car", "t_in": 0.0, "t_out": 5.0}, {"type": "car", "t_in": 2.0, "t_out": 7.0}]
    fv.add_speeds_and_headways(vs, 60)
    assert vs[0]["headway_s"] is None
    assert fv.capacity_from_operating_speed(vs, "divided_4lane")["capacity_pcu_h"] is None


def test_partial_last_period_dropped():
    vs = [{"type": "car", "t_in": float(t), "t_out": t + 4.0} for t in range(0, 420, 2)]
    fv.add_speeds_and_headways(vs, 60)
    periods = fv.five_minute_periods(vs, "divided_4lane", 60)
    assert len(periods) == 1 and periods[0]["flow_pcu_h"] == pytest.approx(1800)


# ---------------- Chapter 2: single and intermediate lane ----------------
def test_ch2_base_capacity_at_standard_width():
    assert hcm.base_capacity("single_lane", None, 3.75)["c0_pcu_h"] == pytest.approx(800)
    assert hcm.base_capacity("intermediate_lane", None, 5.5)["c0_pcu_h"] == pytest.approx(2150)


def test_ch2_table_2_6_width_factor():
    assert hcm.carriageway_width_factor("single_lane", 4.0)["f_w"] == pytest.approx(1.24)
    assert hcm.carriageway_width_factor("intermediate_lane", 5.7)["f_w"] == pytest.approx(1.06)
    clamp = hcm.carriageway_width_factor("single_lane", 3.0)
    assert clamp["f_w"] == pytest.approx(0.76) and clamp["note"]
    assert hcm.base_capacity("single_lane", None, 4.2)["c0_pcu_h"] == pytest.approx(800 * 1.43)


def test_ch2_speed_equations():
    assert hcm.base_capacity("single_lane", 50, 3.75)["c0_pcu_h"] == pytest.approx(187 + 12.4 * 50)
    assert hcm.base_capacity("intermediate_lane", 75, 5.5)["c0_pcu_h"] == pytest.approx(830 + 16.4 * 75)


def test_ch2_los_tables():
    assert hcm.los_from_vc(0.15, "single") == "A"          # Table 2.10: A is <= 0.15
    assert hcm.los_from_vc(0.31, "single") == "C"
    assert hcm.los_from_vc(0.81, "single") == "E"
    assert hcm.los_from_vc(0.25, "intermediate") == "B"    # Table 2.9: A is < 0.25
    assert hcm.los_from_vc(0.60, "intermediate") == "C"
    assert hcm.los_from_vc(1.01, "intermediate") == "F"


def test_ch2_pcu_table_2_4():
    assert hcm.pcu_values("single_lane")["two_wheeler"] == 0.25
    assert hcm.pcu_values("intermediate_lane")["two_wheeler"] == 0.30
    assert hcm.flow_pcu({"bus": 10}, "intermediate_lane")["table"] == "2.4"


def test_ch2_roughness_uses_eq_2_19_2_20():
    f = ext.roughness_factor(7.0, 50, "single_lane")["F_R"]
    assert f == pytest.approx((945 - 25 * 7) / (945 - 25 * 3))
    f = ext.roughness_factor(5.0, 75, "intermediate_lane")["F_R"]
    assert f == pytest.approx((2956 - 199 * 5) / (2956 - 199 * 3))


def test_ch2_full_pipeline_and_los_table_ref():
    inp = core.resolve_road_inputs({"road_type": "single_lane", "total_width_m": 3.75,
                                    "observed_volume_pcu_h": 300, "bus_stop": "kerbside_low"})
    assert inp["v_ref"] == 50 and inp["lanes"] == 1
    cap = core.compute_capacity(inp, [], False)
    assert cap["c_hcm"] == pytest.approx(640)
    assert cap["los"]["table"] == "2.10" and cap["los"]["los_hcm"] == "C"   # 300/640 = 0.47
    assert any("Chapter 2 has no side-friction" in n for n in cap["notes"])


def test_ch2_field_method_a_and_se_rejected():
    vs = [{"type": "car", "t_in": 10.0 * i, "t_out": 10.0 * i + 4.32} for i in range(120)]
    fv.add_speeds_and_headways(vs, 60)
    a = fv.capacity_from_operating_speed(vs, "single_lane")
    assert a["capacity_pcu_h"] == pytest.approx(187 + 12.4 * a["operating_speed_kmh"])
    with pytest.raises(ValueError):
        fv.five_minute_periods(vs, "single_lane", 60, "se")


# ---------------- detector post-processing ----------------
def test_cross_class_duplicate_keeps_more_confident():
    dets = [{"cls_name": "barricade", "conf": 0.8, "xyxy": (0, 0, 100, 100)},
            {"cls_name": "illegal_parking", "conf": 0.6, "xyxy": (5, 5, 100, 100)},
            {"cls_name": "pothole", "conf": 0.7, "xyxy": (200, 200, 260, 240)},
            {"cls_name": "vehicle", "conf": 0.9, "xyxy": (0, 0, 100, 100)}]
    kept, dropped = core.suppress_cross_class(dets)
    names = sorted(d["cls_name"] for d in kept)
    assert dropped == 1 and names == ["barricade", "pothole", "vehicle"]


def test_class_thresholds_file_overrides_defaults(tmp_path):
    (tmp_path / "class_thresholds.json").write_text('{"pothole": 0.3, "cart": 5}')
    t = core.load_class_thresholds(str(tmp_path / "best.pt"))
    assert t["pothole"] == 0.3 and t["cart"] == core.CONF_THRESHOLDS["cart"]
