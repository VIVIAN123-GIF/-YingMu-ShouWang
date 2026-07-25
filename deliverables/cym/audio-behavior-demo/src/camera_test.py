import argparse
import json
import time

import cv2


def parse_args():
    parser = argparse.ArgumentParser(description="OpenCV摄像头读取测试")
    parser.add_argument("--camera", type=int, default=0, help="摄像头编号")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="不显示窗口，适合自动验收",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=0.0,
        help="自动退出秒数；0表示不限制",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="自动退出帧数；0表示不限制",
    )
    args = parser.parse_args()

    if args.max_seconds < 0:
        parser.error("--max-seconds不能小于0")
    if args.max_frames < 0:
        parser.error("--max-frames不能小于0")
    if args.headless and args.max_seconds == 0 and args.max_frames == 0:
        args.max_seconds = 5.0

    return args


def main():
    args = parse_args()
    cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(args.camera)

    if not cap.isOpened():
        print(f"无法打开摄像头：{args.camera}")
        return 2

    print("摄像头已打开，按q退出")
    frame_count = 0
    first_shape = None
    started_at = time.perf_counter()
    stop_reason = "unknown"

    try:
        while True:
            if args.max_seconds and time.perf_counter() - started_at >= args.max_seconds:
                stop_reason = "max_seconds"
                break

            ok, frame = cap.read()
            if not ok:
                print("读取摄像头画面失败")
                stop_reason = "camera_read_failed"
                break

            frame_count += 1
            if first_shape is None:
                first_shape = list(frame.shape)

            if not args.headless:
                cv2.imshow("Camera Test", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    stop_reason = "user_quit"
                    break

            if args.max_frames and frame_count >= args.max_frames:
                stop_reason = "max_frames"
                break
    finally:
        cap.release()
        if not args.headless:
            cv2.destroyAllWindows()

    summary = {
        "camera_index": args.camera,
        "frames_processed": frame_count,
        "first_frame_shape": first_shape,
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "stop_reason": stop_reason,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    return 1 if stop_reason == "camera_read_failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
