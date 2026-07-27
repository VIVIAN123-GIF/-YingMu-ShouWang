import time
from datetime import datetime
import httpx
import logging
from typing import Optional, Dict, Any
from backend.config import (
    EZVIZ_BASE_URL,
    EZVIZ_APP_KEY,
    EZVIZ_APP_SECRET,
    EZVIZ_ACCESS_TOKEN,
    EZVIZ_ACCESS_TOKEN_EXPIRES_AT,
    TOKEN_REFRESH_OFFSET
)

# 统一日志器，脱敏输出敏感信息
logger = logging.getLogger("ezviz_api_core")

# 全局内存缓存Token，服务运行期间常驻
_TOKEN_STORE: Optional[Dict[str, Any]] = None
_ENV_TOKEN_REJECTED = False

# 接口重试配置
MAX_RETRY_TIMES = 3
RETRY_INTERVALS = [2, 3, 5]


class EzvizAuth:
    @staticmethod
    async def get_valid_token() -> str:
        """
        获取有效accessToken，内存缓存复用，临近过期自动刷新
        脱敏打印日志，不输出完整密钥、完整token
        """
        global _TOKEN_STORE, _ENV_TOKEN_REJECTED
        now_ts = time.time()

        # 本地.env可注入平台当前Token；仅在仍有效时使用，绝不写入日志。
        if (not _ENV_TOKEN_REJECTED and _TOKEN_STORE is None and EZVIZ_ACCESS_TOKEN
                and EZVIZ_ACCESS_TOKEN_EXPIRES_AT):
            expires_at = datetime.fromisoformat(EZVIZ_ACCESS_TOKEN_EXPIRES_AT).timestamp()
            if now_ts < expires_at - TOKEN_REFRESH_OFFSET:
                _TOKEN_STORE = {"token": EZVIZ_ACCESS_TOKEN, "expire_time": expires_at}

        # 缓存存在且未过期，直接复用
        if _TOKEN_STORE is not None:
            expire_ts = _TOKEN_STORE["expire_time"]
            token = _TOKEN_STORE["token"]
            if now_ts < expire_ts - TOKEN_REFRESH_OFFSET:
                # 仅打印token末尾6位脱敏片段
                logger.info("复用缓存Token，脱敏片段：****%s", token[-6:])
                return token

        # 缓存失效，重新请求全新Token
        token_result = await EzvizAuth._fetch_new_token()
        expire_sec = token_result["expireTime"] / 1000
        _TOKEN_STORE = {
            "token": token_result["accessToken"],
            "expire_time": now_ts + expire_sec
        }
        logger.info("Token刷新完成，过期时间戳：%s", _TOKEN_STORE["expire_time"])
        return _TOKEN_STORE["token"]

    @staticmethod
    async def _fetch_new_token() -> Dict[str, Any]:
        """请求鉴权接口获取新Token，全程脱敏日志，禁止打印完整密钥"""
        url = f"{EZVIZ_BASE_URL}/token/get"
        form_data = {
            "appKey": EZVIZ_APP_KEY,
            "appSecret": EZVIZ_APP_SECRET
        }

        # 日志仅展示AppKey后四位，Secret完全隐藏不输出
        if EZVIZ_APP_KEY:
            logger.info("发起鉴权请求，AppKey脱敏后四位：****%s", EZVIZ_APP_KEY[-4:])
        else:
            logger.warning("环境变量 EZVIZ_APP_KEY 为空，鉴权将失败")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, data=form_data)
                resp_json = resp.json()
        except httpx.TimeoutException:
            raise ConnectionError("鉴权接口请求超时，请检查Mock/线上服务是否启动")
        except Exception as err:
            raise ConnectionError(f"鉴权网络请求异常：{str(err)}")

        code = resp_json.get("code")
        if code != "200":
            msg = resp_json.get("msg", "未知鉴权错误")
            raise ValueError(f"鉴权失败 code={code}, msg={msg}")

        return resp_json["data"]

    @staticmethod
    async def request(
        path: str,
        method: str = "POST",
        params: Dict = None,
        body: Dict = None
    ) -> Dict[str, Any]:
        """
        萤石统一请求封装
        1. accessToken 放入表单参数（官方标准，不放在header）
        2. 表单x-www-form-urlencoded传参
        3. 网络异常自动重试3次
        4. Token失效自动清空缓存，下一次请求自动刷新
        """
        retry_count = 0
        full_url = f"{EZVIZ_BASE_URL}{path}"

        while retry_count <= MAX_RETRY_TIMES:
            try:
                token = await EzvizAuth.get_valid_token()
                # 核心修复：把accessToken合并进表单，而非请求头
                form_body = {}
                if body:
                    form_body.update(body)
                form_body["accessToken"] = token

                async with httpx.AsyncClient(timeout=12.0) as client:
                    if method.upper() == "GET":
                        res = await client.get(full_url, params=params)
                    else:
                        res = await client.post(full_url, data=form_body)
                    result = res.json()

                # 业务错误码处理
                res_code = result.get("code")
                if res_code != "200":
                    # Token过期/失效，清空缓存，触发重试刷新Token
                    if res_code in ("10002", "10018"):
                        global _TOKEN_STORE, _ENV_TOKEN_REJECTED
                        _TOKEN_STORE = None
                        _ENV_TOKEN_REJECTED = True
                        logger.warning("Token已失效，清空缓存准备重试")
                        raise ValueError(f"token失效 code={res_code}")
                    # 无需重试的业务错误（参数缺失、设备不存在、无语音等）直接抛出
                    no_retry_codes = ("10001", "10017", "10030", "20002", "20014")
                    if res_code in no_retry_codes:
                        raise ValueError(f"接口{path}业务错误 code={res_code}, msg={result.get('msg')}")
                    # 其他临时异常继续重试
                    raise ValueError(f"接口{path}返回异常 code={res_code}, msg={result.get('msg')}")

                # 请求成功直接返回原始数据
                return result

            except (ConnectionError, ValueError) as err:
                retry_count += 1
                if retry_count > MAX_RETRY_TIMES:
                    logger.error("接口 %s 重试%d次全部失败，终止请求", path, MAX_RETRY_TIMES)
                    raise err
                sleep_sec = RETRY_INTERVALS[retry_count - 1]
                logger.warning("接口 %s 请求失败，第%d次重试，等待%ds", path, retry_count, sleep_sec)
                time.sleep(sleep_sec)
