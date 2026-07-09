# 开发规则

日期：2026-07-10

状态：长期维护

这份文档是给以后所有代码改动用的规则。目标是避免项目变成“每次生成代码都像开盲盒”的状态。

## 1. 总原则

1. 先判断功能归属，再写代码。
2. 核心逻辑不能继续无限堆进 `video_slicer/pipeline.py`。
3. 新增核心模块必须有测试。
4. 改目录结构或模块职责时，必须更新 `docs/code-map.zh-CN.md`。
5. 视频专属事实只能放在 `context.json` 或项目数据里，不能写进通用代码。
6. 外部服务调用必须通过 provider 层，不直接散落在业务流程里。
7. 输出质量问题先进入 `quality_report.json`，观察稳定后再决定是否改成硬失败。
8. `.env`、视频、输出、声音参考、真实声音注册表不能提交。

## 2. 每次改代码前必须先分类

新增或修改功能前，先判断它属于哪一类。

| 功能类型 | 应放位置 |
| --- | --- |
| 文案生成、审稿、润色 | `video_slicer/script_generation.py` |
| 文案和原字幕/画面的匹配 | `video_slicer/alignment.py` |
| FFmpeg 剪辑、合成、混音、字幕烧录 | `video_slicer/rendering.py` |
| 项目、版本、任务字段 | `video_slicer/project_models.py` |
| 本地项目数据读写 | `video_slicer/project_store.py` |
| 旧 CLI 到项目记录的适配 | `video_slicer/pipeline_records.py` |
| 本地 HTTP API、请求 schema、任务调度 | `video_slicer/api/` |
| 大模型服务 | `llm_providers/` |
| TTS 服务 | `tts_providers/` |
| 声音资产本地注册 | `video_slicer/voice_registry.py` |
| 上下文包和前端可编辑字段 | `video_slicer/context_packet.py`、`context.example.json` |
| 质量检查 | `video_slicer/quality_report.py` |
| 命令行入口 | `scripts/` |
| 产品设计和技术计划 | `docs/` |

如果一个新功能不知道该放哪里，先停下来讨论，不直接塞进 `pipeline.py`。

## 3. 什么时候必须更新代码地图

只要出现以下情况，必须同步更新 `docs/code-map.zh-CN.md`：

- 新增核心模块。
- 移动核心函数。
- 新增目录。
- 新增命令行脚本。
- 新增 provider。
- 新增测试文件。
- 改变 pipeline 阶段职责。
- 改变输出文件含义。
- 新增未来前端/后端会依赖的数据结构。

以下情况一般不需要更新代码地图：

- 修复小 bug。
- 调整 prompt 文案。
- 调整默认参数。
- 补充 README 中的使用示例。
- 新增单个测试用例但没有新测试文件。

## 4. `pipeline.py` 的使用边界

`video_slicer/pipeline.py` 当前仍然是主流程，但它应该逐步变薄。

允许暂时留在 `pipeline.py` 的内容：

- CLI 参数解析。
- 主流程编排。
- 旧逻辑迁移前的兼容代码。

不应继续新增到 `pipeline.py` 的内容：

- 新的大模型 provider 细节。
- 新的 TTS provider 细节。
- 新的复杂画面匹配算法。
- 新的复杂 FFmpeg 渲染逻辑。
- 新的数据模型。
- 新的质量检查规则。

如果必须先放进 `pipeline.py`，需要同时记录后续迁移目标，例如迁到 `alignment.py`、`rendering.py` 或 `script_generation.py`。

## 5. 测试规则

新增核心模块必须新增对应测试：

| 模块 | 测试 |
| --- | --- |
| `video_slicer/api/app.py` | `tests/test_api_app.py` |
| `video_slicer/api/project_service.py` | `tests/test_api_projects.py` |
| `video_slicer/api/job_runner.py` | `tests/test_api_jobs.py` |
| `video_slicer/alignment.py` | `tests/test_alignment.py` |
| `video_slicer/rendering.py` | `tests/test_rendering.py` |
| `video_slicer/script_generation.py` | `tests/test_script_generation.py` |
| `video_slicer/quality_report.py` | `tests/test_quality_report.py` |
| `video_slicer/pipeline.py` 的可测试纯逻辑 | `tests/test_pipeline.py` |
| `video_slicer/project_models.py` | `tests/test_project_models.py` |
| `video_slicer/project_store.py` | `tests/test_project_store.py` |

测试原则：

- 纯函数优先写单元测试。
- 网络调用不写成必须联网的单元测试。
- FFmpeg 真实视频处理后续单独做集成测试。
- 每次核心改动至少运行相关测试。
- 如果改了公共模型或 pipeline 入口，运行全部现有单元测试。

当前推荐验证命令：

```powershell
python -m unittest tests.test_api_app tests.test_api_projects tests.test_api_jobs tests.test_script_generation tests.test_rendering tests.test_alignment tests.test_pipeline tests.test_project_models tests.test_project_store tests.test_pipeline_records tests.test_quality_report
python -m compileall video_slicer tests scripts
```

后续新增测试文件后，把它加入验证命令。

## 6. 质量报告规则

所有输出质量风险优先进入 `outputs/quality_report.json`。

适合先进入质量报告的问题：

- 画面时间线倒跳。
- 相邻画面大量重叠。
- 文案和原字幕证据重合度过低。
- source evidence 跨度过长。
- 文案英文残留。
- 时长偏差。
- TTS 和画面时长不一致。
- 转写疑似错词。

规则升级路径：

```text
info / warning
  -> 观察多次输出
  -> 形成修复策略
  -> 必要时升级为 error 或直接拦截
```

不要一开始就把不稳定判断写成硬失败，否则会影响 demo 迭代。

## 7. Context 规则

视频专属信息不能写进通用代码。

应该放进 `context.json` 的内容：

- 作品名。
- 人物名。
- 人物关系。
- 剧情梗概。
- 必须讲到的点。
- 明确不能出现的剧情。
- 该视频特有的禁用词。
- 该视频特有的 TTS 易错表达。

可以放进通用代码或模板的内容：

- 通用影视解说写作规则。
- 通用口播规则。
- 通用禁止角色扮演规则。
- 通用质量检查规则。
- 前端可编辑字段 schema。

换视频时，应该换新的 `context.json`，不要改通用代码。

## 8. Provider 规则

大模型服务统一放在 `llm_providers/`。

TTS 服务统一放在 `tts_providers/`。

Provider 层应该负责：

- API key 读取。
- base URL。
- 请求格式。
- 响应解析。
- 重试和错误提示。

Provider 层不应该负责：

- 文案策略。
- 视频剪辑。
- 项目/版本记录。
- 用户产品逻辑。

## 9. 输出和 Git 规则

不能提交：

- `.env`
- `.venv/`
- `outputs/`
- `projects.local/`
- `videos/*.mp4`
- `assets/voice_refs/*`
- `assets/bgm/*`
- `__pycache__/`

可以提交：

- `.env.example`
- `context.example.json`
- `batch.example.json`
- `assets/bgm/.gitkeep`
- `assets/voice_refs/.gitkeep`
- `videos/.gitkeep`
- 文档、代码、测试。

如果需要让同学复用 demo，不要提交真实 key 和本地输出，而是提交模板和说明。

## 10. 每轮开发收尾清单

每次完成代码改动后，最终总结至少说明：

- 改了哪些文件。
- 属于哪一层。
- 有没有更新代码地图。
- 跑了哪些测试。
- 有没有未解决风险。
- 是否改动运行逻辑。

如果本轮只改文档，也要说明没有改运行逻辑。

## 11. 推荐开发顺序

当前阶段推荐顺序：

1. 保持现有 pipeline 可跑。
2. 质量问题先进入 `quality_report.py`。
3. 拆 `alignment.py`，解决画面匹配。
4. 拆 `rendering.py`，集中管理 FFmpeg。
5. 拆 `script_generation.py`，集中管理文案生成和审稿。
6. 接本地 FastAPI。
7. 再做前端。

不要在画面匹配还不稳定时急着做复杂前端。前端应该接稳定的项目/版本/任务接口，而不是直接包住一个混乱脚本。
