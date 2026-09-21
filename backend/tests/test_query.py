"""数据查询与统计接口测试."""
from app.models import Exceedance, Measurement


def _seed_boundary_batch(client, station, entry_payload):
    """同一时刻各因子: 2 条贴限值(达标) + 2 条超标, 覆盖四舍五入到 1.0 的场景。"""
    client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            measured_at="2026-09-01 10:00",
            period="hourly",
            entries=[
                {"pollutant": "O3", "value": 200.0},    # 恰好等于限值 -> 达标
                {"pollutant": "NO2", "value": 199.9},   # 0.9995 倍 -> 达标
                {"pollutant": "SO2", "value": 600.0},   # 1.2 倍 -> 超标
                {"pollutant": "CO", "value": 12.0},     # 1.2 倍 -> 超标
            ],
        ),
    )


def test_boundary_counts_agree_across_detail_dashboard_report_and_export(
    client, station, entry_payload
):
    _seed_boundary_batch(client, station, entry_payload)

    # 明细: 标志位筛选与同页汇总必须一致
    measurements = client.get("/api/measurements?is_exceeded=true").get_json()
    query = client.get("/api/query/measurements?is_exceeded=true").get_json()
    assert measurements["total"] == 2
    assert measurements["summary"]["exceeded_count"] == 2
    assert query["total"] == 2
    assert query["summary"]["exceeded_count"] == 2

    # 看板: 监测数据超标数 == 超标记录数
    overview = client.get("/api/meta/overview").get_json()
    assert overview["measurements"]["exceeded_count"] == 2
    assert overview["exceedances"]["total"] == 2
    assert overview["exceedances"]["pending"] == 2

    # 聚合报表: 各分组的超标数合计
    stats = client.get("/api/query/statistics?group_by=pollutant&metric=count").get_json()
    assert stats["totals"]["exceeded_count"] == 2

    # 落库不变量 1: 监测值严格小于限值的记录, 倍数舍入后仍须 < 1
    # (旧实现把 199.9/200=0.9995 舍入成 1.0, 给了"倍数>=1"二次统计可乘之机)
    rounded_up = (
        Measurement.query.filter(Measurement.value < Measurement.limit_value)
        .filter(Measurement.exceed_ratio >= 1.0)
        .count()
    )
    assert rounded_up == 0
    # 落库不变量 2: 标志位永远与"值 > 限值"的边界口径一致
    assert all(
        bool(row.is_exceeded) is (row.value > row.limit_value)
        for row in Measurement.query.filter(Measurement.limit_value.isnot(None)).all()
    )
    # 恰好等于限值: 倍数展示为 1.0, 但取等号判达标、以标志位为准, 不建超标单
    exact = Measurement.query.filter_by(pollutant="O3", value=200.0).one()
    assert exact.is_exceeded is False
    assert exact.exceed_ratio == 1.0
    assert Exceedance.query.count() == 2

    # 导出: 全量 4 行中"是否超标=是"恰为 2 行
    csv_text = client.get("/api/query/export").get_data(as_text=True)
    rows = csv_text.lstrip("\ufeff").strip().splitlines()[1:]
    assert len(rows) == 4
    assert sum(1 for line in rows if ",是," in line) == 2


def _seed_two_days(client, station, entry_payload):
    client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            measured_at="2026-09-01 10:00",
            period="daily",
            entries=[{"pollutant": "PM25", "value": 60.0}, {"pollutant": "SO2", "value": 900.0}],
        ),
    )
    client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            measured_at="2026-09-02 10:00",
            period="daily",
            entries=[{"pollutant": "PM25", "value": 100.0}, {"pollutant": "SO2", "value": 100.0}],
        ),
    )


def test_query_by_date_range_and_values(client, station, entry_payload):
    _seed_two_days(client, station, entry_payload)

    all_rows = client.get("/api/query/measurements").get_json()
    assert all_rows["total"] == 4
    assert all_rows["summary"]["exceed_rate"] == 0.5

    day_range = client.get(
        "/api/query/measurements?date_from=2026-09-02&date_to=2026-09-02"
    ).get_json()
    assert day_range["total"] == 2

    value_range = client.get("/api/query/measurements?min_value=200").get_json()
    assert value_range["total"] == 1

    filters = client.get("/api/query/measurements?is_exceeded=true").get_json()
    assert filters["summary"]["exceeded_count"] == 2
    assert filters["summary"]["exceed_rate"] == 1.0
    assert filters["applied_filters"]["pollutants"] == []


def test_query_rejects_invalid_filters(client):
    assert client.get("/api/query/measurements?pollutant=XX").status_code == 422
    assert client.get("/api/query/measurements?date_from=not-a-date").status_code == 422
    assert (
        client.get(
            "/api/query/measurements?date_from=2026-09-05&date_to=2026-09-01"
        ).status_code
        == 422
    )
    assert client.get("/api/query/statistics?group_by=unknown").status_code == 422


def test_statistics_by_pollutant_and_metric(client, station, entry_payload):
    _seed_two_days(client, station, entry_payload)
    body = client.get("/api/query/statistics?group_by=pollutant&metric=avg").get_json()
    assert body["group_by"] == "pollutant"
    values = {item["key"]: item["value"] for item in body["items"]}
    assert values["PM25"] == 80.0
    assert values["SO2"] == 500.0

    counts = client.get("/api/query/statistics?group_by=pollutant&metric=count").get_json()
    assert {item["key"]: item["value"] for item in counts["items"]} == {"PM25": 2.0, "SO2": 2.0}

    exceeded = {item["key"]: item["exceeded_count"] for item in counts["items"]}
    assert exceeded == {"PM25": 1, "SO2": 1}


def test_statistics_by_day_is_chronological(client, station, entry_payload):
    _seed_two_days(client, station, entry_payload)
    body = client.get("/api/query/statistics?group_by=day&metric=avg").get_json()
    assert [item["key"] for item in body["items"]] == ["2026-09-01", "2026-09-02"]
    assert body["totals"]["count"] == 4


def test_statistics_by_station_uses_station_labels(client, station, second_station, entry_payload):
    _seed_two_days(client, station, entry_payload)
    client.post(
        "/api/measurements/entries",
        json=entry_payload(second_station.id, entries=[{"pollutant": "PM25", "value": 30.0}]),
    )
    body = client.get("/api/query/statistics?group_by=station&metric=count").get_json()
    labels = {item["key"]: item["label"] for item in body["items"]}
    assert labels["TEST-002"] == "TEST-002 工业园监测点"


def test_query_export_respects_filters(client, station, entry_payload):
    _seed_two_days(client, station, entry_payload)
    response = client.get("/api/query/export?pollutant=PM25")
    assert response.status_code == 200
    lines = response.get_data(as_text=True).strip().splitlines()
    assert len(lines) == 3
    assert lines[0].startswith("\ufeff站点编码")
    assert "PM2.5" in lines[1]


def test_query_options_payload(client):
    body = client.get("/api/query/options").get_json()
    assert "day" in body["group_by"]
    assert {item["value"] for item in body["pollutants"]} == {"PM25", "PM10", "SO2", "NO2", "CO", "O3"}
