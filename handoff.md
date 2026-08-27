# 荧目守望项目交接说明

> 更新时间：2026-08-26（Asia/Shanghai）
>
> 开发冻结目标：2026-08-31；初审材料截止：2026-09-05。
>
> 本文不包含凭证、设备标识、参与者信息、私有素材名称、绝对路径或姿态关键点。

## 1. 一句话状态

`ruleset-v1.2` 起身后即时不稳事件、`ruleset-v1.3-min` 个体化多源前置预警、
后端/前端/智能体、环形缓冲、回放验收器和 Windows 发布包已经形成可运行工程闭环。

当前已经完成工程实现、自动化正向夹具、授权录制像素负向回放、风险/恢复真实像素正向回放，
以及真实设备 H.264 三次取流和环形缓冲探测。真实设备告警 Webhook 仍被公网回调失败阻塞，尚未形成
`LIVE_DEVICE/simulated=false` 的算法任务和保守裁决记录。不得把自动化 Mock 或录制回放写成真实老人验证。

## 2. 当前架构和规则边界

### 2.1 双层规则

- `ruleset-v1.2` 检测一次有效坐站转换后的即时姿态不稳，并负责确定性 RiskEvent 裁决。
- `ruleset-v1.3-min` 输出三时间尺度、四分量的工程风险指数，不输出跌倒概率。
- 即时窗口为 8 秒，短时窗口为 30 秒，趋势窗口为 180 秒；24 小时和 7 天窗口用于长期记忆。
- 四分量为人体风险、个人偏离、环境风险和人境交互风险。
- 个人偏离采用中位数和 MAD；不足三天的有效个人素材保持 `INSUFFICIENT`。
- 环境证据不能单独创建跌倒事件，必须与合格人体证据同窗才形成交互风险。

### 2.2 v1.2 即时事件

- 先确认有效坐站转换，再观察躯干摆动、骨盆横移、支撑面变化和补偿步。
- ORANGE 至少需要两个独立信号族，且证据必须绑定同一次转换 Observation。
- 单一异常、偏快/偏慢起身或步态不对称保持 `YELLOW/REVIEW`。
- 遮挡、低质量、错误机位、持续转身和证据不足返回 `UNKNOWN/REVIEW`，不能显示为 GREEN。
- 授权 `RECORDED_REPLAY/simulated=true` 可用于 ORANGE 工程演示。
- `LIVE_DEVICE/simulated=false` 在正向验证完成前最多为 `YELLOW/REVIEW`，不自动干预。

### 2.3 声明边界

对外统一使用：

- 工程风险指数；
- 起身后姿态不稳事件；
- 授权录制回放；
- 人工复核；
- 自动化夹具验证。

禁止使用：

- 未来跌倒概率；
- 临床诊断或医学有效性；
- 已完成真实老人验证；
- Mock 语音等同于设备真实播报；
- 历史回放等同于实时等待。

## 3. 已完成的工程内容

### 3.1 算法和场景

- GAIT 与 TRAJECTORY 顺序消费同一次进程内姿态序列，不持久化原始关键点。
- TRAJECTORY 已计算骨盆轨迹、危险区停留、障碍相交、支撑区距离和画面亮度。
- `SceneCalibration` 支持 `HIGH_RISK`、`SUPPORT`、`OBSTACLE`、`SAFE` 归一化多边形。
- 发布包携带两份脱敏示例场景；真实机位需用本地安装工具配置，不开放无鉴权写接口。
- 低质量、跟踪不足、无人体和场景缺失均保守降级，不伪装为安全。

### 3.2 后端、前端和智能体

- Worker 链路已覆盖 Asset、Observation、Evidence、ForewarningSnapshot、RuleTrace、RiskEvent 和 Agent Job。
- 事件创建时保存 `PRE_INTERVENTION`，恢复后保存 `POST_INTERVENTION`，并回写 `risk_after`。
- 已提供最新预警、历史预警、事件前后快照和场景查询接口。
- 首页展示四分量、三时间尺度、基线状态、置信等级、主要证据和降级原因。
- 事件详情展示干预前后指数、恢复状态和来源标识。
- 智能体只解释证据、置信度和建议动作；模型不可用时使用模板降级。

### 3.3 环形缓冲和启动器

- Stream Buffer Worker 默认保留短期私有分片，并优先拼接告警前 10 秒和告警后 20 秒。
- 缓冲未预热、覆盖不足或拼接失败时，Alarm Worker 保守回退到告警后直录。
- `live` 在 `YINGMU_STREAM_BUFFER_ENABLED=true` 时启动 API、Alarm Worker、Agent Worker 和 Stream Buffer Worker。
- `demo` 始终保持 API、Alarm Worker 和 Agent Worker 三进程，不访问真实设备。
- 启动器统一监控和回收子进程；任一进程异常退出会终止整组进程。
- `self-check` 验证关键模块、规则集、姿态模型、场景配置和运行目录，不访问设备。

### 3.4 发布和验收

- 源码 ZIP 的代码和配置只收集发布白名单内且已进入 Git 索引的文件，避免把本地未跟踪工具混入发布包。
- 官方姿态模型是唯一允许进入源码包的外部运行时文件；模型不进入 Git，打包时必须通过固定 SHA-256 校验。
- 源码构建缺少 TRAJECTORY、风险复核、环形缓冲、场景配置等必需文件时直接失败。
- Windows 包包含姿态模型、脱敏场景配置、完整配置模板、`self-check` 和统一启动器。
- Windows 构建在压缩前和重新解压后各运行一次 `self-check + Demo`。
- `run_v13_closed_loop_acceptance.py` 支持显式 `NO_EVENT` 和 `EVENT_RESOLVED`。
- `EVENT_RESOLVED` 强制风险/恢复双输入、分别拍摄时间和至少 60 秒记录时间线。
- 干预使用 `mock_voice/simulated=true`，不会冒充萤石真实语音。
- 验收报告检查全部跨表引用，任一阶段缺失时非零退出。

## 4. 最新验证基线

最终上传前已执行以下检查：

- Python 全量测试通过；
- 前端 Vitest 全量测试和 Vite 生产构建通过；
- `compileall` 通过；
- 数据库 14 张表验证通过；
- `git diff --check` 通过；
- 源码 ZIP 和 Windows ZIP 隐私扫描、SHA-256 清单和全新解压验证通过；
- 授权真实录制像素 `NO_EVENT` 通过，未创建 RiskEvent、Agent Job 或 InterventionResult；
- Windows Demo 最终为 `RESOLVED`，退出后无残留监听端口。

以仓库中的最新 CI 结果和本地 `output/fresh-release-validation.json` 为最终数字；`output/` 已忽略，不上传 Git。

### 4.1 现场验收前 P0 工程修复

2026-08-26 已完成以下不依赖真实设备的工程修复：

- 恢复证据不再要求恢复段重复坐站转换，仍严格要求稳定至少 15 秒、躯干角不超过 8 度和有效跟踪质量；
- 正向回放验收器支持 `--scene-config-dir`，可读取仓库外最终机位配置，并检查风险/恢复两次任务的双模块状态；
- 实机直播录制和环形缓冲成片增加 H.264 严格门禁，脱敏报告保留 `codec_name`；
- Stream Buffer Worker 与 Windows 启动器退出时立即清除临时分片、工作区、状态和死亡锁，正式 Asset 不受影响；
- 新增 `docs/field-acceptance/` 轻量现场授权、采集台账、场景示例和实机验收模板。

工程门禁已经就绪。2026-08-26 后续已补齐授权风险/恢复真实像素和 `camera_01` 私有场景，并从干净提交完成回放复验；`LIVE_DEVICE/simulated=false` 现场记录仍未产生。

### 4.2 P03 评价口径已冻结

P03 已停止使用统一 `RISK_PRECURSOR/NORMAL_CONTROL` 二分类和全局 Accuracy，改为即时事件、步态/趋势两条独立评价轨。正式主结果仅允许配置 A，B-D 消融在存在可执行实现并另行冻结前暂缓。

冻结口径、机器规范和推理结果 Schema 位于 `experiments/three-participant/`。最终 `rule-freeze.json` 必须同时绑定 P03 lock、v1.2、v1.3-min、模型、评价文件、结果 Schema 和正式执行器哈希。

当前仍缺少自动处理 P03 全部32段并生成 `p03-inference-results/1.0` 的正式批量执行器。因此 `generate-predictions` 已被禁止，P03 继续保持锁定，不得手工填写预测表或直接运行现有算法脚本代替正式执行器。
正式结果契约要求每段保留有序 Evidence（含片内时间、质量和严重度）及完整 RuleTrace 序列；分析器按冻结 v1.2 规则重放同源 Observation 和 30 秒窗口，旧 `risk_status`/二分类结果不再作为裁决依据。

### 4.3 正向真实像素回放已通过

2026-08-26 已在干净 worktree、提交 `27c9f406e780688a7b5991f8bf7bfaba026cf8db` 上复验同一授权参与者、同一固定机位的风险/恢复双片段。私有场景为 `scene-camera-01-v1`，四类多边形已通过场景契约和 TRAJECTORY 双片段探测。

最终 `RECORDED_REPLAY/simulated=true` 报告为 `PASS`：两段 GAIT 均为 `SUCCESS`，两段 TRAJECTORY 均为合法 `NO_EVIDENCE` 且无模块失败；风险段创建唯一 ORANGE 事件，完成 `mock_voice` 模拟干预，恢复段产生 `posture_recovered`，事件依次进入 `OBSERVING` 和 `RESOLVED`。前后干预快照、跨表引用和 latest/history/baseline/events API 均通过。

脱敏报告 SHA-256 为 `9F574FF0A570F969C8495330397E9C6AC6DCA420F0BA308412108CBF96CA324C`；私有运行清单另行绑定代码、规则、模型、视频、标签、场景、数据库和报告哈希。该结果不是 `LIVE_DEVICE`、P03 或临床验证。最新 v1.3-min 快照仍因个人基线不足而为 `PARTIAL`，不得宣称个体化基线已验证。

### 4.4 真实设备取流和缓冲探测已通过

2026-08-26 已访问授权真实设备并完成以下脱敏工程检查：

- 正式直播流连续探测三次，三次均为 `SUCCESS` 和 `codec_name=h264`；每次录制 15 秒、10 FPS、150 帧；
- Stream Buffer Worker 达到 `ready=true`，告警前连续覆盖达到 10 秒；
- 缓冲完整窗口拼接为 30 秒 H.264 MP4，10 FPS、300 帧，真实探测时长和覆盖时长均为 30 秒；
- 私有 `scene-camera-01-v1`、姿态模型和 `live.env` 必填门禁已经安装并通过本地检查；
- 本地 API `/health` 可用，公网临时入口的 GET 可返回 200；无签名 POST 能到达本机并被正式验签门禁返回 401，说明本地路由和拒绝无签名请求的行为正常。

以上只证明真实取流、H.264、缓冲、场景和本机服务可用，不等于真实告警端到端验收完成。当前数据库尚无由本次真实 `ys.alarm` 产生的任务、事件或复核记录。

本轮联调暴露了两个尚未提交的工程修复：连续 FFmpeg 分片的文件时间戳轻微抖动不应累计误报覆盖不足；Windows 退出需要终止虚拟环境解释器的整棵后代进程树。修改后的真实缓冲拼接已成功，相关定向测试通过；但 Windows `taskkill` 非零返回和终止失败时禁止提前清理的分支仍需补强，当前修改不得直接与其他工作区文件一起提交。

## 5. 当前真正卡住的问题

### 5.1 正向真实像素双片段已完成

该项不再阻塞。已在算法运行前完成双人独立标注和仲裁冻结，并使用同一授权参与者、同一固定机位完成：

1. 风险段：有效坐站转换后出现至少两个独立且清晰的不稳信号；
2. 恢复段：姿态稳定并满足恢复观察窗口。

最终干净提交回放为 `PASS`。原始视频、标签、数据库和运行清单只保存在仓库及 OneDrive 外的私有目录；不得根据算法结果反向修改标签或降低阈值。

### 5.2 camera_01 回放场景已校准

私有 `scene-camera-01-v1` 已绑定 `camera_01` 和 `1280x720` 画幅，包含危险区、支撑区、障碍区和安全区；风险/恢复两段 TRAJECTORY 均成功加载并完成评估。该配置不得进入 Git，也不得用于其他机位。

正式实机验收前仍须由现场人员确认摄像机、焦距、椅子、柜体和门厅边界未发生变化；任一项变化都必须重新标定并生成新场景 ID。

### 5.3 萤石 Webhook 公网推送失败

这是 2026-08-26 当晚真实设备联调的当前首要阻塞，也是此前实机联调未出现的新问题。萤石平台多次显示国标告警消息和设备属性变更消息为“超时异常”或“服务降级”，但同一时间本机服务日志没有对应平台 POST，隔离数据库也没有新任务。

已经确认：

- 本地 API、H.264 取流、环形缓冲和场景配置正常；
- 从普通公网客户端访问临时入口的 `/health` 可得到 200；
- 公网无签名 POST 可到达本机并被验签门禁返回 401；
- 萤石平台失败时本机没有收到请求，因此现有证据更符合“萤石云出口到临时公网隧道不可达或不稳定”，不能归因于 GAIT、TRAJECTORY、H.264、通道号或本地签名逻辑；
- 临时公网入口只能用于连通性试验，当前不具备正式验收所需的稳定性。

当前不得把平台列表中的“推送失败”写成已收到 `ys.alarm`，也不得通过关闭验签或启用无签名测试模式绕过阻塞。所有失败尝试和报告目录应保留，不覆盖、不选择性删除。

### 5.4 真实设备算法闭环尚未完成

由于平台 Webhook 没有到达本机，以下验收项仍无真实记录：

- 真实 `ys.alarm` 创建并消费 Alarm Task；
- 告警窗口 Asset 入库以及 GAIT/TRAJECTORY 双模块执行；
- `source_mode=LIVE_DEVICE`、`simulated=false` 的跨表来源继承；
- 实机保守 `YELLOW/REVIEW`，且不创建 ORANGE RiskEvent；
- 不创建 Agent Job、InterventionResult，不自动播报；
- 最终一次完整会话的正常退出回收记录。

最后一次记录时启动器和临时公网隧道可能仍在运行。明日接续前先检查 8000 端口、萤目 Python/Worker 进程和缓冲锁，不要假定昨夜进程已经退出；若仍在运行，分别在启动器和隧道终端执行一次 `Ctrl+C`，确认退出后再建立新会话。

### 5.5 语音和外部服务

- 当前真实设备语音没有完成资源与能力验证，不能宣称自动播报。
- Agent 外部模型不是闭环必需条件；验收默认允许模板降级。
- 公网 Webhook 临时通道可能失效，每次实机验收前必须重新检查 `/health` 和回调地址。

## 6. 下一位接手者的执行计划

### A. 从远端复验工程基线

```powershell
git pull --ff-only
powershell -ExecutionPolicy Bypass -File scripts\setup_algorithm_runtime.ps1
.\.venv\Scripts\python.exe -m scripts.yingmu_launcher self-check
.\.venv\Scripts\python.exe -m pytest -q
Set-Location frontend
npm ci
npm test -- --run
npm run build
```

不要复用本地 `output/` 判断远端是否完整；发布包必须从当前提交重新构建。

### B. 复核最终机位场景标定（回放已完成）

1. 固定摄像头位置、焦距、画幅和照明；
2. 用归一化坐标填写四类多边形；
3. 运行场景安装工具写入仓库外私有配置目录；
4. 运行 `self-check` 和 TRAJECTORY 定向测试；
5. 截图只展示脱敏多边形和结果，不展示设备信息。

### C. 保全正向风险/恢复证据（回放已完成）

当前通过素材、冻结标签、私有场景、数据库、报告和运行清单必须按授权期限原样保留，不得覆盖。只有机位、素材、规则、模型或代码变化时才重新建立全新隔离数据库运行；重试不得覆盖既有失败和通过记录。

正向命令结构：

```powershell
.\.venv\Scripts\python.exe scripts\run_v13_closed_loop_acceptance.py `
  --expected-outcome EVENT_RESOLVED `
  --input <授权风险视频> `
  --recovery-input <授权恢复视频> `
  --database <临时数据库> `
  --private-root <仓库外私有目录> `
  --captured-at <风险段带时区拍摄时间> `
  --recovery-captured-at <恢复段带时区拍摄时间> `
  --resolve-at <满足60秒窗口的裁决时间> `
  --retention-until <带时区保留期限> `
  --report <脱敏报告>
```

当前最终报告已同时包含 ORANGE、Agent Job、模拟干预、OBSERVING、RESOLVED 和 POST 快照，且引用完整，因此真实像素工程正向回放已通过。

### D. 完成实机受控联调

明日从 Webhook 连通性恢复开始，不需要重做已经通过的三次 H.264 正式探测和缓冲拼接，除非摄像机编码、网络、机位或配置发生变化。

1. 先正常停止仍在运行的旧启动器和临时隧道，记录退出结果；检查 8000 端口、Worker、缓冲锁和状态文件；
2. 保留现有探测报告和失败推送记录，新建带时间戳的重试报告目录，不复用或覆盖旧数据库；
3. 更换为团队已有稳定 HTTPS 入口或稳定公网隧道，优先使用有明确可用性和请求日志的入口；
4. 在平台改回调前，依次验证本地 `/health`、公网 `/health` 和公网 POST 路由；正式配置继续保持签名校验开启、无签名测试关闭；
5. 在萤石平台更新回调地址并先发送平台测试消息，必须同时看到平台成功、入口访问日志、本机 POST 日志和 HTTP 2xx；只有其中一项不能算打通；
6. 确认缓冲再次为 `ready=true` 且前置覆盖不少于 10 秒，然后由授权健康成年人执行正常安全动作触发真实告警，不实施跌倒；
7. 核对 Asset、任务摘要、GAIT/TRAJECTORY 状态、Evidence、Snapshot 和 RuleTrace；模块不得为 `FAILED/LOW_QUALITY`；
8. 核对所有记录继承 `LIVE_DEVICE/simulated=false`，裁决保持 `YELLOW/REVIEW`，RiskEvent、Agent Job、InterventionResult 和自动播报均为零；
9. 在启动器终端执行 `Ctrl+C`，确认所有后代进程、缓冲分片、工作目录、锁、状态文件和 8000 端口均已回收；
10. 填写脱敏实机验收 JSON，只记录任务引用、模块状态、codec、缓冲模式、来源、裁决和清理计数，不记录设备标识、凭证、临时公网地址或私有路径。

若平台仍显示超时/服务降级且本机无 POST，继续处理公网入口或联系萤石平台支持，不要反复触发真人动作。若本机已收到 POST 但返回 401/403，再转查消息类型对应的签名算法、时间戳窗口和 `EZVIZ_WEBHOOK_SECRET`；两类故障不能混为一谈。

### E. 9 月 1-5 日材料准备

- 冻结代码和规则，不临时调阈值；
- 统一研究报告、系统设计、接口、测试报告和演示视频措辞；
- 明确区分自动化 Mock、真实像素负向、已通过的真实像素正向回放和待执行的真实设备联调；
- 展示可审计引用关系和降级策略，不展示私有素材或凭证；
- 将后续研究路线与截止前已实现功能分开。

## 7. 已踩过的坑

### Git 和发布

- 不要使用 `git add .`；本地可能存在私有素材、个人计划和浏览器诊断文件。
- Fresh 验证必须验证准备提交的 Git 文件集合，不能把未跟踪脚本混入源码 ZIP。
- 输出 ZIP、运行日志、数据库和私有媒体都不进入 Git。
- 源码 ZIP 测试通过不代表暂存区完整；提交前同时检查 staged 和 unstaged。
- Windows 上 `subprocess` 应解析 `npm.cmd`，不能假设裸 `npm` 可直接执行。

### Windows 打包

- 不要把行为算法目录放到 PyInstaller 顶层 `--paths`，否则会遮蔽项目自己的 `adapters` 包。
- Windows 包必须从 ZIP 重新解压验证，不能复用构建目录。
- Demo 必须先提交有效坐站转换，再提交躯干和横移两类信号；旧的单信号顺序会得到 HTTP 409。
- `-SkipFrontend` 只允许在已有且已独立验证的生产构建存在时使用。

### 回放和时间线

- 私有媒体目录必须位于仓库外；数据库父目录也必须在启动验收器前创建。
- 所有拍摄时间必须带时区，恢复时间必须晚于风险时间，最终裁决必须满足 60 秒观察窗口。
- `RECORDED_TIMELINE` 是记录时间线，不代表程序真实等待了 60 秒。
- 低质量结果、无人体或场景缺失不能改写为 GREEN。

### 实机、Windows 和 Webhook

- PowerShell 的 `$变量`、反引号续行和 `New-Item` 不能直接粘贴到 CMD；先确认提示符包含 `PS`。CMD 中的多行反引号会被拆成错误命令。
- 文档中的尖括号是占位符，不能把 `<收到的文件.json>` 原样执行；必须替换为真实存在的路径，并先用 `Test-Path` 检查。
- 从仓库直接执行导入项目包的脚本时优先使用 `python -m scripts.<module>`，并确认当前目录和 `PYTHONPATH`；直接执行文件曾出现 `ModuleNotFoundError: contracts`。
- `live.env` 不存在或必填凭证、授权字段缺失时，探测必须停止；不得用空值绕过。该文件不进入聊天、Git、截图或提交材料。
- FFmpeg 路径必须指向真实存在的 `ffmpeg.exe`，同目录还要有 `ffprobe.exe`。本机旧 `.env` 曾指向已删除版本，导致全量测试中的视频探测失败；使用当前有效路径后为 `356 passed`。
- LocalTunnel 在 CMD 中应使用单行命令；PowerShell 才能使用反引号续行。公网 `/health` 成功只证明普通客户端可访问，不证明萤石云出口也能访问。
- 平台显示超时/服务降级且本机无 POST 时，先查公网入口、DNS、TLS、隧道服务和平台出口；本机收到 POST 后才查验签、消息体和业务处理。
- 未确认 Webhook 2xx 和缓冲 `ready=true` 前，不要让授权人员重复执行动作。真人动作只用于安全触发设备告警，不实施真实跌倒。
- Windows 虚拟环境解释器可能产生后代进程。只结束直接 `Popen` 会出现端口已释放但 Worker 和缓冲锁仍残留；退出必须终止整棵进程树并再次等待。
- 连续分片的文件时间戳可能存在轻微抖动，不能把累计元数据误差当作真实缺片；但缺号、超出既有容差、最终成片时长不足或非 H.264 仍必须失败。
- 临时隧道地址、设备标识和联系人曾出现在联调聊天中；结束本轮后应停用临时入口，后续报告不得复述这些值。

### 算法和材料

- 不要为了让现有片段触发 ORANGE 而降低 12 度参考量或篡改标签。
- 健康成年人授权模拟不能写成真实老人居家验证。
- 环境区域进入不能单独创建跌倒事件。
- `9/9` 控制样本未误报不等于 100% 特异度，也不证明正向召回。
- 一次工程快照不能外推为长期跌倒概率。

## 8. 截止后研究路线

以下内容不建议在 8 月 31 日前继续扩建：

- Seq2Seq、TCN、Transformer 时序预测；
- 3D Mesh、视角归一化和跨机位域适配；
- Deep SVDD 个体异常检测；
- 自动障碍物识别和动态场景图；
- 多摄像头融合、联邦学习和专用多智能体协作；
- 基于真实老年人样本的概率校准、灵敏度/特异度、外部验证和医学合作。

在伦理、授权、正负样本和外部验证完成前，不宣称跌倒概率或临床有效性。

## 9. 优先阅读文件

- `handoff.md`
- `docs/2026-08-26-起身后即时不稳规则-v1.2.md`
- `docs/2026-08-26-个体化多源跌倒前置预警-v1.3-min.md`
- `docs/ezviz-alarm-worker.md`
- `contracts/v1/gait_video.py`
- `contracts/v1/gait_adapter.py`
- `contracts/v1/decision.py`
- `backend/service/forewarning_service.py`
- `backend/service/algorithm_task_service.py`
- `backend/service/stream_buffer_service.py`
- `scripts/run_v13_closed_loop_acceptance.py`
- `scripts/validate_fresh_release.py`
- `scripts/yingmu_launcher.py`

下一位接手者的第一目标不是继续增加算法，而是恢复萤石平台到本机的稳定 Webhook 2xx，再完成 `LIVE_DEVICE/simulated=false` 的双算法、保守裁决和退出回收证据。真实正向双片段和最终机位回放标定已经完成，不需要重复执行。

## 10. 2026-08-27 最新交接状态

### 10.1 本轮已经完成

- P01、P02、P03的96段实验素材全部按负责人确认标记为`VALID`，P03冻结测试已经一次性运行并保持原结果；P02基线日期确认是2026-08-24。
- URFD官方cam0数据完成fresh raw独立复核：30段fall、40段adl，共70序列；140个源文件完成大小、SHA-256及适用的ZIP CRC校验。结果为`PUBLIC_DATASET`，未与自采数据混算，也未生成不适用的Accuracy、Precision、Recall或F1。
- P01、P02、P03各补录一段连续黄金闭环原片，时长分别为122.355秒、123.399秒和120.866秒。三段均从同一原片派生`0-30s`风险窗口和`30s-end`恢复窗口，并在全新隔离数据库中独立验收。
- 三段黄金闭环的GAIT均为`SUCCESS`，TRAJECTORY均为允许的`NO_EVIDENCE`且无模块失败；三次均创建ORANGE、执行`mock_voice/simulated=true`模拟干预、进入OBSERVING并最终RESOLVED，引用完整性和读取API全部通过。
- P03黄金片已标记为`SUPPLEMENTAL_GOLDEN_LOOP`，没有进入P03的24段独立测试集，也没有重新计算或覆盖P03正式0/4 ORANGE结果。
- 已生成`experiments/three-participant/results/golden-loop-results.json`和脱敏三人汇总；原始人像视频、派生媒体、数据库和详细验收报告均由`.gitignore`排除。
- 2026-08-27 22:23运行正式组包门禁：`formal_documents`、`experiment`、`urfd`、`golden_loops`、`windows_release`和`source_release`均为`PASS`。

### 10.2 当前卡住的问题

- `stability`仍为`INCOMPLETE`：缺少`experiments/three-participant/results/stability-summary.json`，三次4小时或等价的12小时正式记录尚未形成。
- `authorization`和`signed_consent_scans`仍为`INCOMPLETE`：已有三个人的脱敏授权编号，但缺成年确认、签字完成状态和P01/P02/P03三份私有PDF扫描件。不得仅凭编号把授权摘要改成`COMPLETE`。
- `video_verification`和`final_video`仍为`INCOMPLETE`：缺少演示视频成片及其脱敏验收JSON。
- `external_windows`仍为`INCOMPLETE`：发布包尚未在另一台未安装项目Python/Node的Windows电脑上验收。
- `registration_form`、`platform_evidence`和`online_entry`仍未完成；Pages入口此前返回404，未恢复前不要写入提交邮件。
- 真实设备`LIVE_DEVICE/simulated=false`闭环仍被萤石平台到本机的Webhook稳定性阻塞。回放黄金闭环通过不能替代真实设备来源继承、保守裁决和退出回收证据。

### 10.3 下一步计划

1. 立即启动12小时稳定性记录，按三次4小时分别记录运行时长、风险事件、人工复核误报、系统异常、重启和未处理异常；实际不足12小时就报告实际时长，不补写目标值。
2. 同步收齐三份签字授权PDF和成年确认，只在私有目录保存扫描件；完成后更新脱敏`authorization-summary.json`，公开文件不得包含姓名或签字图像。
3. 在另一台干净Windows电脑完成解压、启动、页面、来源标识、关闭回收、清单和敏感扫描验收，生成`external-windows-acceptance.json`。
4. 录制5-7分钟演示视频和一份未跳切黄金闭环补充录屏，常驻标记`RECORDED_REPLAY`、`MOCK`或`LIVE_DEVICE`；生成`video-verification.json`后再进入正式组包。
5. 更换稳定HTTPS入口并恢复萤石Webhook 2xx，完成`LIVE_DEVICE/simulated=false`的H.264、缓冲、GAIT、TRAJECTORY、来源继承、YELLOW/REVIEW保守裁决和退出回收验收。
6. 补齐报名表、平台调用证据和在线入口验证，最后重新运行`python -m scripts.assemble_submission final`，只有总状态不再是`INCOMPLETE`才能称为正式提交包。

### 10.4 本轮踩过的坑

- 黄金闭环正式派生窗口必须按冻结脚本使用`0-30s`和`30s-end`。早期预检使用`0-45s`和`45s-end`虽通过，但不能直接作为正式口径，已用正式窗口重新运行三人验收。
- `private-root`必须位于Git仓库之外。第一次把临时私有存储放进仓库内部时，验收器正确拒绝并返回`private media storage must be outside the repository`。
- 只有躯干晃动属于单一信号族，不会创建ORANGE。首段预检虽检出坐站转换、21.104度躯干摆动和3次反转，但骨盆横移、支撑宽度和补偿步都未过门，因此保持YELLOW。后续拍摄通过受控骨盆横移和小幅补偿步形成第二独立信号族。
- `support_base_change`与`compensatory_step`都属于足部信号族，同时出现仍只算一个族；必须与躯干或骨盆横移族组合。
- `TRAJECTORY=NO_EVIDENCE`不等于模块失败。黄金闭环通过条件允许GAIT成功且TRAJECTORY有解释地无证据，但任何模块`FAILED`都必须判失败。
- P02早期15.399秒风险段和22.999秒恢复段曾打通工程链，但不是连续原片且总时长不足115秒，不能计入三段正式黄金闭环。
- 组包脚本应从仓库根目录使用`python -m scripts.assemble_submission final`。直接执行文件曾出现`ModuleNotFoundError: scripts`；总门禁存在缺项时命令以非零退出，即使其中`golden_loops=PASS`也属正常拒绝。
- 公开Git只能提交脱敏汇总、来源清单和代码。`视频/`、`data/raw/`、`results/private/`、签字扫描件、数据库和原始平台证据必须保持忽略。
