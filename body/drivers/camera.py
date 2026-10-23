"""Camera: one still photo at a time, and only with the visor up.

Every camera here is built with a `visor_is_open` function (the face link's
last reported state). `capture_jpeg()` checks it FIRST and raises VisorClosed
if the visor isn't reported open — that check is in the base class, so no
camera implementation can skip it. Nothing is ever written to disk.

    OpenCVCamera   the real USB UVC camera (opencv-python-headless on the Pi)
    FolderCamera   simulator: returns sample JPEGs from a folder
"""

from __future__ import annotations

import itertools
import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


class VisorClosed(PermissionError):
    pass


class Camera:
    def __init__(self, visor_is_open: Callable[[], bool]):
        self._visor_is_open = visor_is_open

    def capture_jpeg(self, hint: str | None = None) -> bytes:
        """Return one JPEG. Refuses unless the face says the visor is open."""
        if not self._visor_is_open():
            raise VisorClosed("the visor is not open, so the camera stays off")
        return self._grab(hint)

    def _grab(self, hint: str | None) -> bytes:
        raise NotImplementedError


class OpenCVCamera(Camera):
    """USB camera via OpenCV. The device is opened for each photo and released
    straight after, so the camera is genuinely off between looks."""

    def __init__(self, visor_is_open, index: int = 0, max_px: int = 1024, quality: int = 80):
        super().__init__(visor_is_open)
        self.index = index
        self.max_px = max_px
        self.quality = quality

    def _grab(self, hint: str | None) -> bytes:
        import cv2   # only needed on the robot

        cap = cv2.VideoCapture(self.index)
        try:
            if not cap.isOpened():
                raise RuntimeError(f"camera {self.index} didn't open")
            frame = None
            for _ in range(5):          # let auto-exposure settle for a few frames
                ok, frame = cap.read()
            if frame is None or not ok:
                raise RuntimeError("camera returned no frame")
        finally:
            cap.release()
        h, w = frame.shape[:2]
        scale = self.max_px / max(h, w)
        if scale < 1:
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        return jpeg.tobytes()


class FolderCamera(Camera):
    """Simulator camera. If a file name contains the hint (a place or what to
    look at) that file is used; otherwise it cycles through the folder."""

    def __init__(self, visor_is_open, folder: str | Path):
        super().__init__(visor_is_open)
        self.files = sorted(Path(folder).glob("*.jpg"))
        if not self.files:
            raise FileNotFoundError(f"no .jpg files in {folder}")
        self._cycle = itertools.cycle(self.files)
        self.last_file: Path | None = None

    def _grab(self, hint: str | None) -> bytes:
        chosen = None
        if hint:
            chosen = next((f for f in self.files if hint.lower().replace(" ", "_") in f.stem.lower()), None)
        self.last_file = chosen or next(self._cycle)
        return self.last_file.read_bytes()
