from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NormalizedROI(BaseModel):
    """A deterministic, side-effect-free region of interest in [0, 1] coordinates."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    def pixel_bounds(self, image_width: int, image_height: int) -> tuple[int, int, int, int]:
        """Return clipped pixel bounds as (left, top, right, bottom)."""
        if image_width <= 0 or image_height <= 0:
            raise ValueError("image dimensions must be positive")
        right = min(1.0, self.x + self.width)
        bottom = min(1.0, self.y + self.height)
        left_px = int(self.x * image_width)
        top_px = int(self.y * image_height)
        right_px = int(right * image_width)
        bottom_px = int(bottom * image_height)
        if right_px <= left_px or bottom_px <= top_px:
            raise ValueError("ROI does not contain any pixels")
        return left_px, top_px, right_px, bottom_px

    def crop_array(self, image: object) -> object:
        """Crop a NumPy-like HxW image without importing an image backend."""
        shape = getattr(image, "shape", None)
        if not isinstance(shape, tuple) or len(shape) < 2:
            raise ValueError("image must expose an HxW shape")
        height, width = int(shape[0]), int(shape[1])
        left, top, right, bottom = self.pixel_bounds(width, height)
        return image[top:bottom, left:right]


