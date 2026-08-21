# “萤目守望”最终交付工作区

本目录保存最终交付的可维护源稿和执行清单，不保存真实凭证、原始人脸视频、签字授权原件或私有数据库。

## 当前状态

| 交付项 | 当前状态 | 完成门禁 |
|---|---|---|
| 专项研究报告 | 工作底稿 | P03结果、消融、12小时数据写入后复核 |
| 演示视频 | 脚本和镜头清单 | 补拍、旁白、字幕、来源标签和脱敏完成 |
| Windows程序 | ZIP已构建，本机全栈冒烟和清单复核通过 | 在另一台Windows电脑验收 |
| 系统/接口/部署文档 | 工作底稿 | 与最终发布包和规则版本一致 |
| 测试报告 | 工程证据已汇总，真实实验待填 | 96段、P03盲测、消融、12小时完成 |
| 隐私材料 | 模板和边界已建立 | 三人签字及删除日期确认 |
| 提交门禁 | 草稿包可生成，最终模式会拒绝缺项 | 所有真实证据完成后状态变为READY |

正式文档源稿位于`docs/`，演示视频材料位于`video/`。生成的DOCX和PDF分别输出到`output/docx/`和`output/pdf/`。

## 发布命令

```powershell
# 白名单源码包；自动排除.env、数据库、原始媒体、签字授权和TEST_LOCKED
.\.venv\Scripts\python.exe -m scripts.build_source_release

# 草稿允许缺少真实实验和视频，但状态固定显示为INCOMPLETE
.\.venv\Scripts\python.exe -m scripts.assemble_submission draft

# 最终模式存在任一缺项、PENDING标记或敏感项时以非零状态退出
.\.venv\Scripts\python.exe -m scripts.assemble_submission final
```

最终视频放入`input/萤目守望-演示视频.mp4`，并根据`video/video-verification.template.json`完成人工复核。另一台Windows电脑的验收结果根据`../packaging/external-windows-acceptance.template.json`填写。两者都必须引用当前成品，不能提前勾选。

## 禁止提交

- `.env`、AccessToken、AppSecret、设备验证码或完整设备序列号；
- P01-P03原始视频和未脱敏授权原件；
- 私有数据库、临时URL、本地绝对路径；
- 仍包含`PENDING_REAL_DATA`的文档或视频字幕；
- 把`RECORDED_REPLAY`、`PUBLIC_DATASET`或`MOCK`描述成实时实机闭环的材料。
