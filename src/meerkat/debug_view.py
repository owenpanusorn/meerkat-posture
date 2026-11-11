"""Debug window: live camera image with landmarks and metric values.

Opened only when the user asks for it (``--debug``). Frames are drawn and shown
in memory only, never saved (PLAN.md section 2).
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from meerkat.camera import Camera
from meerkat.detector import Detector, Landmarks
from meerkat.metrics import (
    FACE_EYE_OUTER_A,
    FACE_EYE_OUTER_B,
    POSE_LEFT_EAR,
    POSE_LEFT_SHOULDER,
    POSE_RIGHT_EAR,
    POSE_RIGHT_SHOULDER,
    PostureMetrics,
    Smoother,
    compute_metrics,
)

WINDOW = "Meerkat debug (q / Esc to close)"
FACE_NOSE_TIP = 1


def _fmt(v: float | None, unit: str = "", digits: int = 1) -> str:
    return "--" if v is None else f"{v:+.{digits}f}{unit}"


def draw(frame: np.ndarray, lm: Landmarks, m: PostureMetrics, fps: float) -> np.ndarray:
    img = frame.copy()
    w, h = lm.width, lm.height

    def pt(points: np.ndarray, i: int) -> tuple[int, int]:
        return int(points[i, 0] * w), int(points[i, 1] * h)

    if lm.face is not None:
        for i in (FACE_EYE_OUTER_A, FACE_EYE_OUTER_B, FACE_NOSE_TIP):
            cv2.circle(img, pt(lm.face, i), 4, (0, 255, 255), -1)
        cv2.line(
            img, pt(lm.face, FACE_EYE_OUTER_A), pt(lm.face, FACE_EYE_OUTER_B), (0, 255, 255), 1
        )
    if lm.pose is not None:
        for i in (POSE_LEFT_SHOULDER, POSE_RIGHT_SHOULDER, POSE_LEFT_EAR, POSE_RIGHT_EAR):
            color = (0, 200, 0) if lm.pose[i, 3] >= 0.5 else (0, 0, 200)
            cv2.circle(img, pt(lm.pose, i), 6, color, -1)
        cv2.line(
            img, pt(lm.pose, POSE_LEFT_SHOULDER), pt(lm.pose, POSE_RIGHT_SHOULDER), (0, 200, 0), 2
        )

    lines = [
        f"present {'yes' if m.present else 'no'}   {fps:.1f} fps",
        f"yaw   {_fmt(m.head_yaw, ' deg')}",
        f"pitch {_fmt(m.head_pitch, ' deg')}",
        f"roll  {_fmt(m.head_roll, ' deg')}",
        f"scale {_fmt(m.face_scale, '', 3)}",
        f"tilt  {_fmt(m.shoulder_tilt, ' deg')}",
        f"width {_fmt(m.shoulder_width, '', 3)}",
        f"neck  {_fmt(m.neck_drop, '', 3)}",
    ]
    cv2.rectangle(img, (0, 0), (230, 12 + 22 * len(lines)), (0, 0, 0), -1)
    for i, text in enumerate(lines):
        cv2.putText(
            img,
            text,
            (8, 24 + 22 * i),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
    return img


def run(camera_index: int = 0, fps: float = 5.0, smoothing_s: float = 1.5) -> int:
    smoother = Smoother(smoothing_s)
    last = time.monotonic()
    shown_fps = 0.0
    with Camera(camera_index, fps) as cam, Detector() as det:
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        try:
            while True:
                frame = cam.read()
                if frame is None:
                    print("camera returned no frame")
                    return 1
                now = time.monotonic()
                shown_fps = 0.8 * shown_fps + 0.2 * (1.0 / max(now - last, 1e-6))
                last = now

                lm = det.detect(frame, int(now * 1000))
                m = smoother.update(now, compute_metrics(lm))
                cv2.imshow(WINDOW, draw(frame, lm, m, shown_fps))
                del frame  # frames are never kept

                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    break
        finally:
            cv2.destroyAllWindows()
    return 0
