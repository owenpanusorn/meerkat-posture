"""Camera access: open a device by index and hand out frames at a target rate.

Frames live only in memory. Nothing here writes to disk (PLAN.md section 2).
``release()`` really closes the device so the camera light turns off.
"""

from __future__ import annotations

import sys
import time

import cv2
import numpy as np


class CameraError(RuntimeError):
    pass


class Camera:
    """Webcam reader throttled to ``fps`` frames per second."""

    def __init__(
        self, index: int = 0, fps: float = 5.0, width: int = 640, height: int = 480
    ) -> None:
        if fps <= 0:
            raise ValueError("fps must be > 0")
        self.index = index
        self.fps = fps
        self.width = width
        self.height = height
        self._cap: cv2.VideoCapture | None = None
        self._next_t = 0.0

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def open(self) -> None:
        if self.is_open:
            return
        # DirectShow opens much faster than MSMF on Windows.
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.index, backend)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(self.index)
        if not cap.isOpened():
            cap.release()
            raise CameraError(f"cannot open camera index {self.index}")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        # Keep the driver buffer small so a slow reader still gets fresh frames.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap = cap
        self._next_t = time.monotonic()

    def read(self) -> np.ndarray | None:
        """Wait until the next frame slot, then return a BGR frame (or None on failure)."""
        if not self.is_open:
            raise CameraError("camera is not open")
        delay = self._next_t - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._next_t = max(self._next_t + 1.0 / self.fps, time.monotonic())
        ok, frame = self._cap.read()
        return frame if ok else None

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> Camera:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
