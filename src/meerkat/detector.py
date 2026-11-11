"""Run MediaPipe Face + Pose Landmarkers on a frame and return raw landmarks.

No posture logic lives here; see ``metrics.py``. Models are loaded from local
``models/`` only. Nothing is downloaded at runtime (PLAN.md section 2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

DEFAULT_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
FACE_MODEL = "face_landmarker.task"
POSE_MODEL = "pose_landmarker_lite.task"


@dataclass(frozen=True)
class Landmarks:
    """Landmarks for one frame. Coordinates are normalized to [0, 1] of the image.

    face:        (478, 3) x, y, z or None if no face
    face_matrix: (4, 4) facial transformation matrix or None
    pose:        (33, 4) x, y, z, visibility or None if no body
    """

    width: int
    height: int
    timestamp_ms: int
    face: np.ndarray | None = None
    face_matrix: np.ndarray | None = None
    pose: np.ndarray | None = None


class Detector:
    def __init__(
        self, models_dir: Path | str = DEFAULT_MODELS_DIR, min_confidence: float = 0.5
    ) -> None:
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        models_dir = Path(models_dir)
        face_path = models_dir / FACE_MODEL
        pose_path = models_dir / POSE_MODEL
        for p in (face_path, pose_path):
            if not p.exists():
                raise FileNotFoundError(
                    f"missing model {p}. Run: uv run python scripts/download_models.py"
                )

        self._mp = mp
        video = vision.RunningMode.VIDEO
        self._face = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(face_path)),
                running_mode=video,
                num_faces=1,
                min_face_detection_confidence=min_confidence,
                min_face_presence_confidence=min_confidence,
                output_facial_transformation_matrixes=True,
            )
        )
        self._pose = vision.PoseLandmarker.create_from_options(
            vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(pose_path)),
                running_mode=video,
                num_poses=1,
                min_pose_detection_confidence=min_confidence,
                min_pose_presence_confidence=min_confidence,
            )
        )
        self._last_ts = -1

    def detect(self, frame_bgr: np.ndarray, timestamp_ms: int) -> Landmarks:
        # VIDEO mode requires strictly increasing timestamps.
        ts = max(int(timestamp_ms), self._last_ts + 1)
        self._last_ts = ts

        h, w = frame_bgr.shape[:2]
        rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)

        face_res = self._face.detect_for_video(image, ts)
        pose_res = self._pose.detect_for_video(image, ts)

        face = face_matrix = pose = None
        if face_res.face_landmarks:
            face = np.array([(p.x, p.y, p.z) for p in face_res.face_landmarks[0]])
            if face_res.facial_transformation_matrixes:
                face_matrix = np.asarray(face_res.facial_transformation_matrixes[0])
        if pose_res.pose_landmarks:
            pose = np.array(
                [(p.x, p.y, p.z, p.visibility or 0.0) for p in pose_res.pose_landmarks[0]]
            )
        return Landmarks(w, h, ts, face, face_matrix, pose)

    def close(self) -> None:
        self._face.close()
        self._pose.close()

    def __enter__(self) -> Detector:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
