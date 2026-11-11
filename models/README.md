# models/

MediaPipe `.task` files live here. They are not committed to git.

Download them once with:

```sh
uv run python scripts/download_models.py
```

- `face_landmarker.task`: MediaPipe Face Landmarker (Apache 2.0)
- `pose_landmarker_lite.task`: MediaPipe Pose Landmarker Lite (Apache 2.0)
