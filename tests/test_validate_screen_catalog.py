from scripts.validate_screen_catalog import duplicate_json_keys, validate_catalog


def _region():
    return {"image": "screen.png", "left": 0, "top": 0, "right": 1280, "bottom": 720}


def test_accepts_consistent_catalog():
    result = validate_catalog(
        {"screens": {"sample": _region()}, "targets": {"実行": _region()}},
        screen_targets={"sample": {"実行"}}, coordinates={"sample": {"実行": (640, 600)}},
    )
    assert result["status"] == "ok"


def test_rejects_out_of_bounds_region_and_coordinate():
    bad = _region()
    bad["right"] = 1281
    result = validate_catalog(
        {"screens": {"sample": bad}, "targets": {"実行": _region()}},
        screen_targets={"sample": {"実行"}}, coordinates={"sample": {"実行": (1280, 600)}},
    )
    assert result["status"] == "error"
    assert any("region_out_of_bounds" in item for item in result["errors"])
    assert any("coordinate_out_of_bounds" in item for item in result["errors"])


def test_rejects_coordinate_label_not_allowed_for_screen():
    result = validate_catalog(
        {"screens": {"sample": _region()}, "targets": {"閉じる": _region()}},
        screen_targets={"sample": {"実行"}}, coordinates={"sample": {"閉じる": (640, 600)}},
    )
    assert "coordinates.sample.閉じる: target_not_allowed_for_screen" in result["errors"]


def test_reports_duplicate_json_keys():
    assert duplicate_json_keys('{"screens": {}, "screens": {}}') == ["screens"]
