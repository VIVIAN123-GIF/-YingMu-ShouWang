import cv2


cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)

if not cap.isOpened():
    print("无法打开摄像头")
    raise SystemExit

print("摄像头已打开，按 q 键退出")

while True:
    ok, frame = cap.read()

    if not ok:
        print("读取画面失败")
        break

    cv2.imshow("Camera Test", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()

