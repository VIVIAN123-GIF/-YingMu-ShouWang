import argparse
from pathlib import Path

import cv2
import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(
        description="生成不含人物的MP4输入链路测试视频"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/smoke.mp4"),
        help="输出MP4路径",
    )
    parser.add_argument("--seconds", type=float, default=4.0, help="视频时长")
    parser.add_argument("--fps", type=float, default=15.0, help="视频帧率")
    args = parser.parse_args()

    if args.seconds <= 0:
        parser.error("--seconds必须大于0")
    if args.fps <= 0:
        parser.error("--fps必须大于0")

    return args


def main():
    args = parse_args()
    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    width, height = 640, 480
    frame_count = max(1, round(args.seconds * args.fps))
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        args.fps,
        (width, height),
    )
    if not writer.isOpened():
        print("无法创建MP4，请检查OpenCV视频编码支持")
        return 2

    try:
        for frame_index in range(frame_count):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            progress = frame_index / max(1, frame_count - 1)
            x = int(30 + progress * (width - 60))
            y = int(height / 2 + 50 * np.sin(progress * 2 * np.pi))

            # 小圆点只用于产生可见运动，避免模拟成人体轮廓。
            cv2.circle(frame, (x, y), 18, (40, 220, 220), -1)
            writer.write(frame)
    finally:
        writer.release()

    print(f"已生成{frame_count}帧链路测试视频：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
