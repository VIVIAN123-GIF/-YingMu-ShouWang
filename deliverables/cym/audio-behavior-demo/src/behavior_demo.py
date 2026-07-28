import argparse
import json
import math
import time
from collections import Counter, deque
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import cv2

from observation import build_observation, validate_observation_collection


FRAME_SIZE = (640, 480)


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
                }
            )

        if detections:
            largest = max(detections, key=lambda item: item["area"])
            x, y, w, h = largest["box"]
            target_point = (x + w // 2, y + h // 2)

            if self.smoothed_point is None:
                self.smoothed_point = target_point
            else:
                alpha = 0.35
                self.smoothed_point = (
                    int(
                        (1 - alpha) * self.smoothed_point[0]
                        + alpha * target_point[0]
                    ),
                    int(
                        (1 - alpha) * self.smoothed_point[1]
                        + alpha * target_point[1]
                    ),
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
        }


def render_frame(analysis_frame, result):
    """在原始分析帧的副本上绘图，不改变传入的analysis_frame。"""
    display_frame = analysis_frame.copy()

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


def build_behavior_observations(
    summary,
    *,
    resident_id,
    location=None,
    asset_id=None,
):
    """把一次行为Demo运行摘要转换为可校验的直接观测。"""
    frame_count = summary["frames_processed"]
    detected_ratio = (
        summary["detected_frames"] / frame_count if frame_count else 0.0
    )
    activity_counts = summary["activity_counts"]
    dominant_activity = (
        max(activity_counts, key=activity_counts.get)
        if activity_counts
        else "UNKNOWN"
    )

    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    common = {
        "resident_id": resident_id,
        "timestamp": timestamp,
        "source": "tracking",
        "location": location,
        "confidence": 0.50,
        "data_quality": 0.60 if frame_count else 0.0,
        "source_mode": summary["source_mode"],
        "asset_id": asset_id,
        "simulated": summary["simulated"],
        "metadata": {
            "adapter_version": "behavior-adapter-v1",
            "threshold_status": summary["threshold_status"],
            "frames_processed": frame_count,
            "score_status": "DEMO_UNCALIBRATED",
        },
    }

    feature_specs = [
        ("max_person_count", summary["max_person_count"], "count"),
        ("person_detected_frame_ratio", round(detected_ratio, 4), "ratio"),
        ("dominant_activity_level", dominant_activity, None),
        ("max_motion_area", summary["max_motion_area"], "pixel"),
        ("track_point_count", summary["track_points"], "count"),
        ("travel_distance", summary["travel_distance_px"], "pixel"),
    ]

    observations = [
        build_observation(
            observation_id=f"obs-behavior-{uuid4().hex}",
            feature_name=feature_name,
            feature_value=feature_value,
            unit=unit,
            **common,
        )
        for feature_name, feature_value, unit in feature_specs
    ]
    return validate_observation_collection(observations)


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
    frame_count = 0
    detected_frame_count = 0
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
            analysis_frame = cv2.resize(frame, FRAME_SIZE)
            result = analyzer.analyze(analysis_frame)

            frame_count += 1
            if result["person_count"] > 0:
                detected_frame_count += 1
            max_person_count = max(max_person_count, result["person_count"])
            max_motion_area = max(max_motion_area, result["motion_area"])
            activity_counts[result["activity_level"]] += 1

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
    summary = {
        "schema_version": "1.0",
        "input_type": input_info["input_type"],
        "input_name": input_info["input_name"],
        "source_mode": input_info["source_mode"],
        "simulated": bool(args.simulated),
        "frames_processed": frame_count,
        "detected_frames": detected_frame_count,
        "max_person_count": max_person_count,
        "max_motion_area": max_motion_area,
        "activity_counts": dict(activity_counts),
        "track_points": len(analyzer.track_points),
        "travel_distance_px": round(analyzer.travel_distance, 3),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "stop_reason": stop_reason,
        "threshold_status": "DEMO_UNCALIBRATED",
    }

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.summary_output:
        write_summary(args.summary_output, summary)
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
