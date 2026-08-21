import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


class RegionConfigError(ValueError):
    pass


def load_region_config(
    path,
    target_frame_size,
    expected_scene_config_id=None,
    content_rect=None,
):
    config_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RegionConfigError(f"无法读取区域配置：{error}") from error

    scene_config_id = payload.get("scene_config_id")
    if (
        expected_scene_config_id is not None
        and scene_config_id != expected_scene_config_id
    ):
        raise RegionConfigError("区域配置的scene_config_id与AlgorithmJob不一致")

    frame_size = payload.get("frame_size")
    regions = payload.get("regions")
    if (
        not isinstance(frame_size, list)
        or len(frame_size) != 2
        or not all(isinstance(value, int) and value > 0 for value in frame_size)
    ):
        raise RegionConfigError("frame_size必须是两个正整数：[宽, 高]")
    if not isinstance(regions, list) or not regions:
        raise RegionConfigError("regions必须是非空数组")

    source_width, source_height = frame_size
    target_width, target_height = target_frame_size
    if content_rect is None:
        offset_x, offset_y = 0, 0
        content_width, content_height = target_width, target_height
    else:
        offset_x, offset_y, content_width, content_height = content_rect
        if (
            min(offset_x, offset_y) < 0
            or content_width <= 0
            or content_height <= 0
            or offset_x + content_width > target_width
            or offset_y + content_height > target_height
        ):
            raise RegionConfigError("content_rect超出目标分析帧")
    scale_x = content_width / source_width
    scale_y = content_height / source_height
    normalized = []
    region_ids = set()
    for item in regions:
        if not isinstance(item, dict):
            raise RegionConfigError("每个区域必须是对象")
        region_id = item.get("id")
        polygon = item.get("polygon")
        polygon_norm = item.get("polygon_norm")
        if not isinstance(region_id, str) or not region_id.strip():
            raise RegionConfigError("区域id必须是非空字符串")
        if region_id in region_ids:
            raise RegionConfigError(f"区域id重复：{region_id}")
        selected_polygon = polygon_norm if polygon_norm is not None else polygon
        if (
            not isinstance(selected_polygon, list)
            or len(selected_polygon) < 3
            or not all(
                isinstance(point, list)
                and len(point) == 2
                and all(isinstance(value, (int, float)) for value in point)
                for point in selected_polygon
            )
        ):
            raise RegionConfigError(f"区域{region_id}的polygon至少需要3个二维坐标")

        if polygon_norm is not None:
            if any(
                coordinate < 0 or coordinate > 1
                for point in polygon_norm
                for coordinate in point
            ):
                raise RegionConfigError(f"区域{region_id}的polygon_norm必须在0到1")
            points = [
                (
                    offset_x + int(round(point[0] * content_width)),
                    offset_y + int(round(point[1] * content_height)),
                )
                for point in polygon_norm
            ]
        else:
            points = [
                (
                    offset_x + int(round(point[0] * scale_x)),
                    offset_y + int(round(point[1] * scale_y)),
                )
                for point in polygon
            ]
        normalized.append(
            {
                "id": region_id,
                "label": str(item.get("label") or region_id),
                "polygon": points,
            }
        )
        region_ids.add(region_id)

    return normalized


def find_region(point, regions):
    if point is None:
        return None
    for region in regions:
        contour = np.asarray(region["polygon"], dtype=np.int32)
        if cv2.pointPolygonTest(contour, point, False) >= 0:
            return region["id"]
    return None


class RegionTracker:
    """Track deterministic region transitions from center points and relative time."""

    def __init__(
        self,
        regions,
        *,
        min_confirmation_updates=3,
        min_confirmation_seconds=0.4,
    ):
        self.regions = regions
        self.min_confirmation_updates = max(1, int(min_confirmation_updates))
        self.min_confirmation_seconds = max(0.0, float(min_confirmation_seconds))
        self.current_region = None
        self.entered_at = None
        self.last_timestamp = 0.0
        self.candidate_region = None
        self.candidate_since = None
        self.candidate_updates = 0
        self.events = []
        self.visited_regions = []
        self.dwell_seconds = Counter()
        self.transitions = Counter()

    def update(self, point, timestamp_seconds, close_missing=False):
        timestamp = max(float(timestamp_seconds), self.last_timestamp)
        self.last_timestamp = timestamp
        # A missed HOG frame is not proof that the resident left the region.
        if point is None and not close_missing:
            return []
        next_region = find_region(point, self.regions)
        if next_region == self.current_region:
            self.candidate_region = None
            self.candidate_since = None
            self.candidate_updates = 0
            return []

        if not close_missing:
            if next_region != self.candidate_region:
                self.candidate_region = next_region
                self.candidate_since = timestamp
                self.candidate_updates = 1
            else:
                self.candidate_updates += 1
            candidate_age = timestamp - self.candidate_since
            if (
                self.candidate_updates < self.min_confirmation_updates
                or candidate_age < self.min_confirmation_seconds
            ):
                return []

        self.candidate_region = None
        self.candidate_since = None
        self.candidate_updates = 0

        new_events = []
        previous_region = self.current_region
        if previous_region is not None:
            dwell = max(0.0, timestamp - self.entered_at)
            self.dwell_seconds[previous_region] += dwell
            new_events.append(
                {
                    "event_type": "EXIT",
                    "region_id": previous_region,
                    "at_seconds": round(timestamp, 3),
                    "dwell_seconds": round(dwell, 3),
                }
            )

        if next_region is not None:
            if previous_region is not None:
                self.transitions[f"{previous_region}->{next_region}"] += 1
            self.entered_at = timestamp
            if next_region not in self.visited_regions:
                self.visited_regions.append(next_region)
            new_events.append(
                {
                    "event_type": "ENTER",
                    "region_id": next_region,
                    "at_seconds": round(timestamp, 3),
                    "dwell_seconds": None,
                }
            )
        else:
            self.entered_at = None

        self.current_region = next_region
        self.events.extend(new_events)
        return new_events

    def finalize(self, timestamp_seconds=None):
        timestamp = self.last_timestamp if timestamp_seconds is None else timestamp_seconds
        if self.current_region is not None:
            self.update(None, timestamp, close_missing=True)
        return self.statistics()

    def statistics(self):
        dwell = Counter(self.dwell_seconds)
        if self.current_region is not None and self.entered_at is not None:
            dwell[self.current_region] += max(0.0, self.last_timestamp - self.entered_at)
        return {
            "schema_version": "1.0",
            "visited_region_count": len(self.visited_regions),
            "visited_regions": list(self.visited_regions),
            "dwell_seconds": {
                region["id"]: round(dwell.get(region["id"], 0.0), 3)
                for region in self.regions
            },
            "transition_count": sum(self.transitions.values()),
            "transitions": dict(self.transitions),
            "region_sequence": [
                event["region_id"]
                for event in self.events
                if event["event_type"] == "ENTER"
            ],
            "threshold_status": "DEMO_UNCALIBRATED",
            "distance_unit": "pixel_not_meter",
        }


def draw_regions(frame, regions, current_region=None):
    colors = [(0, 200, 255), (255, 200, 0), (0, 180, 80), (180, 80, 255)]
    for index, region in enumerate(regions):
        color = colors[index % len(colors)]
        contour = np.asarray(region["polygon"], dtype=np.int32)
        thickness = 4 if region["id"] == current_region else 2
        cv2.polylines(frame, [contour], True, color, thickness)
        x, y = region["polygon"][0]
        cv2.putText(
            frame,
            region["label"],
            (x + 5, y + 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )
    return frame
