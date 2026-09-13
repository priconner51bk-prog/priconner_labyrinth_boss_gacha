import numpy as np
import pytest

from scripts.crop_template import crop_image


def test_crop_image_returns_requested_roi() -> None:
    image = np.zeros((10, 12, 3), dtype=np.uint8)
    assert crop_image(image, 2, 3, 7, 8).shape == (5, 5, 3)


@pytest.mark.parametrize("bounds", [(-1, 0, 2, 2), (0, 0, 13, 2), (2, 2, 1, 3), (0, 0, 2, 11)])
def test_crop_image_rejects_invalid_bounds(bounds) -> None:
    image = np.zeros((10, 12, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="画像外"):
        crop_image(image, *bounds)
