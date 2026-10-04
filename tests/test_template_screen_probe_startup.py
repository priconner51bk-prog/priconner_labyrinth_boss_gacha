"""起動画面・エラー画面を安全に分類する条件を確認する。"""

import numpy as np

from vision.template_screen_probe import AdbTemplateScreenProbe, TemplateRegion


def test_startup_error_requires_its_confirmed_title_button(monkeypatch):
    title = TemplateRegion("title.png", 490, 645, 790, 705)
    error = TemplateRegion("error.png", 580, 170, 700, 220)
    title_button = TemplateRegion("title_button.png", 500, 460, 780, 530)
    probe = AdbTemplateScreenProbe(
        capture=object(), screens={"title": title, "startup_error": error},
        targets={"タイトルへ": title_button}, threshold=0.95,
    )
    button_score = {"value": 1.0}

    def score(_image, reference, _region):
        if reference is error:
            return 1.0
        if reference is title_button:
            return button_score["value"]
        return 0.0

    monkeypatch.setattr(probe, "_score", score)
    image = np.zeros((720, 1280, 3), dtype=np.uint8)

    assert probe._classify(image) == "startup_error"
    button_score["value"] = 0.0
    assert probe._classify(image) is None


def test_server_error_201_uses_confirmed_dialog_layout_when_header_text_differs(monkeypatch):
    title = TemplateRegion("title.png", 490, 645, 790, 705)
    error = TemplateRegion("error.png", 580, 170, 700, 220)
    title_button = TemplateRegion("title_button.png", 500, 460, 780, 530)
    probe = AdbTemplateScreenProbe(
        capture=object(), screens={"title": title, "startup_error": error},
        targets={"タイトルへ": title_button}, threshold=0.95,
    )
    monkeypatch.setattr(
        probe, "_score",
        lambda _image, reference, _region: 1.0 if reference is title_button else 0.2,
    )
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[171:218, 325:958] = (255, 150, 30)  # Blue dialog header in BGR.
    image[220:450, 325:958] = (255, 255, 255)

    assert probe._classify(image) == "startup_error"

    image[171:218, 325:958] = (0, 0, 0)
    assert probe._classify(image) is None


def test_animated_title_uses_scoped_threshold_for_screen_and_start_button(monkeypatch):
    title = TemplateRegion("title.png", 534, 658, 674, 686)
    start_button = TemplateRegion("start.png", 534, 658, 674, 686)
    probe = AdbTemplateScreenProbe(
        capture=object(), screens={"title": title},
        targets={"Touch To Start": start_button}, threshold=0.95,
    )
    monkeypatch.setattr(probe, "_score", lambda *_args: 0.936)
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    probe._last_color_image = image

    assert probe._classify(image) == "title"
    assert probe.target_visible("Touch To Start") is True


def test_network_loading_overrides_home_until_overlay_clears(monkeypatch):
    home = TemplateRegion("home.png", 665, 635, 780, 710)
    connecting = TemplateRegion("connecting.png", 1010, 30, 1240, 60)
    probe = AdbTemplateScreenProbe(
        capture=object(), screens={"home": home, "network_loading": connecting},
        targets={"dummy": home}, threshold=0.95,
    )
    scores = {"home": 1.0, "connecting": 0.81}
    monkeypatch.setattr(
        probe, "_score", lambda _image, reference, _region: scores[reference.image.split(".")[0]],
    )
    image = np.zeros((720, 1280, 3), dtype=np.uint8)

    assert probe._classify(image) == "network_loading"
    scores["connecting"] = 0.79
    assert probe._classify(image) == "home"
