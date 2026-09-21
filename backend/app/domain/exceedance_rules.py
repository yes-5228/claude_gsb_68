"""超标判定规则: 依据污染物限值计算超标倍数并分级.

限值边界口径(全系统唯一来源, 明细 / 看板 / 导出 / 报表必须一致):

- 超标判定一律基于**未舍入的真实超标倍数** ``value / limit``, 采用严格大于:
  ``真实倍数 > 1`` (等价于 ``监测值 > 限值``) 才判超标。
- **监测值恰好等于限值时, 真实倍数恰为 1.0, 结论为「达标」, 不生成超标记录。**
- ``exceed_ratio`` 仅在判定之后做三位小数舍入, 用于展示与导出; 任何统计、筛选
  或分级都不得拿舍入后的倍数反推是否超标, 否则贴边记录会与明细结论不一致。
- 分级同样基于未舍入倍数, 阈值取「不小于」(沿用既有口径): 倍数 ``>= 2``
  重度、``>= 1.5`` 中度、其余(即 ``1 < 倍数 < 1.5``)轻度。
"""
from .standards import get_limit, get_pollutant

# 超标倍数 -> 等级 (基于未舍入倍数; 阈值取不小于, 倍数 1.5/2.0 整档时即升档)
LEVEL_THRESHOLDS = ((2.0, "severe"), (1.5, "moderate"), (1.0, "light"))

LEVEL_ORDER = {"light": 1, "moderate": 2, "severe": 3}

# 超标倍数的判定下沿: 真实倍数严格大于该值才算超标; 恰好等于(值=限值)算达标
EXCEEDED_RATIO_MIN = 1.0

# 超标倍数展示精度; 仅用于展示/导出, 不参与任何判定
RATIO_PRECISION = 3


def is_exceeded_ratio(ratio):
    """限值边界唯一谓词: 真实超标倍数严格大于 1 才算超标。

    入参必须是未舍入的 ``value / limit``; 倍数恰为 1(监测值恰好等于限值)
    时返回 False(达标)。明细标志位、看板/报表计数及超标单的生成都以此为准。
    """
    return ratio > EXCEEDED_RATIO_MIN


def is_exceeded_value(value, limit):
    """限值边界的监测值形式: 监测值严格大于限值才算超标, 等于限值算达标。"""
    return is_exceeded_ratio(float(value) / float(limit))


def grade_ratio(ratio):
    """Map an (unrounded) exceedance ratio (value / limit) to a level code.

    Level cut-offs use "ratio >= threshold" (1.5/2.0 at the boundary promotes).
    Only invoked for readings already established as exceeded (ratio > 1).
    """
    for threshold, level in LEVEL_THRESHOLDS:
        if ratio >= threshold:
            return level
    return "light"


def evaluate(pollutant_code, period, value):
    """Evaluate a single reading.

    Returns a dict: {"applicable", "exceeded", "limit", "ratio", "level", "unit", "message"}.
    ``applicable`` is False when the standard defines no limit for this period
    (e.g. PM2.5 has no 1-hour limit), in which case ``exceeded`` stays False.

    ``exceeded``/``level`` are derived from the unrounded ratio via the shared
    boundary predicates; ``ratio`` is rounded afterwards for display only.
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

    # 先按真实倍数完成全部判定, 再做展示用舍入, 保证各处口径一致
    exact_ratio = float(value) / float(limit)
    exceeded = is_exceeded_ratio(exact_ratio)
    ratio = round(exact_ratio, RATIO_PRECISION)
    return {
        "applicable": True,
        "exceeded": exceeded,
        "limit": limit,
        "ratio": ratio,
        "level": grade_ratio(exact_ratio) if exceeded else None,
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
