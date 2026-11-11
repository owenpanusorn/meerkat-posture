import math

import numpy as np
import pytest

from meerkat.detector import Landmarks
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
    euler_to_matrix,
    matrix_to_euler,
)

W, H = 640, 480


def make_landmarks(
    yaw=0.0,
    pitch=0.0,
    roll=0.0,
    eye_gap=0.1,
    shoulders=((0.3, 0.8), (0.7, 0.8)),
    ears=((0.45, 0.4), (0.55, 0.4)),
    visibility=1.0,
    with_pose=True,
) -> Landmarks:
    face = np.full((478, 3), 0.5)
    face[FACE_EYE_OUTER_A, :2] = (0.5 - eye_gap / 2, 0.35)
    face[FACE_EYE_OUTER_B, :2] = (0.5 + eye_gap / 2, 0.35)
    pose = None
    if with_pose:
        pose = np.zeros((33, 4))
        pose[:, 3] = visibility
        pose[POSE_RIGHT_SHOULDER, :2] = shoulders[0]
        pose[POSE_LEFT_SHOULDER, :2] = shoulders[1]
        pose[POSE_RIGHT_EAR, :2] = ears[0]
        pose[POSE_LEFT_EAR, :2] = ears[1]
    return Landmarks(W, H, 0, face, euler_to_matrix(yaw, pitch, roll), pose)


@pytest.mark.parametrize(
    "angles",
    [(0, 0, 0), (30, 0, 0), (-30, 0, 0), (0, -20, 0), (0, 15, 0), (0, 0, 12), (25, -15, 8)],
)
def test_euler_roundtrip(angles):
    got = matrix_to_euler(euler_to_matrix(*angles))
    assert got == pytest.approx(angles, abs=1e-6)


def test_euler_ignores_uniform_scale_and_translation():
    m = euler_to_matrix(20, -10, 5)
    m[:3, :3] *= 3.0
    m[:3, 3] = (1, 2, -40)
    assert matrix_to_euler(m) == pytest.approx((20, -10, 5), abs=1e-6)


def test_turn_right_30_gives_yaw_30():
    m = compute_metrics(make_landmarks(yaw=30))
    assert m.present
    assert m.head_yaw == pytest.approx(30, abs=0.01)
    assert m.head_pitch == pytest.approx(0, abs=0.01)
    assert m.head_roll == pytest.approx(0, abs=0.01)


def test_looking_down_gives_negative_pitch():
    # MediaPipe's matrix reports looking down 20 deg as +20 rotation about x.
    m = compute_metrics(make_landmarks(pitch=20))
    assert m.head_pitch == pytest.approx(-20, abs=0.01)


def test_no_face_means_not_present():
    lm = Landmarks(W, H, 0)
    assert compute_metrics(lm) == PostureMetrics(present=False)


def test_no_face_but_body_visible_keeps_shoulders():
    lm = make_landmarks()
    lm = Landmarks(lm.width, lm.height, 0, None, None, lm.pose)
    m = compute_metrics(lm)
    assert not m.present and m.body_visible and m.person_present
    assert m.head_pitch is None
    assert m.shoulder_width == pytest.approx(0.4)


def test_smoother_keeps_body_when_face_lost():
    s = Smoother()
    s.update(0.0, PostureMetrics(True, head_yaw=10.0, shoulder_width=0.4))
    out = s.update(0.2, PostureMetrics(False, shoulder_width=0.41))
    assert not out.present and out.head_yaw is None and out.shoulder_width == 0.41


def test_face_scale_grows_when_leaning_in():
    near = compute_metrics(make_landmarks(eye_gap=0.15)).face_scale
    far = compute_metrics(make_landmarks(eye_gap=0.10)).face_scale
    assert far == pytest.approx(0.10)
    assert near / far == pytest.approx(1.5)


def test_level_shoulders():
    m = compute_metrics(make_landmarks())
    assert m.shoulder_tilt == pytest.approx(0)
    assert m.shoulder_width == pytest.approx(0.4)


def test_shoulder_tilt_angle_in_pixels():
    # Image-right shoulder lower by 40 px over 256 px horizontal.
    m = compute_metrics(make_landmarks(shoulders=((0.3, 0.8), (0.7, 0.8 + 40 / H))))
    assert m.shoulder_tilt == pytest.approx(math.degrees(math.atan2(40, 256)))
    assert m.shoulder_tilt > 0


def test_shoulder_tilt_independent_of_landmark_order():
    a = make_landmarks(shoulders=((0.3, 0.8), (0.7, 0.85)))
    b = make_landmarks(shoulders=((0.7, 0.85), (0.3, 0.8)))
    assert compute_metrics(a).shoulder_tilt == pytest.approx(compute_metrics(b).shoulder_tilt)


def test_neck_drop_shrinks_when_slouching():
    upright = compute_metrics(make_landmarks(ears=((0.45, 0.4), (0.55, 0.4)))).neck_drop
    slouch = compute_metrics(make_landmarks(ears=((0.45, 0.55), (0.55, 0.55)))).neck_drop
    # (0.8 - 0.4) * 480 / 256
    assert upright == pytest.approx(0.75)
    assert slouch < upright


def test_low_visibility_pose_is_ignored():
    m = compute_metrics(make_landmarks(visibility=0.2))
    assert m.present
    assert m.shoulder_tilt is None and m.shoulder_width is None and m.neck_drop is None


def test_face_only():
    m = compute_metrics(make_landmarks(with_pose=False))
    assert m.present and m.head_yaw is not None and m.shoulder_tilt is None


def test_smoother_averages_within_window():
    s = Smoother(window_s=1.0)
    s.update(0.0, PostureMetrics(True, head_yaw=0.0))
    s.update(0.5, PostureMetrics(True, head_yaw=10.0))
    out = s.update(1.0, PostureMetrics(True, head_yaw=20.0))
    assert out.head_yaw == pytest.approx(10.0)
    # The t=0 sample falls out of the window.
    out = s.update(1.6, PostureMetrics(True, head_yaw=20.0))
    assert out.head_yaw == pytest.approx(20.0)


def test_smoother_skips_none_values():
    s = Smoother(window_s=2.0)
    s.update(0.0, PostureMetrics(True, head_yaw=10.0, shoulder_tilt=None))
    out = s.update(0.5, PostureMetrics(True, head_yaw=None, shoulder_tilt=4.0))
    assert out.head_yaw == pytest.approx(10.0)
    assert out.shoulder_tilt == pytest.approx(4.0)


def test_smoother_absent_returns_empty():
    s = Smoother()
    s.update(0.0, PostureMetrics(True, head_yaw=10.0))
    assert s.update(0.2, PostureMetrics(False)) == PostureMetrics(False)
