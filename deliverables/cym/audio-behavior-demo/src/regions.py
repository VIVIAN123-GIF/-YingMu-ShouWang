import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


class RegionConfigError(ValueError):
    pass


def load_region_config(path, target_frame_size):
    config_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RegionConfigError(f"无法读取区域配置：{error}") from error

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
    scale_x = target_width / source_width
    scale_y = target_height / source_height
    normalized = []
    region_ids = set()
    for item in regions:
        if not isinstance(item, dict):
            raise RegionConfigError("每个区域必须是对象")
        region_id = item.get("id")
        polygon = item.get("polygon")
        if not isinstance(region_id, str) or not region_id.strip():
            raise RegionConfigError("区域id必须是非空字符串")
        if region_id in region_ids:
            raise RegionConfigError(f"区域id重复：{region_id}")
        if (
            not isinstance(polygon, list)
            or len(polygon) < 3
            or not all(
                isinstance(point, list)
                and len(point) == 2
                and all(isinstance(value, (int, float)) for value in point)
                for point in polygon
            )
        ):
            raise RegionConfigError(f"区域{region_id}的polygon至少需要3个二维坐标")

        points = [
            (int(round(point[0] * scale_x)), int(round(point[1] * scale_y)))
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

    def __init__(self, regions):
        self.regions = regions
        self.current_region = None
        self.entered_at = None
        self.last_timestamp = 0.0
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
            return []

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
