from __future__ import annotations

import base64
import os
import threading
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional dependency
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None

try:  # pragma: no cover - optional dependency
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    np = None

try:  # pragma: no cover - optional dependency
    from ultralytics import YOLO  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    YOLO = None


class VisionServiceError(ValueError):
    """Raised for invalid vision-service requests."""


@dataclass(frozen=True)
class VisionSessionConfig:
    sample_interval_ms: int = 500
    motion_enabled: bool = True
    object_enabled: bool = True
    detector_model: str = ""
    window_seconds: int = 10


class VisionService:
    """Local-first frame analyzer for motion and optional object detection."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active = False
        self._session_id = ""
        self._started_at = ""
        self._stopped_at = ""
        self._actor = "web_ui"
        self._frames_total = 0
        self._frames_dropped = 0
        self._last_error = ""
        self._config = VisionSessionConfig()
        self._events: deque[dict[str, Any]] = deque(maxlen=40)
        self._prev_gray: Any = None
        self._sustained_motion_frames = 0
        self._yolo_model: Any = None
        self._detector_source = "none"
        self._face_cascade: Any = None

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    @staticmethod
    def _bounded_int(value: Any, *, default: int, low: int, high: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(low, min(high, parsed))

    def start_session(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = payload if isinstance(payload, dict) else {}
        sample_interval_ms = self._bounded_int(
            data.get("sample_interval_ms", 500),
            default=500,
            low=200,
            high=3000,
        )
        window_seconds = self._bounded_int(
            data.get("window_seconds", 10),
            default=10,
            low=5,
            high=30,
        )
        detector_model = str(data.get("detector_model", "")).strip()
        motion_enabled = bool(data.get("motion_enabled", True))
        object_enabled = bool(data.get("object_enabled", True))
        actor = str(data.get("actor", "web_ui")).strip() or "web_ui"

        max_events = max(10, min(180, int((window_seconds * 1000) / max(1, sample_interval_ms)) + 8))

        with self._lock:
            self._active = True
            self._session_id = f"vision_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
            self._started_at = self._now_iso()
            self._stopped_at = ""
            self._actor = actor
            self._frames_total = 0
            self._frames_dropped = 0
            self._last_error = ""
            self._config = VisionSessionConfig(
                sample_interval_ms=sample_interval_ms,
                motion_enabled=motion_enabled,
                object_enabled=object_enabled,
                detector_model=detector_model,
                window_seconds=window_seconds,
            )
            self._events = deque(maxlen=max_events)
            self._prev_gray = None
            self._sustained_motion_frames = 0
            self._yolo_model = None
            self._detector_source = "none"

        return self.status()

    def stop_session(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        _ = payload if isinstance(payload, dict) else {}
        with self._lock:
            self._active = False
            self._stopped_at = self._now_iso()
            snapshot = self._summary_locked(max_events=8)
        return {
            "active": False,
            "session_id": self._session_id,
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "frames_total": self._frames_total,
            "frames_dropped": self._frames_dropped,
            "summary": snapshot,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self._active,
                "session_id": self._session_id,
                "started_at": self._started_at,
                "stopped_at": self._stopped_at,
                "actor": self._actor,
                "frames_total": self._frames_total,
                "frames_dropped": self._frames_dropped,
                "last_error": self._last_error,
                "config": {
                    "sample_interval_ms": self._config.sample_interval_ms,
                    "window_seconds": self._config.window_seconds,
                    "motion_enabled": self._config.motion_enabled,
                    "object_enabled": self._config.object_enabled,
                    "detector_model": self._config.detector_model,
                },
                "capabilities": {
                    "opencv_available": bool(cv2 is not None and np is not None),
                    "yolo_available": bool(YOLO is not None),
                },
            }

    def process_frame(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = payload if isinstance(payload, dict) else {}
        frame_b64 = str(data.get("frame_base64", "")).strip()
        if not frame_b64:
            raise VisionServiceError("frame_base64 is required.")

        timestamp_utc = str(data.get("timestamp_utc", "")).strip() or self._now_iso()
        frame_id = str(data.get("frame_id", "")).strip() or uuid.uuid4().hex[:10]

        with self._lock:
            if not self._active:
                raise VisionServiceError("Vision session is not active.")

            self._frames_total += 1

            raw_bytes = self._decode_frame_bytes(frame_b64)
            frame = self._decode_opencv_frame(raw_bytes)
            detections: list[dict[str, Any]] = []
            motion = {
                "detected": False,
                "sustained": False,
                "ratio": 0.0,
                "regions": [],
                "method": "unavailable",
            }

            if frame is None:
                self._frames_dropped += 1
                self._last_error = (
                    "OpenCV/Numpy unavailable or frame decode failed. "
                    "Install opencv-python-headless + numpy for motion/object detection."
                )
            else:
                self._last_error = ""
                if self._config.motion_enabled:
                    motion = self._detect_motion(frame)
                if self._config.object_enabled:
                    detections = self._detect_objects(frame)
                    if motion.get("detected") and not detections:
                        detections = self._motion_proxy_detections(motion)

            event = {
                "timestamp_utc": timestamp_utc,
                "frame_id": frame_id,
                "frame_bytes": len(raw_bytes),
                "detections": detections,
                "motion": motion,
                "detector_source": self._detector_source,
            }
            self._events.append(event)
            summary = self._summary_locked(max_events=12)
            planner_context = self._planner_context_locked(max_events=8)

        return {
            "session_id": self._session_id,
            "frame_id": frame_id,
            "event": event,
            "summary": summary,
            "planner_context": planner_context,
        }

    def context_snapshot(self, *, max_events: int = 20) -> dict[str, Any]:
        with self._lock:
            summary = self._summary_locked(max_events=max_events)
            events = list(self._events)[-max(1, min(max_events, 120)) :]
            return {
                "active": self._active,
                "session_id": self._session_id,
                "summary": summary,
                "events": events,
                "planner_context": self._planner_context_locked(max_events=min(10, max_events)),
            }

    def planner_context(self, *, max_events: int = 8) -> str:
        with self._lock:
            return self._planner_context_locked(max_events=max_events)

    @staticmethod
    def _decode_frame_bytes(frame_base64: str) -> bytes:
        raw = frame_base64.strip()
        if raw.startswith("data:") and "," in raw:
            raw = raw.split(",", 1)[1].strip()
        try:
            buff = base64.b64decode(raw, validate=True)
        except (ValueError, TypeError) as exc:
            raise VisionServiceError(f"Invalid base64 frame payload: {exc}") from exc
        if not buff:
            raise VisionServiceError("Decoded frame is empty.")
        if len(buff) > 4 * 1024 * 1024:
            raise VisionServiceError("Frame exceeds max size (4MB).")
        return buff

    @staticmethod
    def _decode_opencv_frame(raw_bytes: bytes) -> Any | None:
        if cv2 is None or np is None:
            return None
        arr = np.frombuffer(raw_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return None
        return frame

    def _detect_motion(self, frame: Any) -> dict[str, Any]:
        if cv2 is None:
            return {
                "detected": False,
                "sustained": False,
                "ratio": 0.0,
                "regions": [],
                "method": "unavailable",
            }

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        if self._prev_gray is None:
            self._prev_gray = gray
            return {
                "detected": False,
                "sustained": False,
                "ratio": 0.0,
                "regions": [],
                "method": "frame_diff",
            }

        diff = cv2.absdiff(self._prev_gray, gray)
        _, thresh = cv2.threshold(diff, 24, 255, cv2.THRESH_BINARY)
        thresh = cv2.dilate(thresh, None, iterations=2)
        motion_pixels = int(cv2.countNonZero(thresh))
        total_pixels = int(thresh.shape[0] * thresh.shape[1]) or 1
        ratio = motion_pixels / total_pixels

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        regions: list[dict[str, Any]] = []
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < 450:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            regions.append(
                {
                    "x": int(x),
                    "y": int(y),
                    "w": int(w),
                    "h": int(h),
                    "area": round(area, 2),
                }
            )

        detected = ratio >= 0.008 or bool(regions)
        if detected:
            self._sustained_motion_frames += 1
        else:
            self._sustained_motion_frames = max(0, self._sustained_motion_frames - 1)
        sustained = self._sustained_motion_frames >= 3

        self._prev_gray = gray
        return {
            "detected": bool(detected),
            "sustained": bool(sustained),
            "ratio": round(ratio, 5),
            "regions": regions[:8],
            "method": "frame_diff",
        }

    def _detect_objects(self, frame: Any) -> list[dict[str, Any]]:
        # Priority 1: explicit local YOLO model, if configured and available.
        yolo_rows = self._detect_objects_yolo(frame)
        if yolo_rows:
            self._detector_source = "yolo"
            return yolo_rows

        # Priority 2: lightweight local face detector fallback.
        face_rows = self._detect_objects_faces(frame)
        if face_rows:
            self._detector_source = "haar_face"
            return face_rows

        self._detector_source = "none"
        return []

    def _detect_objects_yolo(self, frame: Any) -> list[dict[str, Any]]:
        if YOLO is None:
            return []
        model_hint = str(self._config.detector_model or "").strip()
        if not model_hint:
            return []

        if self._yolo_model is None:
            model_path = Path(model_hint).expanduser()
            allow_download = str(os.getenv("DAVID_VISION_ALLOW_MODEL_DOWNLOAD", "")).strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            if not model_path.exists() and not allow_download:
                self._last_error = (
                    f"Configured detector model '{model_hint}' not found locally. "
                    "Set DAVID_VISION_ALLOW_MODEL_DOWNLOAD=true to allow automatic download."
                )
                return []
            try:  # pragma: no cover - depends on local ultralytics install/model
                self._yolo_model = YOLO(model_hint)
            except Exception as exc:  # pragma: no cover - depends on local ultralytics install/model
                self._last_error = f"YOLO load failed: {exc}"
                self._yolo_model = None
                return []

        try:  # pragma: no cover - depends on local ultralytics install/model
            rows: list[dict[str, Any]] = []
            result_set = self._yolo_model(frame, verbose=False)
            for result in result_set:
                names = getattr(result, "names", {}) or {}
                boxes = getattr(result, "boxes", None)
                if boxes is None:
                    continue
                cls_rows = getattr(boxes, "cls", [])
                conf_rows = getattr(boxes, "conf", [])
                xyxy_rows = getattr(boxes, "xyxy", [])
                size = min(len(cls_rows), len(conf_rows), len(xyxy_rows))
                for idx in range(size):
                    cls_id = int(float(cls_rows[idx]))
                    conf = float(conf_rows[idx])
                    if conf < 0.25:
                        continue
                    coords = xyxy_rows[idx]
                    x1, y1, x2, y2 = [int(float(value)) for value in coords[:4]]
                    rows.append(
                        {
                            "label": str(names.get(cls_id, f"class_{cls_id}")),
                            "confidence": round(conf, 3),
                            "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
                        }
                    )
            return rows[:24]
        except Exception as exc:  # pragma: no cover - depends on local ultralytics install/model
            self._last_error = f"YOLO inference failed: {exc}"
            return []

    def _detect_objects_faces(self, frame: Any) -> list[dict[str, Any]]:
        if cv2 is None:
            return []
        if self._face_cascade is None:
            try:
                cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
                self._face_cascade = cv2.CascadeClassifier(str(cascade_path))
            except Exception:
                self._face_cascade = None
        if self._face_cascade is None or self._face_cascade.empty():
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(30, 30))
        rows: list[dict[str, Any]] = []
        for (x, y, w, h) in faces:
            rows.append(
                {
                    "label": "human_face",
                    "confidence": 0.6,
                    "bbox": {"x1": int(x), "y1": int(y), "x2": int(x + w), "y2": int(y + h)},
                }
            )
        return rows[:16]

    @staticmethod
    def _motion_proxy_detections(motion: dict[str, Any]) -> list[dict[str, Any]]:
        if not bool(motion.get("detected")):
            return []
        rows: list[dict[str, Any]] = []
        for region in motion.get("regions", [])[:4]:
            if not isinstance(region, dict):
                continue
            x = int(region.get("x", 0))
            y = int(region.get("y", 0))
            w = int(region.get("w", 0))
            h = int(region.get("h", 0))
            rows.append(
                {
                    "label": "moving_region",
                    "confidence": round(min(0.99, 0.4 + float(motion.get("ratio", 0.0)) * 20), 3),
                    "bbox": {"x1": x, "y1": y, "x2": x + w, "y2": y + h},
                }
            )
        return rows

    def _summary_locked(self, *, max_events: int) -> dict[str, Any]:
        rows = list(self._events)[-max(1, min(max_events, 120)) :]
        labels: Counter[str] = Counter()
        motion_events = 0
        sustained_motion_events = 0
        latest = rows[-1] if rows else {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            motion = row.get("motion", {})
            if isinstance(motion, dict) and bool(motion.get("detected")):
                motion_events += 1
            if isinstance(motion, dict) and bool(motion.get("sustained")):
                sustained_motion_events += 1
            detections = row.get("detections", [])
            if not isinstance(detections, list):
                continue
            for item in detections:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label", "")).strip()
                if label:
                    labels[label] += 1

        top_labels = [{"label": key, "count": value} for key, value in labels.most_common(8)]
        motion_ratio = round(motion_events / max(1, len(rows)), 3) if rows else 0.0
        sustained_recent = bool(sustained_motion_events > 0)
        latest_motion = latest.get("motion", {}) if isinstance(latest, dict) else {}
        latest_detections = latest.get("detections", []) if isinstance(latest, dict) else []
        return {
            "events_considered": len(rows),
            "top_labels": top_labels,
            "motion_event_count": motion_events,
            "motion_event_rate": motion_ratio,
            "sustained_motion_recent": sustained_recent,
            "latest_motion": latest_motion if isinstance(latest_motion, dict) else {},
            "latest_detections": latest_detections if isinstance(latest_detections, list) else [],
            "detector_source": self._detector_source,
        }

    def _planner_context_locked(self, *, max_events: int) -> str:
        summary = self._summary_locked(max_events=max_events)
        labels = summary.get("top_labels", [])
        label_text = ", ".join(
            f"{row.get('label')} ({row.get('count')})"
            for row in labels[:5]
            if isinstance(row, dict) and str(row.get("label", "")).strip()
        )
        latest_motion = summary.get("latest_motion", {})
        latest_ratio = float(latest_motion.get("ratio", 0.0)) if isinstance(latest_motion, dict) else 0.0
        sustained = bool(summary.get("sustained_motion_recent"))
        lines = [
            "Real-world vision context (local webcam, privacy-first):",
            f"- Top observed entities: {label_text or 'none confidently detected'}",
            f"- Motion activity rate: {summary.get('motion_event_rate', 0.0)}",
            f"- Sustained motion recently: {str(sustained).lower()}",
            f"- Latest motion ratio: {round(latest_ratio, 5)}",
        ]
        if sustained:
            lines.append(
                "- Note: sustained movement detected; prioritize logging/monitoring automation if user requests hardware tracking."
            )
        return "\n".join(lines).strip()
