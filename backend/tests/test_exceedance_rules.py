"""超标判定规则的单元测试."""
import pytest

from app.domain import exceedance_rules


def test_value_below_limit_is_not_exceeded():
    result = exceedance_rules.evaluate("PM25", "daily", 60.0)
    assert result["applicable"] is True
    assert result["exceeded"] is False
    assert result["limit"] == 75.0
    assert result["level"] is None


def test_light_moderate_and_severe_grading():
    assert exceedance_rules.evaluate("PM25", "daily", 80.0)["level"] == "light"
    assert exceedance_rules.evaluate("PM25", "daily", 120.0)["level"] == "moderate"
    assert exceedance_rules.evaluate("PM25", "daily", 200.0)["level"] == "severe"


def test_ratio_is_computed_against_limit():
    result = exceedance_rules.evaluate("NO2", "hourly", 250.0)
    assert result["exceeded"] is True
    assert result["limit"] == 200.0
    assert result["ratio"] == 1.25
    assert result["level"] == "light"


def test_period_without_limit_is_recorded_but_not_flagged():
    result = exceedance_rules.evaluate("PM10", "hourly", 400.0)
    assert result["applicable"] is False
    assert result["exceeded"] is False
    assert result["limit"] is None
    assert "未设定小时均值限值" in result["message"]


def test_unknown_pollutant_raises():
    with pytest.raises(ValueError):
        exceedance_rules.evaluate("XX", "daily", 1.0)


def test_value_equal_to_limit_is_not_exceeded():
    """取等号口径: 监测值恰好等于限值时倍数恰为 1, 结论为达标。"""
    for code, period, limit in (
        ("PM25", "daily", 75.0),
        ("NO2", "hourly", 200.0),
        ("CO", "daily", 4.0),
        ("SO2", "hourly", 500.0),
    ):
        result = exceedance_rules.evaluate(code, period, limit)
        assert result["exceeded"] is False
        assert result["level"] is None
        assert result["ratio"] == 1.0


def test_value_just_below_limit_that_rounds_to_one_is_not_exceeded():
    """真实倍数 < 1 但三位舍入后恰为 1.00 的贴边记录仍判达标, 统计不得翻成超标。"""
    result = exceedance_rules.evaluate("PM25", "daily", 74.9996)  # 0.9999947 -> 舍入 1.0
    assert result["ratio"] == 1.0
    assert result["exceeded"] is False
    assert result["level"] is None


def test_value_just_above_limit_that_rounds_to_one_is_exceeded():
    """真实倍数 > 1 但舍入后显示 1.00 的记录必须判超标, 不能被漏判。"""
    result = exceedance_rules.evaluate("CO", "hourly", 10.0004)  # 1.00004 -> 舍入 1.0
    assert result["ratio"] == 1.0
    assert result["exceeded"] is True
    assert result["level"] == "light"


def test_grading_thresholds_promote_at_equal_boundary():
    """分级阈值沿用「不小于」口径: 倍数恰为 1.5/2.0 整档即升档。"""
    assert exceedance_rules.grade_ratio(1.0) == "light"
    assert exceedance_rules.grade_ratio(1.5) == "moderate"
    assert exceedance_rules.grade_ratio(2.0) == "severe"
    assert exceedance_rules.evaluate("PM25", "daily", 112.5)["level"] == "moderate"
    assert exceedance_rules.evaluate("PM25", "daily", 150.0)["level"] == "severe"


def test_boundary_predicates_share_one_rule():
    """值形式与倍数形式的谓词对同一边界给出同一结论。"""
    assert exceedance_rules.is_exceeded_ratio(1.0) is False
    assert exceedance_rules.is_exceeded_ratio(1.0000001) is True
    assert exceedance_rules.is_exceeded_value(75.0, 75.0) is False
    assert exceedance_rules.is_exceeded_value(75.1, 75.0) is True


def test_summarize_counts_exceeded_items():
    results = [
        exceedance_rules.evaluate("PM25", "daily", 10.0),
        exceedance_rules.evaluate("PM25", "daily", 90.0),
    ]
    for item, code in zip(results, ("PM25", "PM25")):
        item["pollutant"] = code
    summary = exceedance_rules.summarize(results)
    assert summary["total"] == 2
    assert summary["exceeded_count"] == 1
