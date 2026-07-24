import math
from collections import deque

import cv2


# 打开摄像头
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

if not cap.isOpened():
    print("无法打开摄像头")
    raise SystemExit

# OpenCV内置行人检测器
hog = cv2.HOGDescriptor()
hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

# 用于检测画面变化
background = cv2.createBackgroundSubtractorMOG2(
    history=300,
    varThreshold=35,
    detectShadows=True,
)

# 保存最近一段人体中心点和移动距离
track_points = deque(maxlen=80)
recent_steps = deque(maxlen=40)
smoothed_point = None
travel_distance = 0.0

print("行为检测已启动，按 q 键退出")

while True:
    ok, frame = cap.read()

    if not ok:
        print("读取画面失败")
        break

    frame = cv2.resize(frame, (640, 480))

    # 1. 行人检测
    boxes, weights = hog.detectMultiScale(
        frame,
        winStride=(8, 8),
        padding=(8, 8),
        scale=1.05,
    )

    person_count = 0
    detections = []

    for (x, y, w, h), weight in zip(boxes, weights):
        if float(weight) < 0.35:
            continue

        person_count += 1
        detections.append(((x, y, w, h), w * h))

        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(
            frame,
            f"person {person_count}",
            (x, max(y - 8, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )

    # 单人Demo优先跟踪面积最大的人体框
    if detections:
        largest_box, _ = max(detections, key=lambda item: item[1])
        bx, by, bw, bh = largest_box
        target_point = (bx + bw // 2, by + bh // 2)

        # 指数平滑，降低HOG检测框抖动
        if smoothed_point is None:
            smoothed_point = target_point
        else:
            alpha = 0.35
            smoothed_point = (
                int((1 - alpha) * smoothed_point[0] + alpha * target_point[0]),
                int((1 - alpha) * smoothed_point[1] + alpha * target_point[1]),
            )

        if track_points:
            previous_point = track_points[-1]
            step_distance = math.hypot(
                smoothed_point[0] - previous_point[0],
                smoothed_point[1] - previous_point[1],
            )
            if step_distance >= 2:
                travel_distance += step_distance
                recent_steps.append(step_distance)
            else:
                recent_steps.append(0.0)

        track_points.append(smoothed_point)

    # 最近窗口移动状态，仅作为未经标定的Demo标签
    recent_distance = sum(recent_steps)
    if recent_distance < 35:
        behavior_label = "STILL"
        behavior_color = (0, 255, 0)
    elif recent_distance < 220:
        behavior_label = "WALKING"
        behavior_color = (0, 255, 255)
    else:
        behavior_label = "HIGH MOVEMENT"
        behavior_color = (0, 0, 255)

    for i in range(1, len(track_points)):
        cv2.line(
            frame,
            track_points[i - 1],
            track_points[i],
            (255, 0, 255),
            3,
        )

    if track_points:
        cv2.circle(frame, track_points[-1], 6, (255, 0, 255), -1)

    # 2. 活动量检测
    mask = background.apply(frame)
    _, mask = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    motion_area = cv2.countNonZero(mask)

    if motion_area < 1500:
        activity_level = "LOW"
        color = (0, 255, 0)
    elif motion_area < 8000:
        activity_level = "MEDIUM"
        color = (0, 255, 255)
    else:
        activity_level = "HIGH"
        color = (0, 0, 255)

    # 3. 显示状态
    cv2.putText(
        frame,
        f"Persons: {person_count}",
        (20, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2,
    )
    cv2.putText(
        frame,
        f"Motion area: {motion_area}",
        (20, 65),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )
    cv2.putText(
        frame,
        f"Activity: {activity_level}",
        (20, 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        color,
        2,
    )
    cv2.putText(
        frame,
        f"Track points: {len(track_points)}",
        (20, 135),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 0, 255),
        2,
    )
    cv2.putText(
        frame,
        f"Travel distance: {travel_distance:.0f}px",
        (20, 170),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (255, 0, 255),
        2,
    )
    cv2.putText(
        frame,
        f"Behavior: {behavior_label}",
        (20, 205),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        behavior_color,
        2,
    )

    cv2.imshow("Behavior Demo", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()

