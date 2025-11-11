# kqChecker

轻量的考勤检查工具，用于从教务/考勤接口抓取课程周表、查询打卡（考勤）记录，并在预期上课时间前后检测是否有对应的打卡记录；当检测不到时通过邮件通知。文档以中文为主，示例命令面向 Windows PowerShell（项目在 `ykt` conda 环境下测试）。

## 目录
- 简介
- 快速开始
- 配置（`config.json`）
- 运行与常用脚本
- 匹配规则说明
- 通知模板与邮件
- 开发者说明
- 常见问题

## 简介
kqChecker 将三部分功能组合起来：
- 从学校 API 获取本学期/周的课程表 (api1)，保存为 `weekly.json`。
- 在上课前（默认提前 5 分钟）查询考勤流水（api2），尝试通过课程名或时间窗匹配出打卡记录。
- 如果既未通过名称匹配也未通过时间窗匹配到考勤记录，则异步发送邮件通知（SMTP）。

模块布局（位于 `kq/`）：
- `schedulegen.py`：获取/生成 `weekly.json` 与 `periods.json`，并提供 CLI。
- `scheduler.py`：调度器，定期检查 `weekly.json` 并触发考勤检测。
- `inquiry.py`：向 api2 发起查询并实现 name-based + time-based 匹配逻辑。
- `matcher.py`：时间窗匹配实现（`match_records_by_time`）。
- `notifier.py`：SMTP 邮件发送与模板渲染。
- `icsgen.py`：将 weekly.json / periods.json 生成 ICS 日历文件。

## 快速开始
先激活或创建 conda 环境（项目使用 `ykt` 环境测试，Python 3.13）：

```powershell
# 使用你本地的 conda 路径和环境名称，示例：
D:/ProgramData/miniconda3/Scripts/conda.exe run -p C:\Users\Harco\.conda\envs\ykt --no-capture-output cmd
```

在项目根下运行（示例）：

```powershell
# 一次性（one-shot）运行：处理将要在接下来 5 分钟内开始的事件
D:/ProgramData/miniconda3/Scripts/conda.exe run -p C:\Users\Harco\.conda\envs\ykt --no-capture-output python main.py --once --schedule weekly.json

# 测试模式（跳过网络调用）
D:/ProgramData/miniconda3/Scripts/conda.exe run -p C:\Users\Harco\.conda\envs\ykt --no-capture-output python main.py --once --dry-run --schedule weekly_test.json
```

注意：上面的 `conda.exe run -p ... python` 命令是基于当前工作环境路径，请根据你的机器调整为合适的 conda/环境路径或直接在激活环境后运行 `python main.py ...`。

## 配置（`config.json`）
配置文件包含 API 地址、请求头、以及 SMTP 信息。重要字段：

- `api1`, `api2`, `api3`：学校提供的接口地址。
- `headers`：默认用于对外 API 的请求头（例如鉴权 token）。
- `smtp`：邮件发送配置，包含 `host`, `port`, `username`, `password`, `from`, `to`。
- `notifications`：邮件模板（可自定义）：
  - `miss_subject`：缺席通知邮件主题模板，支持 `{courses}`, `{date}` 占位。
  - `miss_body`：邮件正文模板，支持 `{courses}`, `{date}`, `{candidates}`。

示例（已存在于仓库的 `config.json`）：

```json
"notifications": {
  "miss_subject": "[kqChecker] Attendance missing for {courses} on {date}",
  "miss_body": "Attendance check for courses {courses} on {date} returned no matches.\n\nCandidates:\n{candidates}\n\nThis is an automated message from kqChecker."
}
```

安全建议：不要把真实的 SMTP 密码或敏感 token 提交到远程仓库。建议在生产部署时通过环境变量、密钥管理或 CI secrets 注入配置，或把 `config.json` 加入 `.gitignore` 并在部署主机上手动管理。

## 运行与常用脚本
仓库中有若干便捷脚本用于开发与测试：
- `scripts/set_weekly_first.py --offset N`：把 `weekly_test.json` 的第一条事件移到当前时间 + N 分钟，方便 one-shot 触发。
- `scripts/run_local_match_test.py`：使用本地保存的 API 响应（或合成示例）测试时间窗匹配逻辑。
- `scripts/preview_notification.py`：基于当前 `config.json` 与上下文预览将发送的邮件主题与正文（不实际发送）。

日志位于项目根的 `attendance.log`，主要记录调度（scheduler）与通知的操作历史与异常。

## 匹配规则说明
匹配逻辑分两步：
1. Name-based（基于课程名）：在 API 返回的记录中查找 `subjectBean.sName` 或 `subjectBean.sSimple` 与 `weekly.json` 中课程名完全相等的项。
2. Time-based（基于时间窗）：当名称匹配失败时，会构造单个事件（课程的开始时间）并调用 `kq.matcher.match_records_by_time`，默认窗口为 `before=20min`, `after=5min`。时间字段会尝试 `operdate`, `watertime`, `intime`。

当前行为：若 time-based 找到候选记录则视为匹配成功（不会发送缺席通知）。若二者都未找到，才发送缺席通知；通知正文中的 `{candidates}` 会列出 time-based 的候选项（每行 `- time | subject | teacher`）。

注意：如果你希望在 time-based 找到候选时也发送一封低优先级的“候选”提醒（以便人工确认），可以在 `kq/inquiry.py` 将 time-based 分支改为仍发送通知但使用不同模板（已很容易实现）。

## 通知模板与邮件
通知通过 `kq/notifier.py` 发送，支持：
- 通过 `config.json` 的 `notifications` 字段配置主题与正文模板。
- `send_miss_email(cfg, subject=None, body=None, context=...)`：若 `subject`/`body` 为空，notifier 会使用配置中的模板并用 `context` 数据渲染。
- `send_miss_email_async(...)`：在后台线程中异步发送，默认为非守护线程以确保发送完成。

邮件正文的 `{candidates}` 列表会被格式化为多行，示例：
```
- 2025-11-11 16:05:00 | Test Course A | Teacher A
- 2025-11-11 14:03:00 | Test Course B | Teacher B
```
若该字段为空，会在邮件中留下空行（或你可以在模板中替换为空提示，例如写上 "(no candidates found)"）。

## 开发者说明
- 代码风格：尽量保持现有风格（小体量模块、简单函数式接口）。
- 可配置项：如果希望把 time-window、time_fields 等移入 `config.json`，可在 `kq/matcher.py` 与 `kq/inquiry.py` 中读取配置并替换硬编码值。
- 原地测试：可使用 `scripts/run_local_match_test.py` 与 `scripts/preview_notification.py` 在不联网或不发邮件的情况下验证逻辑。

建议在变更邮件发送逻辑前先使用 `preview_notification.py` 预览模板渲染，避免频繁真实发送邮件并触发 SMTP 限制。

## 常见问题
Q: 为什么邮件里 Candidates 为空？
A: 表示在 API 返回中没有任何记录落在你设置的时间窗内，或返回的时间字段名/格式不同，或根本没有考勤记录（可能确实无人打卡）。你可以：
- 检查 `attendance.log` 与原始 API 响应（如果保存）以确认时间字段名；
- 放宽时间窗（例如 before=30 / after=10）；
- 或在 `notifier` 模板中将空列表替换为更友好的说明。

Q: 邮件未发送/超时怎么办？
A: 检查 `config.json.smtp` 中的 `host/port/username/password`，并尝试使用 SSL(465) 或 STARTTLS(587)；日志 `attendance.log` 会包含发送错误堆栈。

## 贡献与许可
欢迎 issue / PR。请在提交前移除敏感配置信息（token/password），并在 README 中说明使用方法。此仓库默认未附带开源许可证，按需要添加 `LICENSE` 文件。

