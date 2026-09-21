"""超标判定规则: 依据污染物限值计算超标倍数并分级.

边界口径(全系统唯一事实来源, 明细/看板/导出/报表都必须以此为准):

- **监测值严格大于限值** 才判超标(``value > limit``); 监测值恰好等于限值
  (超标倍数正好为 1.0)判为**达标**, 不生成超标记录。
- ``is_exceedance`` 是唯一的超标判定入口, 其它任何模块都不得再拿
  "超标倍数 >= 1" 或监测值/限值自行比较, 避免边界处出现两个口径。
- 超标倍数仅用于超标记录的展示与分级; 落库精度(6 位小数)远高于监测值
  精度(1~2 位), 贴限值的达标数据(如 199.9/200 = 0.9995)舍入后仍严格
  小于 1.0, 不会呈现成 1.0 倍而被按倍数二次统计误判为超标。
"""

from .standards import get_limit, get_pollutant

# 超标倍数 -> 等级 (仅对已判定超标的记录使用)
LEVEL_THRESHOLDS = ((2.0, "severe"), (1.5, "moderate"), (1.0, "light"))

# 倍数落库精度: 远高于监测值精度(因子最多 2 位小数, 限值 >= 4),
# 保证任何达标记录舍入后仍严格小于 1.0, 与超标标志位恒等价。
RATIO_PRECISION = 6

LEVEL_ORDER = {"light": 1, "moderate": 2, "severe": 3}


def is_exceedance(value, limit):
    """唯一的超标边界判定: 监测值严格大于限值才超标, 等于限值判达标。"""
    return float(value) > float(limit)


def grade_ratio(ratio):
    """Map an exceedance ratio (value / limit) to a level code."""
    for threshold, level in LEVEL_THRESHOLDS:
        if ratio >= threshold:
            return level
    return "light"


def exceed_ratio(value, limit):
    """超标倍数, 按固定高精度舍入, 仅供展示/分级, 不作为判定依据。"""
    return round(float(value) / float(limit), RATIO_PRECISION)


def evaluate(pollutant_code, period, value):
    """Evaluate a single reading.

    Returns a dict: {"applicable", "exceeded", "limit", "ratio", "level", "unit", "message"}.
    ``applicable`` is False when the standard defines no limit for this period
    (e.g. PM2.5 has no 1-hour limit), in which case ``exceeded`` stays False.
    """
    pollutant = get_pollutant(pollutant_code)
    if pollutant is None:
        raise ValueError("未知监测因子: %s" % pollutant_code)
    if period not in ("hourly", "daily"):
        raise ValueError("未知数据周期: %s" % period)
    if value is None:
        raise ValueError("监测数值不能为空")

    limit = get_limit(pollutant_code, period)
    if limit is None:
        return {
            "applicable": False,
            "exceeded": False,
            "limit": None,
            "ratio": None,
            "level": None,
            "unit": pollutant["unit"],
            "message": "%s 未设定小时均值限值, 仅记录数值" % pollutant["label"],
        }

    ratio = exceed_ratio(value, limit)
    exceeded = is_exceedance(value, limit)
    return {
        "applicable": True,
        "exceeded": exceeded,
        "limit": limit,
        "ratio": ratio,
        "level": grade_ratio(ratio) if exceeded else None,
        "unit": pollutant["unit"],
        "message": None,
    }


def summarize(results):
    """Aggregate evaluation results for the batch entry form."""
    exceeded = [item for item in results if item["exceeded"]]
    return {
        "total": len(results),
        "exceeded_count": len(exceeded),
        "exceeded_pollutants": [item["pollutant"] for item in exceeded],
    }
