import argparse
import json
import math
import time
from collections import Counter, deque
from pathlib import Path

import cv2

from behavior_observations import build_behavior_observations
from regions import RegionConfigError, RegionTracker, draw_regions, load_region_config


FRAME_SIZE = (640, 480)


def analysis_content_rect(source_size, target_size=FRAME_SIZE):
    """Return the letterboxed content rectangle as x, y, width, height."""
    source_width, source_height = source_size
    target_width, target_height = target_size
    if source_width <= 0 or source_height <= 0:
        raise ValueError("输入帧尺寸无效")
    scale = min(target_width / source_width, target_height / source_height)
    content_width = max(1, int(round(source_width * scale)))
    content_height = max(1, int(round(source_height * scale)))
    return (
        (target_width - content_width) // 2,
        (target_height - content_height) // 2,
        content_width,
        content_height,
    )


def resize_for_analysis(frame, target_size=FRAME_SIZE):
    """Resize without distorting person proportions; pad unused pixels."""
    target_width, target_height = target_size
    source_height, source_width = frame.shape[:2]
    if source_width <= 0 or source_height <= 0:
        raise ValueError("输入帧尺寸无效")

    pad_left, pad_top, resized_width, resized_height = analysis_content_rect(
        (source_width, source_height), target_size
    )
    resized = cv2.resize(frame, (resized_width, resized_height))
    pad_right = target_width - resized_width - pad_left
    pad_bottom = target_height - resized_height - pad_top
    return cv2.copyMakeBorder(
        resized,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0),
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="OpenCV人员检测、活动量与中心轨迹Demo"
    )
    parser.add_argument(
        "--input",
        default="0",
        help="摄像头编号（例如0）或本地视频路径",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="不显示窗口，适合自动复现",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="最多处理多少帧；0表示不限制",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=0.0,
        help="最多运行多少秒；0表示不限制",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="可选的脱敏JSON运行摘要路径",
    )
    parser.add_argument(
        "--observation-output",
        type=Path,
        help="可选的Freeze v1.0 Observation JSON输出路径",
    )
    parser.add_argument(
        "--resident-id",
        default="resident-001",
        help="Observation中的脱敏老人标识",
    )
    parser.add_argument(
        "--location",
        default=None,
        help="可选区域标识，例如living_room",
    )
    parser.add_argument(
        "--asset-id",
        default=None,
        help="可选脱敏素材标识，不得填写绝对路径或访问密钥",
    )
    parser.add_argument(
        "--simulated",
        action="store_true",
        help="将本次输入标记为模拟实验",
    )
    parser.add_argument(
        "--region-config",
        type=Path,
        help="人工多边形区域JSON；坐标会自动缩放到640x480分析帧",
    )
    parser.add_argument(
        "--scene-config-id",
        default=None,
        help="区域配置必须匹配的脱敏scene_config_id",
    )
    parser.add_argument(
        "--region-events-output",
        type=Path,
        help="可选的ENTER/EXIT区域事件JSON输出路径",
    )
    parser.add_argument(
        "--statistics-output",
        type=Path,
        help="可选的访问区域、停留时长和转换统计JSON输出路径",
    )
    args = parser.parse_args()

    if args.max_frames < 0:
        parser.error("--max-frames不能小于0")
    if args.max_seconds < 0:
        parser.error("--max-seconds不能小于0")

    return args


def open_input(input_value):
    if input_value.lstrip("-").isdigit():
        camera_index = int(input_value)
        cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)

        # 非Windows或DirectShow不可用时，回退到OpenCV默认后端。
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(camera_index)

        return cap, {
            "input_type": "CAMERA",
            "input_name": f"camera:{camera_index}",
            "source_mode": "LIVE_DEVICE",
        }

    video_path = Path(input_value).expanduser().resolve()
    if not video_path.is_file():
        raise FileNotFoundError(f"视频文件不存在：{video_path}")

    return cv2.VideoCapture(str(video_path)), {
        "input_type": "VIDEO",
        "input_name": video_path.name,
        "source_mode": "RECORDED_REPLAY",
    }


class BehaviorAnalyzer:
    """分析原始帧并保存短时轨迹状态，不执行任何画面绘制。"""

    def __init__(self):
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.background = cv2.createBackgroundSubtractorMOG2(
            history=300,
            varThreshold=35,
            detectShadows=True,
        )
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        self.track_points = deque(maxlen=80)
        self.recent_steps = deque(maxlen=40)
        self.smoothed_point = None
        self.travel_distance = 0.0
        self.tracker = None
        self.tracker_initial_box = None
        self.tracker_missed_frames = 0
        self.max_tracker_missed_frames = 12

    @staticmethod
    def _box_area(box):
        return max(0, int(box[2])) * max(0, int(box[3]))

    @classmethod
    def _deduplicate_detections(cls, detections):
        """Remove HOG part-boxes that belong to one person's body column."""
        ordered = sorted(detections, key=lambda item: item["area"], reverse=True)
        kept = []
        for candidate in ordered:
            cx, cy, cw, ch = candidate["box"]
            candidate_area = cls._box_area(candidate["box"])
            duplicate = False
            for existing in kept:
                ex, ey, ew, eh = existing["box"]
                intersection_width = max(0, min(cx + cw, ex + ew) - max(cx, ex))
                intersection_height = max(0, min(cy + ch, ey + eh) - max(cy, ey))
                intersection = intersection_width * intersection_height
                horizontal_overlap = intersection_width / max(1, min(cw, ew))
                vertical_gap = max(0, max(cy, ey) - min(cy + ch, ey + eh))
                same_body_column = (
                    horizontal_overlap >= 0.55
                    and (
                        intersection_height / max(1, min(ch, eh)) >= 0.12
                        or vertical_gap <= 0.20 * max(ch, eh)
                    )
                )
                if (
                    candidate_area
                    and intersection / candidate_area >= 0.80
                ) or same_body_column:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(candidate)
        return kept

    def _reset_tracker(self, analysis_frame, box):
        """Start a short-lived tracker from a verified HOG detection."""
        tracker = cv2.TrackerKCF_create()
        try:
            # OpenCV Python bindings return None on successful init in some versions.
            tracker.init(analysis_frame, tuple(int(value) for value in box))
            self.tracker = tracker
            self.tracker_initial_box = tuple(int(value) for value in box)
            self.tracker_missed_frames = 0
        except cv2.error:
            self.tracker = None
            self.tracker_initial_box = None

    def _clear_tracker(self):
        self.tracker = None
        self.tracker_initial_box = None
        self.tracker_missed_frames = 0

    def _fallback_detection(self, analysis_frame):
        """Bridge brief HOG misses without turning long misses into detections."""
        if self.tracker is None:
            return None
        ok, box = self.tracker.update(analysis_frame)
        if not ok:
            self._clear_tracker()
            return None
        x, y, w, h = (int(round(value)) for value in box)
        frame_height, frame_width = analysis_frame.shape[:2]
        initial_area = self._box_area(self.tracker_initial_box or (x, y, w, h))
        current_area = self._box_area((x, y, w, h))
        visible_width = max(0, min(frame_width, x + w) - max(0, x))
        visible_height = max(0, min(frame_height, y + h) - max(0, y))
        visible_area = visible_width * visible_height
        if (
            w < 20
            or h < 40
            or self.tracker_missed_frames >= self.max_tracker_missed_frames
            or x >= frame_width
            or y >= frame_height
            or x + w <= 0
            or y + h <= 0
            or current_area < initial_area * 0.35
            or current_area > initial_area * 3.0
            or visible_area < current_area * 0.45
        ):
            self._clear_tracker()
            return None
        self.tracker_missed_frames += 1
        return {
            "box": (x, y, w, h),
            "confidence": 0.0,
            "area": int(w * h),
            "source": "KCF_TRACKER",
        }

    def analyze(self, analysis_frame):
        boxes, weights = self.hog.detectMultiScale(
            analysis_frame,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05,
        )

        detections = []
        for (x, y, w, h), weight in zip(boxes, weights):
            confidence = float(weight)
            if confidence < 0.35:
                continue
            detections.append(
                {
                    "box": (int(x), int(y), int(w), int(h)),
                    "confidence": confidence,
                    "area": int(w * h),
                    "source": "HOG",
                }
            )

        detections = self._deduplicate_detections(detections)

        hog_detected = bool(detections)
        if detections:
            largest = max(detections, key=lambda item: item["area"])
            x, y, w, h = largest["box"]
            self._reset_tracker(analysis_frame, (x, y, w, h))
            target_point = (x + w // 2, y + h // 2)
        else:
            fallback = self._fallback_detection(analysis_frame)
            if fallback is not None:
                detections = [fallback]
                x, y, w, h = fallback["box"]
                target_point = (x + w // 2, y + h // 2)
            else:
                target_point = None

        if target_point is not None:
            if self.smoothed_point is None:
                self.smoothed_point = target_point
            else:
                alpha = 0.35 if hog_detected else 0.20
                self.smoothed_point = (
                    int((1 - alpha) * self.smoothed_point[0] + alpha * target_point[0]),
                    int((1 - alpha) * self.smoothed_point[1] + alpha * target_point[1]),
                )

            step_distance = 0.0
            if self.track_points:
                previous_point = self.track_points[-1]
                step_distance = math.hypot(
                    self.smoothed_point[0] - previous_point[0],
                    self.smoothed_point[1] - previous_point[1],
                )

            if step_distance >= 2:
                self.travel_distance += step_distance
                self.recent_steps.append(step_distance)
            else:
                self.recent_steps.append(0.0)

            self.track_points.append(self.smoothed_point)
        else:
            # 没有检测到人时让短时活动标签逐步回落，但保留历史轨迹。
            self.recent_steps.append(0.0)

        recent_distance = sum(self.recent_steps)
        if recent_distance < 35:
            behavior_label = "STILL"
        elif recent_distance < 220:
            behavior_label = "WALKING"
        else:
            behavior_label = "HIGH MOVEMENT"

        # MOG2只接收未绘制的analysis_frame，避免框和文字污染运动区域。
        mask = self.background.apply(analysis_frame)
        _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)
        motion_area = int(cv2.countNonZero(mask))

        if motion_area < 1500:
            activity_level = "LOW"
        elif motion_area < 8000:
            activity_level = "MEDIUM"
        else:
            activity_level = "HIGH"

        return {
            "detections": detections,
            "person_count": len(detections),
            "track_points": list(self.track_points),
            "travel_distance": self.travel_distance,
            "recent_distance": recent_distance,
            "behavior_label": behavior_label,
            "motion_area": motion_area,
            "activity_level": activity_level,
            "tracked_point": self.smoothed_point if detections else None,
            "hog_detected": hog_detected,
            "tracked": bool(detections),
        }


def render_frame(analysis_frame, result):
    """在原始分析帧的副本上绘图，不改变传入的analysis_frame。"""
    display_frame = analysis_frame.copy()

    regions = result.get("regions", [])
    if regions:
        draw_regions(display_frame, regions, result.get("current_region"))

    for index, detection in enumerate(result["detections"], start=1):
        x, y, w, h = detection["box"]
        cv2.rectangle(
            display_frame,
            (x, y),
            (x + w, y + h),
            (0, 255, 0),
            2,
        )
        cv2.putText(
            display_frame,
            f"person {index}",
            (x, max(y - 8, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )

    track_points = result["track_points"]
    for index in range(1, len(track_points)):
        cv2.line(
            display_frame,
            track_points[index - 1],
            track_points[index],
            (255, 0, 255),
            3,
        )
    if track_points:
        cv2.circle(display_frame, track_points[-1], 6, (255, 0, 255), -1)

    activity_colors = {
        "LOW": (0, 255, 0),
        "MEDIUM": (0, 255, 255),
        "HIGH": (0, 0, 255),
    }
    behavior_colors = {
        "STILL": (0, 255, 0),
        "WALKING": (0, 255, 255),
        "HIGH MOVEMENT": (0, 0, 255),
    }

    labels = [
        (f"Persons: {result['person_count']}", (255, 255, 255)),
        (f"Motion area: {result['motion_area']}", (255, 255, 255)),
        (
            f"Activity: {result['activity_level']}",
            activity_colors[result["activity_level"]],
        ),
        (f"Track points: {len(track_points)}", (255, 0, 255)),
        (f"Travel distance: {result['travel_distance']:.0f}px", (255, 0, 255)),
        (
            f"Behavior: {result['behavior_label']}",
            behavior_colors[result["behavior_label"]],
        ),
    ]
    if regions:
        labels.append(
            (f"Region: {result.get('current_region') or 'outside/unknown'}", (0, 200, 255))
        )

    for index, (text, color) in enumerate(labels):
        cv2.putText(
            display_frame,
            text,
            (20, 30 + index * 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            color,
            2,
        )

    return display_frame


def write_summary(path, summary):
    output_path = path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"运行摘要：{output_path}")


def write_json(path, payload, label):
    output_path = path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{label}：{output_path}")


def write_observations(path, observations):
    output_path = path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(observations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Observation输出：{output_path}")


def main():
    args = parse_args()

    try:
        cap, input_info = open_input(args.input)
    except FileNotFoundError as error:
        print(error)
        return 2

    if not cap.isOpened():
        print(f"无法打开输入源：{input_info['input_name']}")
        cap.release()
        return 2

    analyzer = BehaviorAnalyzer()
    source_width = int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH)))
    source_height = int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    try:
        content_rect = analysis_content_rect((source_width, source_height))
    except ValueError:
        content_rect = (0, 0, FRAME_SIZE[0], FRAME_SIZE[1])
    regions = []
    region_tracker = None
    if args.region_config:
        try:
            regions = load_region_config(
                args.region_config,
                FRAME_SIZE,
                expected_scene_config_id=args.scene_config_id,
                content_rect=content_rect,
            )
        except RegionConfigError as error:
            print(error)
            cap.release()
            return 2
        region_tracker = RegionTracker(regions)
    frame_count = 0
    detected_frame_count = 0
    tracked_frame_count = 0
    max_person_count = 0
    max_motion_area = 0
    activity_counts = Counter()
    started_at = time.perf_counter()
    stop_reason = "unknown"

    video_fps = cap.get(cv2.CAP_PROP_FPS)
    if input_info["input_type"] == "VIDEO" and video_fps > 0:
        display_delay_ms = max(1, round(1000 / video_fps))
    else:
        display_delay_ms = 1

    print(
        f"行为检测已启动，输入源：{input_info['input_name']}，"
        "按q退出"
    )

    try:
        while True:
            if args.max_seconds and time.perf_counter() - started_at >= args.max_seconds:
                stop_reason = "max_seconds"
                break

            ok, frame = cap.read()
            if not ok:
                if input_info["input_type"] == "VIDEO":
                    print("视频播放结束")
                    stop_reason = "video_eof"
                else:
                    print("读取摄像头画面失败")
                    stop_reason = "camera_read_failed"
                break

            # analysis_frame在整个分析阶段保持未绘制状态。
            # 保持原始宽高比，避免16:9视频被拉伸为4:3后影响HOG人体检测。
            analysis_frame = resize_for_analysis(frame)
            result = analyzer.analyze(analysis_frame)

            frame_count += 1
            if result["hog_detected"]:
                detected_frame_count += 1
            if result["tracked"]:
                tracked_frame_count += 1
            max_person_count = max(max_person_count, result["person_count"])
            max_motion_area = max(max_motion_area, result["motion_area"])
            activity_counts[result["activity_level"]] += 1

            if region_tracker is not None:
                if input_info["input_type"] == "VIDEO" and video_fps > 0:
                    relative_seconds = (frame_count - 1) / video_fps
                else:
                    relative_seconds = time.perf_counter() - started_at
                region_tracker.update(result["tracked_point"], relative_seconds)
                result["regions"] = regions
                result["current_region"] = region_tracker.current_region

            if not args.headless:
                display_frame = render_frame(analysis_frame, result)
                cv2.imshow("Behavior Demo", display_frame)
                if cv2.waitKey(display_delay_ms) & 0xFF == ord("q"):
                    stop_reason = "user_quit"
                    break

            if args.max_frames and frame_count >= args.max_frames:
                stop_reason = "max_frames"
                break
    finally:
        cap.release()
        if not args.headless:
            cv2.destroyAllWindows()

    elapsed_seconds = time.perf_counter() - started_at
    region_statistics = None
    if region_tracker is not None:
        if input_info["input_type"] == "VIDEO" and video_fps > 0:
            final_timestamp = frame_count / video_fps
        else:
            final_timestamp = elapsed_seconds
        region_statistics = region_tracker.finalize(final_timestamp)
    summary = {
        "schema_version": "1.0",
        "input_type": input_info["input_type"],
        "input_name": input_info["input_name"],
        "source_mode": input_info["source_mode"],
        "simulated": bool(args.simulated),
        "frames_processed": frame_count,
        "detected_frames": detected_frame_count,
        "tracked_frames": tracked_frame_count,
        "detection_quality": round(detected_frame_count / frame_count, 4) if frame_count else 0.0,
        "tracking_quality": round(tracked_frame_count / frame_count, 4) if frame_count else 0.0,
        "max_person_count": max_person_count,
        "max_motion_area": max_motion_area,
        "activity_counts": dict(activity_counts),
        "track_points": len(analyzer.track_points),
        "travel_distance_px": round(analyzer.travel_distance, 3),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "stop_reason": stop_reason,
        "threshold_status": "DEMO_UNCALIBRATED",
        "scene_config_id": args.scene_config_id,
        "analysis_resize_mode": "LETTERBOX",
        "analysis_content_rect": list(content_rect),
    }
    if region_statistics is not None:
        detected_ratio = tracked_frame_count / frame_count if frame_count else 0.0
        region_statistics.update(
            {
                "source_mode": input_info["source_mode"],
                "simulated": bool(args.simulated),
                "confidence": 0.50,
                "data_quality": round(min(1.0, detected_ratio), 4),
                "detection_quality": round(
                    detected_frame_count / frame_count, 4
                ) if frame_count else 0.0,
            }
        )
        summary["region_statistics"] = region_statistics

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.summary_output:
        write_summary(args.summary_output, summary)
    if args.region_events_output:
        if region_tracker is None:
            print("--region-events-output需要同时提供--region-config")
            return 2
        write_json(
            args.region_events_output,
            {
                "schema_version": "1.0",
                "source_mode": input_info["source_mode"],
                "simulated": bool(args.simulated),
                "confidence": 0.50,
                "data_quality": region_statistics["data_quality"],
                "events": region_tracker.events,
            },
            "区域事件输出",
        )
    if args.statistics_output:
        if region_statistics is None:
            print("--statistics-output需要同时提供--region-config")
            return 2
        write_json(args.statistics_output, region_statistics, "区域统计输出")
    if args.observation_output:
        observations = build_behavior_observations(
            summary,
            resident_id=args.resident_id,
            location=args.location,
            asset_id=args.asset_id,
        )
        write_observations(args.observation_output, observations)

    return 1 if stop_reason == "camera_read_failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
