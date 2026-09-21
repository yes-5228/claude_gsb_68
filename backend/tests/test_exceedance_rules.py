"""超标判定规则的单元测试."""
import pytest

from app.domain import exceedance_rules


def test_value_below_limit_is_not_exceeded():
    result = exceedance_rules.evaluate("PM25", "daily", 60.0)
    assert result["applicable"] is True
    assert result["exceeded"] is False
    assert result["limit"] == 75.0
    assert result["level"] is None


def test_value_equal_to_limit_is_compliant():
    # 取等号即达标: 恰好等于限值不超标、不分级
    result = exceedance_rules.evaluate("SO2", "hourly", 500.0)
    assert result["exceeded"] is False
    assert result["level"] is None
    assert result["ratio"] == 1.0
    assert exceedance_rules.is_exceedance(500.0, 500.0) is False


def test_value_just_above_limit_is_exceeded():
    result = exceedance_rules.evaluate("SO2", "hourly", 500.1)
    assert result["exceeded"] is True
    assert result["level"] == "light"
    assert result["ratio"] > 1.0


def test_near_limit_compliant_ratio_is_not_rounded_up_to_one():
    # 199.9/200 = 0.9995: 旧实现按 3 位小数舍入成 1.0, 会被"倍数>=1"的
    # 汇总误判为超标; 提高精度后必须仍严格小于 1.0 且与标志位一致
    result = exceedance_rules.evaluate("O3", "hourly", 199.9)
    assert result["exceeded"] is False
    assert result["ratio"] < 1.0
    # 不变量: 倍数 >= 1 当且仅当判定超标, 任何统计口径都不能据此分叉
    assert (result["ratio"] >= 1.0) is result["exceeded"]


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
