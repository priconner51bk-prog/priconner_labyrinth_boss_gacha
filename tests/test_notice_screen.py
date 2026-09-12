from vision.template_screen_probe import AdbTemplateScreenProbe


def test_notice_layout_is_recognized():
    import numpy as np

    image = np.full((720, 1280, 3), 230, dtype=np.uint8)
    image[32:79, 38:1242] = (210, 150, 70)
    assert AdbTemplateScreenProbe._is_notice_screen(image)


def test_plain_light_screen_is_not_notice():
    import numpy as np

    image = np.full((720, 1280, 3), 255, dtype=np.uint8)
    assert not AdbTemplateScreenProbe._is_notice_screen(image)


def test_startup_splash_layout_is_recognized():
    import numpy as np

    image = np.full((720, 1280, 3), 255, dtype=np.uint8)
    image[300:430, 380:900] = 30
    assert AdbTemplateScreenProbe._is_startup_splash(image)


def test_dark_game_screen_is_not_startup_splash():
    import numpy as np

    image = np.full((720, 1280, 3), 80, dtype=np.uint8)
    assert not AdbTemplateScreenProbe._is_startup_splash(image)


def test_target_center_uses_configured_region_only():
    from vision.template_screen_probe import TemplateRegion

    probe = object.__new__(AdbTemplateScreenProbe)
    probe.targets = {"タイトルへ": TemplateRegion("unused.png", 420, 520, 860, 650)}
    assert probe.target_center("タイトルへ") == (640, 585)
    assert probe.target_center("未登録") is None
