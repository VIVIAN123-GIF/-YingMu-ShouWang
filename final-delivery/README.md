# “萤目守望”最终交付工作区

本目录保存最终交付的可维护源稿和执行清单，不保存真实凭证、原始人脸视频、签字授权原件或私有数据库。

## 当前状态

| 交付项 | 当前状态 | 完成门禁 |
|---|---|---|
| 专项研究报告 | 已写入P03双轨结果，待最终材料复核 | 消融、12小时、URFD、实机正向闭环和正式PDF |
| 演示视频 | 脚本和镜头清单 | 补拍、旁白、字幕、来源标签和脱敏完成 |
| Windows程序 | ZIP已构建，本机全栈冒烟和清单复核通过 | 在另一台Windows电脑验收 |
| 系统/接口/部署文档 | 工作底稿 | 与最终发布包和规则版本一致 |
| 测试报告 | 已写入P03结果，未完成项已明确标注 | 消融、12小时、URFD、异机Windows验收 |
| 隐私材料 | 模板和边界已建立 | 三人签字及删除日期确认 |
| 提交门禁 | 草稿包可生成，最终模式会拒绝缺项 | 所有真实证据完成后状态变为READY |

正式文档源稿位于 `docs/`，07/08 号新增源稿位于 `official-docs/`，演示视频材料位于 `video/`。P01/P02全量演练和P03一次性盲测结果已归档；当前仍不是可提交终稿，必须继续补齐外部证据和剩余门禁。

## 本地参赛配置与私有输入

1. 复制 `submission-profile.example.json` 为 `private-input/submission-profile.json`，填写 `school`、`contact_name`、`mobile`、`submission_deadline`、`retention_until`、`online_url` 和 `online_username`。`private-input/` 已被 Git 忽略，手机号不会进入公开源码包。
2. 使用 `scripts/build_participant_consent.py` 生成 P01、P02、P03 授权书；打印签署后，将扫描件命名为 `P01.pdf`、`P02.pdf`、`P03.pdf`，放入 `experiments/three-participant/signed-consent/`。该目录已被 Git 忽略。
3. 张薇完善平台证据后，将 PDF 放为 `private-input/platform-evidence.pdf`；盖章报名表放为 `private-input/registration-form.pdf`；最终演示视频放为 `private-input/demonstration-video.mp4`。
4. 公网 Pages 验收通过后，从 Actions 的 `pages-public-verification` 工件下载 `online-entry-verification.json`，放入 `private-input/online-entry-verification.json`。在真实公网测试完成前不得手工标记为 `COMPLETE`。

## 发布命令

```powershell
# 白名单源码包；自动排除.env、数据库、原始媒体、签字授权和TEST_LOCKED
.\.venv\Scripts\python.exe -m scripts.build_source_release

# 草稿允许缺少真实实验和视频，但状态固定显示为INCOMPLETE
.\.venv\Scripts\python.exe -m scripts.assemble_submission draft

# 最终模式存在任一缺项、PENDING标记或敏感项时以非零状态退出
.\.venv\Scripts\python.exe -m scripts.assemble_submission final
```

草稿文档位于 `output/submission-work/draft/`，草稿提交包位于 `output/submission/`。正式模式只有在实验、12 小时运行、三份授权扫描件、报名表、演示视频、平台证据、Windows 异机验收和在线入口公网验收全部通过后才会生成；否则只在提交目录外写出拒绝报告。

最终视频需根据 `video/video-verification.template.json` 完成人工复核。另一台 Windows 电脑的验收结果根据 `../packaging/external-windows-acceptance.template.json` 填写。两者都必须引用当前成品，不能提前勾选。

## GitHub Pages 在线入口

Pages 固定使用 Mock 数据、Hash 路由和会话级演示登录，不启动后端、数据库、Worker 或萤石接口。该登录只是静态演示门禁，不是生产级认证；公开站点不得存放敏感数据。

```powershell
Set-Location frontend
npm ci
npm test
npm run build:pages
Set-Location ..
.\.venv\Scripts\python.exe scripts\validate_pages_build.py --dist frontend\dist
Set-Location frontend
npm run test:pages
```

首次发布前，在 GitHub 仓库 `Settings > Pages > Build and deployment` 中选择 `GitHub Actions`。推送到 `main` 后，工作流会先完成本地测试与隐私扫描，再部署 Pages，最后对实际公网地址复验九个页面、登录、Hash 刷新、移动端布局和无 API 请求。预期地址为 `https://vivian123-gif.github.io/-YingMu-ShouWang/`。

## 禁止提交

- `.env`、AccessToken、AppSecret、设备验证码或完整设备序列号；
- P01-P03原始视频和未脱敏授权原件；
- 私有数据库、临时URL、本地绝对路径；
- 仍包含实验数据占位标记的文档或视频字幕；
- 把`RECORDED_REPLAY`、`PUBLIC_DATASET`或`MOCK`描述成实时实机闭环的材料。
