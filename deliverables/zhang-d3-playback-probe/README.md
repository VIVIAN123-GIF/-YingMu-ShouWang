# 张同学 D3 播放地址单次复验

## 验证命令

```powershell
py -3.14 scripts/validate_ezviz_live.py `
  --runs 1 `
  --interval-seconds 0 `
  --output-dir deliverables/zhang-d3-playback-probe
```

## 结果

| 阶段 | 结果 | 说明 |
|---|---|---|
| 设备状态 | SUCCESS | 设备在线，业务码 `200` |
| 真实抓拍 | FAILED | 业务码 `20008`，设备响应超时 |
| 临时播放地址 | SKIPPED | `SNAPSHOT_NOT_SUCCESSFUL` |

本次报告未包含凭证、完整设备序列号、图片或临时播放地址。临时播放地址能力仍标记为“部分验证或未稳定验证”，演示使用真实抓拍与真实录像回放。

## 能力矩阵口径

本次结果不改变项目最终能力矩阵：Token 获取、设备状态、WebHook、真实抓拍、WebHook 自动抓拍、Asset 私有入库均按既有实测记录标记为“已验证”；临时播放地址标记为“部分验证或未稳定验证”；文本大模型解释标记为“配置后可验证”；模板解释降级、Mock 语音/文字提醒已实现；萤石服务端语音仍未验证。
