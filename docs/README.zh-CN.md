# 项目目录总览

日期：2026-07-10

这份文档是项目的目录入口。它回答三个问题：

1. 每个顶层目录放什么。
2. 哪些文件可以提交到 GitHub，哪些只能留在本地。
3. 以后新增代码时应该先放到哪里。

更细的函数级代码地图见 `docs/code-map.zh-CN.md`；开发约束见 `docs/development-rules.zh-CN.md`。

## 顶层目录

| 路径 | 作用 | Git 规则 |
| --- | --- | --- |
| `video_slicer/` | 核心业务包：pipeline 编排、上下文包、对齐、渲染、质量报告、项目记录 | 提交 |
| `video_slicer/api/` | 本地 FastAPI 后端：项目、上下文、版本、渲染任务和状态查询 | 提交 |
| `llm_providers/` | 大模型 provider 适配层，例如 DashScope、OCool | 提交 |
| `tts_providers/` | TTS provider 适配层，例如 Fish Audio、OCool | 提交 |
| `scripts/` | 命令行入口和诊断工具 | 提交 |
| `tests/` | 单元测试 | 提交 |
| `docs/` | 目录说明、代码地图、开发规则、产品设计和实施计划 | 提交 |
| `assets/bgm/` | 本地 BGM 音频目录 | 只提交 `.gitkeep` |
| `assets/voice_refs/` | 本地声音参考音频和声音注册表 | 只提交 `.gitkeep` |
| `videos/` | 本地输入视频目录 | 只提交 `.gitkeep` |
| `outputs/` | pipeline 运行产物 | 不提交 |
| `outputs_archive/` | 历史输出归档 | 不提交 |
| `projects.local/` | 本地项目、版本、任务记录 | 不提交 |
| `.venv/` | 本地 Python 虚拟环境 | 不提交 |

## 根目录文件

| 文件 | 作用 | Git 规则 |
| --- | --- | --- |
| `README.md` | 项目使用说明和快速上手入口 | 提交 |
| `1.py` | 兼容旧命令的薄入口，内部调用 `video_slicer.pipeline` | 提交 |
| `requirements.txt` | Python 依赖 | 提交 |
| `.env.example` | 环境变量模板 | 提交 |
| `.env` | 本地真实 API key 和运行配置 | 不提交 |
| `.gitignore` | Git 忽略规则 | 提交 |
| `context.example.json` | 上下文包模板 | 提交 |
| `context.json` | 当前视频的本地事实包和创作配置 | 不提交 |
| `batch.example.json` | 批量任务模板 | 提交 |
| `batch.local.json` | 本地批量任务清单 | 不提交 |

## 核心代码归属

| 功能 | 放置位置 |
| --- | --- |
| 主流程编排、CLI 参数兼容 | `video_slicer/pipeline.py` |
| 文案和原字幕/画面的时间戳对齐 | `video_slicer/alignment.py` |
| FFmpeg 剪辑、合成、混音、字幕烧录、媒体时长探测 | `video_slicer/rendering.py` |
| 配音文案生成、语义审稿、真人口播润色、文案校验 | `video_slicer/script_generation.py` |
| 上下文包加载、规范化、前端可编辑字段 schema | `video_slicer/context_packet.py` |
| 质量报告生成 | `video_slicer/quality_report.py` |
| 项目、版本、任务数据模型 | `video_slicer/project_models.py` |
| 本地项目数据读写 | `video_slicer/project_store.py` |
| CLI 参数到项目记录的过渡适配 | `video_slicer/pipeline_records.py` |
| 本地 API 路由、请求 schema、后台渲染任务调度 | `video_slicer/api/` |
| 本地声音 ID 注册表 | `video_slicer/voice_registry.py` |
| 大模型 API 请求细节 | `llm_providers/` |
| TTS API 请求和声音克隆细节 | `tts_providers/` |
| 新命令行入口 | `scripts/` |

## 文档归属

| 文档 | 作用 |
| --- | --- |
| `docs/README.zh-CN.md` | 目录总览和提交边界 |
| `docs/code-map.zh-CN.md` | 函数级代码地图和后续拆分方向 |
| `docs/development-rules.zh-CN.md` | 每次开发必须遵守的放置、测试、Git 规则 |
| `docs/superpowers/specs/` | 产品设计文档 |
| `docs/superpowers/plans/` | 分阶段实施计划 |

## 新增文件放置规则

新增代码前先判断它属于哪一层：

- 新的剪辑、混音、字幕烧录、编码参数：放到 `video_slicer/rendering.py`。
- 新的画面匹配、字幕证据、时间戳选择策略：放到 `video_slicer/alignment.py`。
- 新的文案策略、审稿规则、口播润色限制、禁用词校验：放到 `video_slicer/script_generation.py`。
- 新的质量指标或风险提示：放到 `video_slicer/quality_report.py`。
- 新的本地 HTTP 接口、请求/响应 schema、后台任务调度：放到 `video_slicer/api/`。
- 新的大模型服务：新增到 `llm_providers/`。
- 新的 TTS 服务：新增到 `tts_providers/`。
- 新的用户可配置参数：优先放到 `VersionSettings`，再由 CLI 或未来前端传入。
- 新的视频专属事实、剧情、人物、禁用词：只放到 `context.json` 或项目数据，不写进通用代码。
- 新的命令行入口：放到 `scripts/`，复杂逻辑仍然回到 `video_slicer/`。

## 提交前检查

提交前至少确认：

```powershell
git status --short
git ls-files outputs videos .env assets\voice_refs assets\bgm
```

第二个命令正常只应该看到：

```text
assets/bgm/.gitkeep
assets/voice_refs/.gitkeep
videos/.gitkeep
```

如果看到 `.env`、真实视频、真实音频、`outputs/` 里的文件，先不要提交。
