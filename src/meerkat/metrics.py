"""Pure functions: landmarks -> PostureMetrics (PLAN.md section 6).

No camera, no UI, no MediaPipe import, so everything here is unit-testable with
fake numbers.

Angle conventions (degrees):
    head_yaw    + = nose turns toward image right
    head_pitch  + = chin up (looking up), - = looking down. MediaPipe's matrix gives
                    the opposite sign, so it is flipped (PITCH_SIGN), checked on a real webcam.
    head_roll   + = head rotates counter-clockwise as seen in the image
    shoulder_tilt + = the shoulder on the image's right side is lower

Raw values are camera dependent. Phase 2 compares them against a calibrated baseline.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, fields

import numpy as np

from meerkat.detector import Landmarks

# Face mesh: outer eye corners.
FACE_EYE_OUTER_A = 33
FACE_EYE_OUTER_B = 263
# Pose: ears and shoulders.
POSE_LEFT_EAR = 7
POSE_RIGHT_EAR = 8
POSE_LEFT_SHOULDER = 11
POSE_RIGHT_SHOULDER = 12

MIN_VISIBILITY = 0.5

# MediaPipe's facial transformation matrix reports looking down as positive pitch.
PITCH_SIGN = -1.0


@dataclass(frozen=True)
class PostureMetrics:
    present: bool
    head_yaw: float | None = None
    head_pitch: float | None = None
    head_roll: float | None = None
    face_scale: float | None = None  # eye-corner distance / frame width
    shoulder_tilt: float | None = None
    shoulder_width: float | None = None  # shoulder distance / frame width
    neck_drop: float | None = None  # (shoulder y - ear y) / shoulder distance


def matrix_to_euler(m: np.ndarray) -> tuple[float, float, float]:
    """Return (yaw, pitch, roll) in degrees for R = Ry(yaw) @ Rx(pitch) @ Rz(roll)."""
    r = np.asarray(m, dtype=float)[:3, :3]
    # Strip any uniform scale so this works on similarity transforms too.
    scale = np.cbrt(abs(np.linalg.det(r)))
    if scale > 0:
        r = r / scale
    pitch = math.asin(max(-1.0, min(1.0, -r[1, 2])))
    yaw = math.atan2(r[0, 2], r[2, 2])
    roll = math.atan2(r[1, 0], r[1, 1])
    return math.degrees(yaw), math.degrees(pitch), math.degrees(roll)


def euler_to_matrix(yaw: float, pitch: float, roll: float) -> np.ndarray:
    """Inverse of ``matrix_to_euler`` as a 4x4 matrix. Used by tests and fixtures."""
    a, b, c = (math.radians(v) for v in (yaw, pitch, roll))
    ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
    rz = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = ry @ rx @ rz
    return m


def _px(points: np.ndarray, idx: int, w: int, h: int) -> np.ndarray:
    return np.array([points[idx, 0] * w, points[idx, 1] * h])


def compute_metrics(lm: Landmarks) -> PostureMetrics:
    if lm.face is None:
        return PostureMetrics(present=False)

    w, h = lm.width, lm.height
    yaw = pitch = roll = None
    if lm.face_matrix is not None:
        yaw, pitch, roll = matrix_to_euler(lm.face_matrix)
        pitch *= PITCH_SIGN

    eye_a = _px(lm.face, FACE_EYE_OUTER_A, w, h)
    eye_b = _px(lm.face, FACE_EYE_OUTER_B, w, h)
    face_scale = float(np.linalg.norm(eye_a - eye_b)) / w

    tilt = width = drop = None
    pose = lm.pose
    if pose is not None and min(pose[POSE_LEFT_SHOULDER, 3], pose[POSE_RIGHT_SHOULDER, 3]) >= (
        MIN_VISIBILITY
    ):
        s1 = _px(pose, POSE_LEFT_SHOULDER, w, h)
        s2 = _px(pose, POSE_RIGHT_SHOULDER, w, h)
        left, right = (s1, s2) if s1[0] <= s2[0] else (s2, s1)
        dx, dy = right - left
        dist = math.hypot(dx, dy)
        if dist > 0:
            tilt = math.degrees(math.atan2(dy, dx))
            width = dist / w
            if min(pose[POSE_LEFT_EAR, 3], pose[POSE_RIGHT_EAR, 3]) >= MIN_VISIBILITY:
                ear_y = (pose[POSE_LEFT_EAR, 1] + pose[POSE_RIGHT_EAR, 1]) / 2 * h
                shoulder_y = (s1[1] + s2[1]) / 2
                drop = (shoulder_y - ear_y) / dist

    return PostureMetrics(
        present=True,
        head_yaw=yaw,
        head_pitch=pitch,
        head_roll=roll,
        face_scale=face_scale,
        shoulder_tilt=tilt,
        shoulder_width=width,
        neck_drop=drop,
    )


_NUMERIC_FIELDS = [f.name for f in fields(PostureMetrics) if f.name != "present"]


class Smoother:
    """Time-window moving average over PostureMetrics.

    Each numeric field is averaged over samples within ``window_s`` seconds, ignoring
    None values. ``present`` takes the latest sample.
    """

    def __init__(self, window_s: float = 1.5) -> None:
        self.window_s = window_s
        self._buf: deque[tuple[float, PostureMetrics]] = deque()

    def update(self, t: float, m: PostureMetrics) -> PostureMetrics:
        self._buf.append((t, m))
        while self._buf and t - self._buf[0][0] > self.window_s:
            self._buf.popleft()
        out: dict[str, float | None] = {}
        for name in _NUMERIC_FIELDS:
            vals = [getattr(s, name) for _, s in self._buf if getattr(s, name) is not None]
            out[name] = sum(vals) / len(vals) if vals else None
        if not m.present:
            # Don't show stale head values once the person has left the frame.
            return PostureMetrics(present=False)
        return PostureMetrics(present=True, **out)

    def reset(self) -> None:
        self._buf.clear()
