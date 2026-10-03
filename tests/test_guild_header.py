import cv2
import numpy as np

from vision.template_screen_probe import AdbTemplateScreenProbe, TemplateRegion


def test_guild_header_wins_over_dynamic_card_button():
    probe = object.__new__(AdbTemplateScreenProbe)
    header, card = object(), object()
    probe.screens = {"guild_select": header}
    probe.targets = {"出発": card}
    probe.threshold = .95
    probe._score = lambda image, reference, region: 1.0
    # 動的カードが別画面のボタンROIに似ていても見出しで識別する。
    assert probe._classify(object()) == "guild_select"


def test_guild_header_edge_match_tolerates_background_and_alignment(tmp_path):
    template = np.full((45, 460), 210, dtype=np.uint8)
    cv2.rectangle(template, (3, 3), (456, 41), 40, 2)
    for x in range(24, 440, 19):
        cv2.line(template, (x, 12), (x + 7, 32), 30, 3)
    template_path = tmp_path / "guild_header.png"
    assert cv2.imwrite(str(template_path), template)

    header = TemplateRegion(template_path, 410, 97, 870, 142)
    probe = AdbTemplateScreenProbe(
        capture=object(), screens={"guild_select": header}, targets={"unused": header},
    )
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    # The banner is shifted 60px and sits over a changing background.
    for x in range(280, 1010):
        image[79:160, x] = (x % 255, (x * 2) % 255, (x * 3) % 255)
    shifted = cv2.cvtColor(template, cv2.COLOR_GRAY2BGR)
    image[101:146, 470:930] = shifted

    assert probe._classify(image) == "guild_select"
