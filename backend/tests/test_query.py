"""数据查询与统计接口测试."""


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


def test_value_equal_to_limit_is_consistent_across_detail_dashboard_and_export(
    client, station, entry_payload
):
    """取等号记录(PM2.5 日均值恰为限值 75)在明细/看板/统计/导出口径一致, 均判达标。"""
    client.post(
        "/api/measurements/entries",
        json=entry_payload(
            station.id,
            measured_at="2026-09-01 10:00",
            period="daily",
            entries=[{"pollutant": "PM25", "value": 75.0}, {"pollutant": "SO2", "value": 900.0}],
        ),
    )

    # 明细: 等于限值 -> 达标, 倍数恰为 1.0
    boundary = client.get(
        "/api/query/measurements?pollutant=PM25"
    ).get_json()["items"][0]
    assert boundary["exceed_ratio"] == 1.0
    assert boundary["is_exceeded"] is False

    # 汇总(查询页): 仅 1 条超标, 等于限值的不算
    query_summary = client.get("/api/query/measurements").get_json()["summary"]
    assert query_summary["total"] == 2
    assert query_summary["exceeded_count"] == 1

    # 看板(运行概览): 与查询页同一个数
    overview = client.get("/api/meta/overview").get_json()
    assert overview["measurements"]["exceeded_count"] == 1

    # 分组统计: 贴边因子超标数为 0
    stats = client.get("/api/query/statistics?group_by=pollutant&metric=count").get_json()
    exceeded = {item["key"]: item["exceeded_count"] for item in stats["items"]}
    assert exceeded == {"PM25": 0, "SO2": 1}

    # 仅超标筛选: 等于限值的记录不出现
    only_exceeded = client.get("/api/query/measurements?is_exceeded=true").get_json()
    assert only_exceeded["total"] == 1
    assert only_exceeded["items"][0]["pollutant"] == "SO2"

    # 导出: PM2.5 行的“是否超标”列为“否”, 与明细一致
    csv_text = client.get("/api/query/export?pollutant=PM25").get_data(as_text=True)
    row = csv_text.strip().splitlines()[1]
    assert "否" in row and "是" not in row


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
