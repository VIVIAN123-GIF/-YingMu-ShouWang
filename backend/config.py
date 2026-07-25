# backend/config.py
ENV = "prod"  # mock=本地模拟服务(暂未启用)，prod=正式萤石平台

if ENV == "mock":
    # 本地Mock服务地址，后续搭建mock服务再启用
    BASE_URL = "http://127.0.0.1:8001/mock"
else:
    BASE_URL = "https://open.ys7.com/api/lapp"

API_TOKEN = f"{BASE_URL}/token/get"
API_LIVE_ADDRESS = f"{BASE_URL}/live/address/get"
API_VOICE_TALK = f"{BASE_URL}/voice/send"