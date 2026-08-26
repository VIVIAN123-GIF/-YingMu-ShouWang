# 荧目守望项目交接说明

> 更新时间：2026-08-26（Asia/Shanghai）
>
> 开发冻结目标：2026-08-31；初审材料截止：2026-09-05。
>
> 本文不包含凭证、设备标识、参与者信息、私有素材名称、绝对路径或姿态关键点。

## 1. 一句话状态

`ruleset-v1.2` 起身后即时不稳事件、`ruleset-v1.3-min` 个体化多源前置预警、
后端/前端/智能体、环形缓冲、回放验收器和 Windows 发布包已经形成可运行工程闭环。

当前已经完成的是工程实现、自动化正向夹具和授权录制像素负向回放；尚未完成的是授权风险/恢复
两段真实像素正向验收，以及固定最终机位后的真实设备联调。不得把自动化 Mock 闭环写成真实老人验证。

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

## 5. 当前真正卡住的问题

### 5.1 正向真实像素双片段已完成

该项不再阻塞。已在算法运行前完成双人独立标注和仲裁冻结，并使用同一授权参与者、同一固定机位完成：

1. 风险段：有效坐站转换后出现至少两个独立且清晰的不稳信号；
2. 恢复段：姿态稳定并满足恢复观察窗口。

最终干净提交回放为 `PASS`。原始视频、标签、数据库和运行清单只保存在仓库及 OneDrive 外的私有目录；不得根据算法结果反向修改标签或降低阈值。

### 5.2 camera_01 回放场景已校准

私有 `scene-camera-01-v1` 已绑定 `camera_01` 和 `1280x720` 画幅，包含危险区、支撑区、障碍区和安全区；风险/恢复两段 TRAJECTORY 均成功加载并完成评估。该配置不得进入 Git，也不得用于其他机位。

正式实机验收前仍须由现场人员确认摄像机、焦距、椅子、柜体和门厅边界未发生变化；任一项变化都必须重新标定并生成新场景 ID。

### 5.3 真实设备 v1.3-min 联调待执行

本轮明确未访问真实设备。现场必须独立验证：

- H.264 实时视频采集；
- Stream Buffer Worker 达到 `ready=true`；
- GAIT/TRAJECTORY 双模块均被调用；
- `LIVE_DEVICE/simulated=false` 来源继承；
- 保守 `YELLOW/REVIEW` 裁决；
- 退出后缓冲、Worker 和监听端口正常回收。

### 5.4 语音和外部服务

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

1. 在本地私有配置中填写凭证和授权字段；
2. 启动 `live`，确认四进程条件编排；
3. 等待缓冲健康检查 `ready=true`；
4. 触发一次不含真实跌倒的授权受控动作；
5. 核对 Asset、任务摘要、双算法状态、Evidence、Snapshot 和 RuleTrace；
6. 确认真实来源保持保守复核，不因演示目的创建 ORANGE；
7. 停止服务并确认私有分片按保留策略清理。

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

下一位接手者的第一目标不是继续增加算法，而是完成“真实正向双片段 + 最终机位标定 + 实机保守裁决”三项证据。
