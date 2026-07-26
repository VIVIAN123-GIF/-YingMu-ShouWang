"""萤石接口调研阶段的地址配置骨架。

当前仓库尚未提交可运行的FastAPI Mock或真实DeviceAdapter；默认使用mock地址，
避免尚未验证的代码意外请求真实平台。
"""

import os


ENV = os.getenv("YINGMU_DEVICE_MODE", "mock").lower()

if ENV == "mock":
    BASE_URL = "http://127.0.0.1:8001/mock"
elif ENV == "live":
    BASE_URL = "https://open.ys7.com/api/lapp"
else:
    raise ValueError("YINGMU_DEVICE_MODE must be 'mock' or 'live'")

API_TOKEN = f"{BASE_URL}/token/get"
API_LIVE_ADDRESS = f"{BASE_URL}/live/address/get"
# 待实机和官方接口核验，不得在材料中写成已实现能力。
API_VOICE_TALK = f"{BASE_URL}/voice/send"
