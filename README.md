# Multi-Agent AI Coding 助手

基于 FastAPI、Pydantic v2 与 OpenAI 兼容接口实现的多智能体研发协作后端服务。系统通过 Planner、Context、Coder、Reviewer 四个 Agent 串联，完成需求拆解、上下文分析、代码生成与审查循环，并通过 HTTP API 暴露任务创建、审批和状态查询能力。

当前版本已经具备：

- 任务创建、审批、状态查询 API
- 基于内存状态存储的工作流引擎
- 多 Agent 串联的异步任务流转
- Context Agent 对 `workspace/` 目录下真实文件的安全读取能力
- 独立的 `benchmark.py` 自动化压测脚本

需要注意：

- 当前任务状态存储使用内存字典 `fake_db`，服务重启后任务会丢失
- 当前生成代码默认保存在任务的 `code_draft` 字段中，不会自动写回磁盘
- 由于状态保存在单进程内存中，部署时必须使用单 worker 运行

## 核心能力

### 1. Multi-Agent 工作流

系统将一次研发任务拆成两个阶段：

1. 规划阶段
   - Planner 根据自然语言需求生成结构化计划
   - 任务进入 `WAITING_FOR_APPROVAL`
2. 执行阶段
   - 用户审批通过后，Context 读取本地代码上下文
   - Coder 生成代码草稿
   - Reviewer 严格审查
   - 最多循环 3 次，直到 `COMPLETED` 或 `FAILED`

### 2. 真实文件上下文读取

Context Agent 会基于 `WORKSPACE_DIR` 读取 Planner 输出的目标文件：

- 支持读取已有文件内容
- 对不存在文件标记为 `NEW_FILE`
- 阻止路径穿越，例如 `../secret.txt`
- 将真实代码内容和需求一并交给大模型分析

### 3. 自动化评估基准

`benchmark.py` 会通过真实 HTTP API 完整跑通任务生命周期：

- 创建任务
- 轮询等待审批
- 自动审批
- 轮询等待完成
- 汇总完成率、耗时与 Reviewer 检出问题数

## 项目结构

```text
ai_coding_assistant/
├── app/
│   ├── api/               # HTTP 路由层
│   ├── agents/            # Planner / Context / Coder / Reviewer
│   ├── core/              # 配置与 LLM 客户端
│   ├── models/            # Pydantic 数据模型
│   ├── services/          # 工作流编排
│   └── main.py            # FastAPI 入口
├── workspace/             # 被 AI 读取的代码工作区
├── benchmark.py           # 基准测试脚本
├── requirements.txt
├── .env.example
└── README.md
```

## API 概览

### 健康检查

```http
GET /
```

返回示例：

```json
{
  "status": "ok",
  "message": "AI Coding Assistant API is running"
}
```

### 创建任务

```http
POST /api/v1/tasks/
Content-Type: application/json
```

请求体：

```json
{
  "requirement": "新增一个商品查询的 GET 接口，支持按价格区间和库存状态过滤"
}
```

### 查询任务状态

```http
GET /api/v1/tasks/{task_id}
```

### 审批任务

```http
POST /api/v1/tasks/{task_id}/approve
Content-Type: application/json
```

请求体：

```json
{
  "is_approved": true,
  "feedback": "可选，审批驳回时可填写意见"
}
```

## 环境要求

- Python 3.10+
- Conda 或 venv
- 可用的 OpenAI 兼容模型服务
- 有权限访问对应模型的 API Key

## 配置说明

项目通过 `.env` 读取运行配置。可以先从模板复制：

```bash
cp .env.example .env
```

关键配置如下：

```env
OPENAI_API_KEY=
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=glm-5
APP_NAME=ai_coding_assistant
APP_ENV=development
LOG_LEVEL=INFO
WORKSPACE_DIR=workspace
```

说明：

- `OPENAI_API_KEY`：必填
- `OPENAI_BASE_URL`：OpenAI 兼容接口地址
- `OPENAI_MODEL`：必须和上面的服务提供方匹配
- `WORKSPACE_DIR`：Context Agent 读取本地代码的目录

如果出现 `403 access_denied`，优先检查：

1. `OPENAI_BASE_URL` 与 `OPENAI_MODEL` 是否属于同一供应商
2. API Key 是否拥有该模型访问权限
3. 修改 `.env` 后是否已重启服务

## 本地开发启动

### 1. 创建并激活环境

如果你使用 Conda：

```bash
cd /home/wxr/proj/ai_coding_assistant
eval "$(conda shell.bash hook)"
conda create -n ai_coding python=3.10 -y
conda activate ai_coding
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 准备配置

```bash
cp .env.example .env
```

然后编辑 `.env`，填入你自己的模型服务配置。

### 4. 启动服务

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

启动成功后，可先验证健康状态：

```bash
curl http://127.0.0.1:8000/
```

## 快速调用示例

### 创建任务

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/ \
  -H "Content-Type: application/json" \
  -d '{"requirement":"写一个 Python 脚本，读取 json 文件并输出行数"}'
```

### 查询任务

```bash
curl http://127.0.0.1:8000/api/v1/tasks/<task_id>
```

### 审批任务

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/<task_id>/approve \
  -H "Content-Type: application/json" \
  -d '{"is_approved": true}'
```

## Benchmark 使用方法

先确保服务已经运行，然后在另一个终端执行：

```bash
cd /home/wxr/proj/ai_coding_assistant
eval "$(conda shell.bash hook)"
conda activate ai_coding
python benchmark.py
```

脚本会：

- 提交测试任务
- 轮询等待进入审批状态
- 自动审批
- 轮询直到任务完成或失败
- 输出完成率、中位时长和 Reviewer 检出改进点平均数

你可以根据需要修改 [benchmark.py](/home/wxr/proj/ai_coding_assistant/benchmark.py) 中的：

- `TASK_PROMPTS`
- `TOTAL_ROUNDS`
- `PLANNING_TIMEOUT_SECONDS`
- `FINAL_TIMEOUT_SECONDS`

## 部署建议

### 单机部署

当前版本适合单机、单进程部署。原因是：

- 任务状态使用进程内内存存储
- 后台工作流通过 `asyncio.create_task(...)` 启动
- 多 worker 模式下，各 worker 之间不会共享 `fake_db`

因此部署时建议只启动 1 个 worker：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 使用 systemd 部署

可在 Linux 服务器上创建 `/etc/systemd/system/ai-coding-assistant.service`：

```ini
[Unit]
Description=AI Coding Assistant API
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/ai_coding_assistant
Environment="PYTHONUNBUFFERED=1"
ExecStart=/path/to/miniconda3/envs/ai_coding/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

然后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-coding-assistant
sudo systemctl start ai-coding-assistant
sudo systemctl status ai-coding-assistant
```

### 生产环境注意事项

如果你准备将其升级为正式生产服务，建议优先补齐以下能力：

- 持久化任务存储，替换 `fake_db`
- 将后台工作流迁移到消息队列或任务队列系统
- 为 Agent 调用增加单步超时与取消机制
- 将生成代码真正写入 `WORKSPACE_DIR`
- 增加鉴权、审计日志、限流和监控

## 当前限制

- 任务状态不会持久化
- 服务重启后历史任务会丢失
- 生成结果默认仅保存在 API 返回的 `code_draft`
- Context 只读取文件，不自动提交代码变更
- 大模型响应速度会直接影响整条链路耗时

## 后续演进方向

- 接入数据库保存任务与审批记录
- 接入对象存储保存中间工件
- 增加代码自动落盘与 Git 提交能力
- 支持更细粒度的 Agent 可观测性
- 支持多租户与权限控制
