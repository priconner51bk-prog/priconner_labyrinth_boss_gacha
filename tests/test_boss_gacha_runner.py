from boss_gacha import BossGachaController, BossGachaPolicy, BossGachaRunner


def test_runner_retries_and_stops_at_maximum():
    events = []
    names = iter([{"3": "別", "5": "別"}, {"3": "別", "5": "別"}])
    runner = BossGachaRunner(
        BossGachaController(BossGachaPolicy({"3": "ベノムサラマンドラ", "5": "ゴブリンロード"}, 2)),
        begin_attempt=lambda: events.append("begin"),
        read_boss_names=lambda: next(names),
        withdraw=lambda: events.append("withdraw"),
        passport_count=lambda: 10,
        safety_check=lambda: True,
    )
    result = runner.run()
    assert result["status"] == "max_attempts"
    assert events == ["begin", "withdraw", "begin", "withdraw"]
    assert result["withdrawn"] is True
    assert result["timing_summary"]["read_boss_names"]["count"] == 2
    assert result["timing_summary"]["withdraw"]["count"] == 2


def test_runner_rejects_phase_before_callback():
    called = []
    runner = BossGachaRunner(
        BossGachaController(BossGachaPolicy({"3": "A"}, max_attempts=2)),
        begin_attempt=lambda: called.append("begin"),
        read_boss_names=lambda: {"3": "A"},
        withdraw=lambda: called.append("withdraw"),
        passport_count=lambda: 1,
        safety_check=lambda: True,
        phase_guard=lambda phase: phase != "begin_attempt",
    )
    result = runner.run()
    assert result["status"] == "safety_stop"
    assert "begin_attempt" in result["reason"]
    assert called == []


def test_runner_honors_ten_attempt_cap():
    calls = {"begin": 0, "withdraw": 0}
    runner = BossGachaRunner(
        BossGachaController(BossGachaPolicy({"3": "対象"}, max_attempts=10)),
        begin_attempt=lambda: calls.__setitem__("begin", calls["begin"] + 1),
        read_boss_names=lambda: {"3": "対象外"},
        withdraw=lambda: calls.__setitem__("withdraw", calls["withdraw"] + 1),
        passport_count=lambda: 99,
        safety_check=lambda: True,
    )
    result = runner.run()
    assert result["status"] == "max_attempts"
    assert result["attempt"] == 10
    assert calls == {"begin": 10, "withdraw": 10}


def test_runner_converts_callback_exception_to_safety_stop():
    called = []
    runner = BossGachaRunner(
        BossGachaController(BossGachaPolicy({"3": "対象"}, max_attempts=10)),
        begin_attempt=lambda: (_ for _ in ()).throw(ValueError("ocr failed")),
        read_boss_names=lambda: {"3": "対象"},
        withdraw=lambda: called.append("withdraw"),
        passport_count=lambda: 1,
        safety_check=lambda: True,
    )
    result = runner.run()
    assert result["status"] == "safety_stop"
    assert "begin_attempt" in result["reason"]
    assert called == []
