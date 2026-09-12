from vision.template_screen_probe import AdbTemplateScreenProbe


def test_guild_header_wins_over_dynamic_card_button():
    probe = object.__new__(AdbTemplateScreenProbe)
    header, card = object(), object()
    probe.screens = {"guild_select": header}
    probe.targets = {"出発": card}
    probe.threshold = .95
    probe._score = lambda image, reference, region: 1.0
    # 動的カードが別画面のボタンROIに似ていても見出しで識別する。
    assert probe._classify(object()) == "guild_select"
