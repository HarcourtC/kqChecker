# kqChecker 架构与使用说明

此文档简要描述项目架构、推荐的运行环境（包含 conda 环境 `Ykt`）、各个模块的职责、主要配置项以及常见运行/部署/测试操作，便于开发者和运维理解代码结构并快速上手。

## 概览
kqChecker 是一个用于从院校考勤接口定期查询/匹配课程考勤记录，并在未检测到预期出勤时发送通知的 Python 工具。支持常驻调度（长期运行）或一次性/测试式运行。

主要特性：
- 周期性读取本地 `weekly.json`（由获取脚本或手动生成），在课程开始前触发考勤查询。
- 匹配逻辑包含按课程名匹配和基于时间的回退匹配（并尝试按地点/教室进一步确认）。
- 可通过 SMTP 发送电子邮件通知（支持 SSL/TLS）。
- 支持 Windows 服务（NSSM）或 Task Scheduler 等多种部署方式。

项目根结构（摘要）：
```
config_example.json
fetch_periods.py
gen_weekly_ics.py
generate_ics.py
get_weekly_json.py
main.py
README.md
real_api_response_20251111T152425.json
weekly_schedule.ics
weekly.json
kq/
    __init__.py
    config.py
    icsgen.py
    inquiry.py
    schedulegen.py
    scheduler.py
    __pycache__/
```

## 推荐运行环境（Conda 环境 `Ykt`）
说明：历史上本项目在若干环境中运行，推荐使用 `conda` 创建一个隔离环境 `Ykt` 以便管理 Python 版本与二进制依赖。

示例创建步骤：
1. 安装 Anaconda / Miniconda。
2. 创建并激活环境（示例）：

```powershell
conda create -n Ykt python=3.11 -y
conda activate Ykt
pip install -r requirements.txt
```

（可选）`envs/Ykt.yml` 可用来精确重现依赖；此仓库包含 `requirements.txt`（或请使用 `pip freeze` 导出后生成）。

推荐依赖（示例）：
- Python 3.10+ (3.11 或 3.12/3.13 均兼容)
- requests
- python-dateutil

## 重要模块说明
下面按文件说明每个模块的职责、关键函数、输入/输出与错误模式。

### kq/config.py
- 作用：从仓库根目录读取 `config.json` 并返回一个字典。
- 关键函数：`load_config()` -> Dict
- 异常处理：如果文件不可读或解析失败，返回空字典 `{}`（调用方须处理缺失字段情况）。

### kq/schedulegen.py
- 作用：从外部 API 或原始日程数据生成 `weekly.json`、以及可选的 ICS（日历）文件。
- 主要用途：将周计划规范化为 `weekly.json`，并在条目中包含 `course` 和 `room` 字段（当前实现会把房间信息以结构化形式写入）。

### kq/icsgen.py
- 作用：将 `weekly.json` 转换为 `.ics` 日历文件，便于导入到日历客户端。

### kq/inquiry.py
- 作用：与考勤 API（api2）交互，发送 POST 请求并执行匹配逻辑。
- 核心函数：`post_attendance_query(event_time, courses=..., ...) -> bool`
  - 输入：`event_time` (datetime), `courses` (list of course entries 或字符串)
  - 输出：返回 True 表示已找到匹配考勤记录，False 表示未找到或请求失败。
- 匹配策略：
  1. 按课程名精确匹配（从 API 返回的 `subjectBean.sName` 比较）。
  2. 若无匹配，使用基于时间的回退匹配（例如 -20/+5 分钟窗口），并尝试按 `room`（教室/设备号）进行进一步验证。
- 通知：在找不到匹配时会异步发送“缺勤通知”（通过 `kq/notifier.py`）；最近也加入了“检测到匹配时亦可发送通知（可配置）”的逻辑。

### kq/matcher.py
- 作用：包含时间轴匹配的帮助函数，如 `match_records_by_time()`，用于在响应中查找时间接近的扫码/打卡记录。

### kq/notifier.py
- 作用：渲染模板并通过 SMTP 发送邮件。
- 关键函数：
  - `send_miss_email(cfg, subject=None, body=None, context=None) -> bool`：同步发送邮件。
  - `send_miss_email_async(...) -> bool`：在后台线程发送邮件（推荐用于调度器/非阻塞场景）。
  - `render_notification(cfg, context) -> (subject, body)`：仅渲染模板，不发送。
- 模板配置位置：`config.json` 下 `notifications` 字段（例如 `miss_subject`, `miss_body` 等）。
- 安全：如果 SMTP 配置缺失，会记录并跳过发送，不会抛异常中断主流程。

### kq/scheduler.py
- 作用：主调度器，长期运行；加载 `weekly.json`，在课程开始前（默认 5 分钟）触发 `post_attendance_query`。
- 行为要点：
  - 心跳日志（每个 poll tick 记录一次），默认轮询间隔 300 秒（5 分钟）。
  - 仅在每日的发布窗口（07:40 — 19:40）内对网络 POST 发起请求，避免在午夜等不期望时间触发外部接口。
  - 使用日志轮转（`logs/attendance.log`，10MB，保留 20 个备份）。
  - 可选：在启动时发送启动通知（`notifications.on_startup`），在匹配到记录时发送匹配通知（`notifications.on_match`）。

### 其他脚本
- `get_weekly_json.py`：获取远程 API 并写入 `weekly.json`（可作为定期刷新脚本）。
- `run_once_locked.py`：用于避免 Task Scheduler 重复触发导致的重叠运行（文件系统锁定）。
- `scripts/preview_notification.py`：渲染并打印通知模板（便于本地验证模板文本而不发送邮件）。

## 配置（`config.json`）
重要字段（示例）：
- `api1`, `api2`：远程 API URL（获取日程、查询考勤等）。
- `headers`：发送到考勤接口时需要的请求头（如授权 token）。
- `smtp`：SMTP 配置：`host`、`port`、`username`、`password`、`from`、`to`。
- `notifications`：通知相关模板与开关：
  - `on_startup`: 布尔（是否在 scheduler 启动时发送通知）
  - `startup_subject`, `startup_body`：启动邮件模板（{date},{time},{host}）
  - `on_match`: 布尔（是否在检测到匹配时也发送通知）
  - `match_subject`, `match_body`：匹配邮件模板（{courses},{date},{matches}）
  - `miss_subject`, `miss_body`：缺勤（未匹配）邮件模板（保持向后兼容）

建议把敏感信息（SMTP 密码、API token）放在受限文件或环境变量，并在 `config.json` 中留空或引用占位符以避免源码仓库泄露。

## 运行与部署
- 本地快速运行（一次性测试）
  - 使用 Python 解释器直接运行 `main.py`：

```powershell
# 仅做一次性/测试运行
py -3 main.py --test --dry-run
# 或在激活 conda 环境后
python main.py --once --dry-run
```

- 推荐长期部署（Windows）：
  - 使用 NSSM 将 `py`（或虚拟环境内的 python.exe）包装为 Windows 服务；或使用 Task Scheduler 创建一个在系统启动时运行的任务，指向 `run_once_locked.py` 或 `main.py`。仓库中提供了 `scripts/register_task_scheduler.ps1` 示例脚本。

## 日志与监控
- 日志位置：`<repo_root>/logs/attendance.log`（自动轮转，10MB，保留 20 个）。
- 日志中包含 heartbeat、每次触发的检查、匹配/未匹配摘要、HTTP 请求错误堆栈。推荐将日志定期上传到中央日志服务或使用文件监控（例如 Windows Event Log / Splunk / ELK）。

## 测试建议
- 模板渲染：使用 `scripts/preview_notification.py` 预览模板渲染结果。
- 邮件发送：先用 `--dry-run` 或配置一个测试 SMTP（例如临时的 Mailtrap），确认邮件格式和模板再切换到真实 SMTP。

## 开发与贡献
- 代码风格：尽量保持与现有文件一致的缩进与日志策略。
- 改动建议：在更改匹配逻辑或通知行为前编写小型回归测试（如模拟 API 响应），并在 PR 中包含日志片段以便审查。

## 附录：常见问题
- 服务启动没有发送邮件：检查 `config.json` 中 `notifications.on_startup` 是否开启，并检查 `logs/attendance.log` 里的发送协程日志与 `kq/notifier.py` 的错误输出。
- 无法匹配到考勤记录：查看 time-based 候选日志输出（候选结构化摘要），确认 `room` 字段是否在 API 返回中存在或需要额外的设备号映射策略。

---
文档到此结束。如果你想，我可以：
- 把 `config_example.json` 更新为包含新的 `notifications` 字段示例；
- 生成 `envs/Ykt.yml`（或 `requirements.txt`）并把 Ykt 环境文件提交到仓库；
- 添加两份快速测试脚本：`scripts/test_startup_notification.py` 和 `scripts/test_match_notification.py`，以便无需修改运行时配置就能验证渲染与发送流程。

请告诉我下一步要我做哪一项（或让我全部完成）。

## 开发与服务环境分离：`kq_dev`（开发） vs `ykt`（运行/服务）

为避免开发与生产冲突，推荐采用双环境策略：

- 开发环境（`kq_dev`）
  - 用于本地开发、单元测试与调试。
  - 可频繁安装/升级依赖、运行测试脚本（如 `scripts/test_*`）。
  - 不作为长期运行的服务环境，避免开发中断影响生产。

- 服务环境（`ykt`）
  - 专用于长期运行的服务实例（NSSM / Task Scheduler / systemd），配置为稳定、只在确认为安全的变更后才更新。
  - 服务应直接指向 `ykt` 环境内的 `python.exe`（不要依赖 shell activate 脚本）。

安全切换与升级建议（零停机或短停机策略）

1. 克隆并准备新环境（推荐用于升级）：
   - 在管理员或 Anaconda Prompt 中执行：
     ```cmd
     conda create -n ykt_next --clone ykt
     # 或从 requirements 创建新 env
     conda create -n ykt_next python=3.11 -y
     conda activate ykt_next
     python -m pip install -r e:\Program\kaoqing\requirements.txt
     ```
   - 在 `ykt_next` 中运行完整的 smoke test（例如调用 `main.py --test` 或执行仓库的测试脚本）。

2. 切换服务到新环境（短停机窗口）
   - 将 NSSM / Task Scheduler 中的 Program 路径从 `...\envs\ykt\python.exe` 改为 `...\envs\ykt_next\python.exe`，保持参数（`e:\Program\kaoqing\main.py`）不变。
   - 重启服务并验证日志（`logs/attendance.log`）。若一切正常，可删除旧环境：
     ```cmd
     conda remove -n ykt -y --all
     conda rename -n ykt_next -new-name ykt    # 注意：conda 没有直接 rename 命令，建议用 clone->remove 或记录名称变更流程
     ```

3. 如果不能短停机，可采用蓝绿式部署（两个并行服务，逐步切换流量/任务）或使用容器化方案（Docker）以实现更平滑切换。

如何配置服务使用 `ykt`（NSSM 示例）

1) 找到 `ykt` 的 python.exe 路径，例如：
   - `C:\Users\<你>\anaconda3\envs\ykt\python.exe`（按实际路径替换）

2) NSSM 配置要点（命令示例，需管理员权限，替换路径）：
   ```powershell
   # 设置应用为 ykt.python
   D:\NSSM\nssm.exe set kqChecker Application C:\Users\you\anaconda3\envs\ykt\python.exe
   D:\NSSM\nssm.exe set kqChecker AppParameters "e:\Program\kaoqing\main.py"
   D:\NSSM\nssm.exe set kqChecker AppDirectory "e:\Program\kaoqing"
   D:\NSSM\nssm.exe restart kqChecker
   ```
   > 说明：将上面的命令在管理员 PowerShell 或 CMD 中执行；更改后注意查看服务是否成功启动与日志输出。

Task Scheduler（GUI）要点

- 在 `Actions` 中填 `Program/script` 为 `C:\Users\you\anaconda3\envs\ykt\python.exe`，`Add arguments` 为 `e:\Program\kaoqing\main.py`，`Start in` 为 `e:\Program\kaoqing`。

注意事项与常见陷阱

- 永远不要在生产服务中直接运行 `conda activate` 脚本作为服务入口（activation 会导致环境变量仅在交互 shell 中设置，且依赖 shell 的初始化）。直接指向解释器路径更可靠。
- 在更新 `ykt`（pip/conda install/upgrade）之前**先停止服务**，完成后再重启。
- 如果频繁需要测试新依赖，优先在 `kq_dev` 做变更，然后把稳定版本“推广”到 `ykt`（通过 clone 或新建 env 并切换服务）。

此节记录了推荐的流程与实际操作示例。如需，我可以：

- 把一份简化的“切换服务到 ykt”的操作指南追加到 `README.md`（一键 copy/paste 命令）；
- 或根据你当前的服务类型（NSSM / Task Scheduler）生成精确的变更步骤。 
