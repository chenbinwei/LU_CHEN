# 代码地图

日期：2026-07-10

状态：随代码演进维护

这份文档用于回答两个问题：

1. 当前仓库每个目录和文件负责什么。
2. 以后功能变复杂后，代码应该放在哪里，避免所有逻辑继续堆进一个大脚本。

## 1. 快速结论

当前项目已经从单文件 demo 进入“产品内核雏形”阶段。

现在的核心结构是：

```text
命令行入口
  -> video_slicer.pipeline
    -> 转写 / TTS / 剪辑 / 混音 / 报告
  -> video_slicer.script_generation
    -> 文案 / 审稿 / 润色 / 校验 / 脚本输出
  -> video_slicer.alignment
    -> 文案和原字幕/画面对齐

项目化记录
  -> video_slicer.project_models
  -> video_slicer.project_store
  -> video_slicer.pipeline_records

本地 HTTP API
  -> video_slicer.api
    -> 项目 / 上下文 / 版本 / 渲染任务 / 状态查询

外部服务
  -> llm_providers
  -> tts_providers

质量基线
  -> video_slicer.quality_report
```

目前还没有真正的前端；本地 FastAPI 后端已进入 MVP 阶段。`video_slicer.pipeline` 仍然偏大，但 alignment、rendering、script_generation 已经拆出，后续重构重点应该是继续逐步拆成可复用阶段，而不是一次性推翻。

相关文档：

- `docs/README.zh-CN.md`：目录总览和提交边界。
- `docs/development-rules.zh-CN.md`：后续开发必须遵守的规则。
- `docs/superpowers/specs/2026-07-09-video-slicing-product-design.zh-CN.md`：产品设计文档。
- `docs/superpowers/plans/2026-07-10-alignment-module-refactor.md`：下一步 alignment 拆分计划。

## 2. 顶层目录

| 路径 | 作用 | 是否应该提交 |
| --- | --- | --- |
| `1.py` | 兼容旧入口，最终调用 `video_slicer.pipeline` | 是 |
| `video_slicer/` | 项目核心 Python 包 | 是 |
| `video_slicer/api/` | 本地 FastAPI 后端：项目、上下文、版本、渲染任务和状态查询 | 是 |
| `llm_providers/` | 大模型 provider 适配层 | 是 |
| `tts_providers/` | TTS provider 适配层 | 是 |
| `scripts/` | 命令行工具入口 | 是 |
| `tests/` | 单元测试 | 是 |
| `docs/` | 产品设计、代码地图、实施计划 | 是 |
| `assets/bgm/` | 本地 BGM 目录，只提交 `.gitkeep` | 只提交 `.gitkeep` |
| `assets/voice_refs/` | 本地声音参考和声音注册表，只提交 `.gitkeep` | 只提交 `.gitkeep` |
| `videos/` | 本地输入视频目录，只提交 `.gitkeep` | 只提交 `.gitkeep` |
| `outputs/` | 运行产物 | 否 |
| `projects.local/` | 本地项目/版本/任务记录 | 否 |
| `.env` | 本地密钥 | 否 |
| `.env.example` | 环境变量模板 | 是 |
| `context.example.json` | 上下文包模板 | 是 |
| `batch.example.json` | 批量任务模板 | 是 |

## 3. 运行入口

### 旧入口

- `1.py`
  - 作用：保持旧命令可用。
  - 后续策略：不要继续往这里加业务逻辑，只保留薄入口。

### 推荐入口

- `scripts/run_pipeline.py`
  - 作用：运行完整 pipeline。
  - 后续策略：可以继续作为本地 CLI 的主要入口。

### 核心入口

- `video_slicer/pipeline.py::main()`
- `video_slicer/pipeline.py::build_parser()`
- `video_slicer/pipeline.py::run_cli()`

其中 `run_cli()` 是当前完整流程编排入口。它现在仍然承担太多职责，后续应该逐步拆分。

## 4. 当前 Pipeline 阶段

当前主流程仍由 `video_slicer/pipeline.py` 编排，其中 alignment 相关逻辑已经拆到 `video_slicer/alignment.py`。

| 阶段 | 主要函数 | 当前职责 |
| --- | --- | --- |
| 环境和命令执行 | `video_slicer.rendering::ensure_ffmpeg()`、`run()`、`run_capture()` | 检查 FFmpeg，执行外部命令 |
| 媒体时长 | `video_slicer.rendering::ffprobe_duration_media()`、`ffprobe_duration()` | 读取视频/音频真实时长 |
| 音频提取 | `extract_audio()` | 从视频中提取 `audio.wav` |
| 语音转写 | `transcribe_audio()` | 使用 faster-whisper 转写字幕 |
| 字幕工具 | `video_slicer.script_generation::write_srt()`、`seconds_to_srt_time()` | 写 SRT |
| 文案生成 | `video_slicer.script_generation::generate_voiceover_with_llm()` | 调用 LLM 生成解说脚本 |
| 语义审稿 | `video_slicer.script_generation::review_voiceover_with_llm()` | 调用 LLM 做语义和口播审查 |
| 真人口播润色 | `video_slicer.script_generation::humanize_voiceover_with_llm()` | 调用 LLM 做口播润色 |
| 文案校验 | `video_slicer.script_generation::validate_voiceover_doc()` | 检查禁用词、英文残留、结构等 |
| TTS 生成 | `prepare_sentence_audio()` | 逐句生成配音 |
| TTS 时间线 | `video_slicer.alignment::refresh_voiceover_timeline()` | 根据真实音频刷新时间线 |
| 时长贴合 | `fit_alignment_audio_to_target_duration()` | 用 `atempo` 调整 TTS 总时长 |
| 对齐 | `video_slicer.alignment::align_voiceover_to_transcript()` | 把文案句子映射到原字幕片段 |
| 画面选择 | `video_slicer.alignment::build_clips_from_alignment()` | 根据对齐结果生成剪辑片段 |
| 静音剪辑 | `video_slicer.rendering::clip_video_silent()` | 生成无原声预览 |
| 配音成片 | `video_slicer.rendering::render_clips_with_voiceover()` | 用新配音合成视频 |
| BGM 混音 | `video_slicer.rendering::add_background_music()` | 混入背景音乐 |
| 输出记录 | `video_slicer.script_generation::write_voiceover_outputs()`、`video_slicer.rendering::write_visual_time_mapping()` | 写脚本、字幕、映射 |
| 时长校验 | `video_slicer.rendering::validate_final_duration()` | 校验最终视频时长 |

### 当前风险

`pipeline.py` 已经超过两千行，后续不要继续把新能力直接塞进去。

已完成：

- `alignment` 相关逻辑已拆到 `video_slicer/alignment.py`。
- `rendering` 相关逻辑已拆到 `video_slicer/rendering.py`。
- `script_generation` 相关逻辑已拆到 `video_slicer/script_generation.py`。

优先拆分方向：

1. 主流程只保留编排逻辑。
2. 新增领域能力先拆到独立模块，再由 pipeline 编排调用。

### 已拆出的 Alignment 模块

`video_slicer/alignment.py` 负责文案和原视频画面的对齐。

核心函数：

- `estimate_voiceover_duration()`
- `apply_estimated_voiceover_timeline()`
- `refresh_voiceover_timeline()`
- `limit_alignment_to_target_duration()`
- `simple_text_score()`
- `score_source_evidence()`
- `evidence_warning_for_score()`
- `find_best_ordered_match()`
- `minimum_timeline_span_for_durations()`
- `latest_start_bounds_for_durations()`
- `choose_visual_window_for_row()`
- `align_voiceover_to_transcript()`
- `build_clips_from_alignment()`

对应测试：

- `tests/test_alignment.py`

后续质量修复仍然优先在这个模块里做，不再把对齐算法塞回 `pipeline.py`。

当前已完成的质量修复：

- 大模型提供 `source_segment_ids` 时，不再无条件给 `match_score=1.0`。
- alignment row 会写入 `source_id_trust`，区分 `llm_provided`、`fallback_matched`、`llm_replaced_by_ordered_fallback` 和 `continuity_visual_support`。
- alignment row 和最终 clip 都会写入 `source_order_policy=monotonic`，MVP 不做 hook/高能片段倒跳，画面来源按原视频时序推进。
- 低证据分会写入 `evidence_warning=low_text_evidence_overlap`；如果 LLM ids 因倒跳被替换，或因低证据且找到更强 ordered fallback 被替换，会保留 `original_source_segment_ids`。
- 如果 LLM ids 低证据，但 ordered fallback 也没有达到证据阈值，alignment 会保留原始位置作为 `continuity_visual_support`，表示这里只用于顺序画面支撑，不再当作可信字幕语义证据。
- `choose_visual_window_for_row()` 会先处理单句画面窗口：短 source span 仍然居中取画面；长 source span 会根据 `story_role` 靠前或靠后取画面，避免几秒配音从几十秒证据范围中间误取。
- `build_clips_from_alignment()` 会先根据所有配音句子的真实时长，从后往前计算每个 clip 的最晚开始时间；如果证据点过晚，会适当前移当前 clip，为后续句子留出画面空间；如果相邻片段重叠过多，会在有足够视频空间时平移后续 clip，并写入 `visual_selection_reason`。

### 已拆出的 Rendering 模块

`video_slicer/rendering.py` 负责 FFmpeg/ffprobe 相关媒体处理。

核心函数：

- `run()`
- `run_capture()`
- `ensure_ffmpeg()`
- `ffprobe_duration_media()`
- `ffprobe_duration()`
- `burn_subtitles()`
- `clip_video_silent()`
- `render_clips_with_voiceover()`
- `write_visual_time_mapping()`
- `mux_voiceover_audio()`
- `validate_final_duration()`
- `add_background_music()`

对应测试：

- `tests/test_rendering.py`

后续规则：

- 新增剪辑、混音、字幕烧录、封装容器、编码参数相关能力，优先放到 `video_slicer/rendering.py`。
- `pipeline.py` 只负责决定何时调用渲染函数，不直接拼 FFmpeg 命令。
- 单元测试通过 mock 验证命令构造，真实 FFmpeg 行为放到低成本集成验证中检查。

### 已拆出的 Script Generation 模块

`video_slicer/script_generation.py` 负责配音文案相关逻辑。

核心函数：

- `voiceover_length_requirements()`
- `parse_json_response()`
- `parse_llm_json_response()`
- `forbidden_terms_from_context()`
- `validate_voiceover_doc()`
- `generate_voiceover_with_llm()`
- `review_voiceover_with_llm()`
- `humanize_voiceover_with_llm()`
- `write_humanize_diff()`
- `fallback_voiceover_script()`
- `write_voiceover_outputs()`

对应测试：

- `tests/test_script_generation.py`

后续规则：

- 新增文案策略、审稿规则、口播润色限制、禁用词校验，优先放到 `video_slicer/script_generation.py`。
- `pipeline.py` 只负责决定何时生成、审稿、润色和写出脚本，不直接拼大段 prompt。
- 第三方模型请求细节仍然放在 `llm_providers/`。

## 5. 本地 API 模块

### `video_slicer/api/app.py`

职责：

- 创建 FastAPI app。
- 暴露健康检查、上下文 schema、项目、版本、渲染任务和任务状态接口。
- 通过依赖注入支持单元测试传入临时 `LocalProjectStore` 和 fake runner。

### `video_slicer/api/schemas.py`

职责：

- 定义 API 请求体。
- 保持前端字段名和 `VersionSettings`、context packet 字段一致。

### `video_slicer/api/project_service.py`

职责：

- 复用 `LocalProjectStore` 创建项目和版本。
- 保存完整 `context_packet`。
- 为 pipeline 渲染写出项目级 `context.json`。

### `video_slicer/api/job_runner.py`

职责：

- 创建和运行后台渲染任务。
- 把 API version settings 映射成 `pipeline.run_cli()` 所需参数。
- 限制本地同一时间只跑一个渲染任务。

对应测试：

- `tests/test_api_app.py`
- `tests/test_api_projects.py`
- `tests/test_api_jobs.py`

后续规则：

- API 层不能重写剪辑、对齐、文案生成、TTS 或 FFmpeg 逻辑。
- API 层只做请求校验、状态记录和调度。
- 如果前端需要新配置，先加到 `VersionSettings` 或 context packet，再由 API 暴露。

## 6. 项目/版本/任务模型

这些模块是以后接前端和商业化的基础。

### `video_slicer/project_models.py`

核心对象：

- `ProjectRecord`
- `VersionRecord`
- `JobRecord`
- `UserContext`
- `VersionSettings`

核心枚举：

- `AudioMode`
- `SubtitleLanguage`
- `AspectRatio`
- `JobStatus`
- `JobStage`

核心函数：

- `validate_version_settings()`

职责：

- 定义“项目、版本、任务”的数据结构。
- 定义前端/后端都要认识的枚举。
- 校验目标时长、音量、语速等基础参数。

后续规则：

- 新增用户可配置参数时，优先加到 `VersionSettings`。
- 新增项目级信息时，优先加到 `ProjectRecord` 或 `UserContext`。
- 不要在 `pipeline.py` 里散落新的产品字段。

### `video_slicer/project_store.py`

核心对象：

- `LocalProjectStore`

职责：

- 本地 JSON 存储。
- 创建/读取/保存项目、版本、任务。
- 记录导出文件和任务状态。

后续规则：

- 本地单人模式继续用它。
- 未来 FastAPI 可以先调用它，后面再替换成数据库。
- 不要让前端直接理解 `outputs/` 里的散乱文件。

### `video_slicer/pipeline_records.py`

核心对象：

- `PipelineRecordSession`

核心函数：

- `settings_from_pipeline_args()`
- `begin_pipeline_record_session()`

职责：

- 把旧 CLI 参数映射成 `VersionSettings`。
- 让现有 pipeline 可选写入 project/version/job 记录。

后续规则：

- 它是过渡适配层，不应该承载复杂业务。
- 等 pipeline 真正项目化后，这个模块可以变薄或被替换。

## 7. 上下文包

### `video_slicer/context_packet.py`

核心函数：

- `load_context_packet()`
- `normalize_context_packet()`
- `compact_context_for_prompt()`
- `narration_rules_for_prompt()`
- `frontend_context_schema()`

职责：

- 读取 `context.json`。
- 把用户补充信息和系统叙事规则变成 prompt 可用结构。
- 提供未来前端可编辑字段 schema。

后续规则：

- 某个视频的人名、剧情、禁用词不能写进通用代码。
- 视频专属信息放到 `context.json`。
- 公共叙事规则可以在 `context.example.json` 和 `context_packet.py` 中维护。

## 8. 大模型 Provider

### `llm_providers/dashscope.py`

核心函数：

- `text_completion()`

职责：

- 使用 DashScope 官方 SDK 调 Qwen。
- 支持 thinking、stream、重试、超时、温度等参数。

### `llm_providers/ocool.py`

核心函数：

- `text_completion()`

职责：

- OpenAI-compatible 文本接口备用适配。

后续规则：

- 新增模型服务时，只在 `llm_providers/` 新增 provider。
- `pipeline.py` 不应该直接写第三方 API 请求细节。
- Provider 输出应该尽量统一为纯文本，由 pipeline 或脚本解析 JSON。

## 9. TTS Provider

### `tts_providers/fish.py`

核心函数：

- `synthesize_batch()`
- `create_voice_model()`

职责：

- Fish Audio TTS。
- Fish 声音克隆模型创建。

### `tts_providers/ocool.py`

核心函数：

- `synthesize_batch()`

职责：

- OpenAI-compatible TTS fallback。

后续规则：

- 新增 TTS 服务时，只在 `tts_providers/` 下新增 provider。
- 每个 provider 对外尽量暴露统一的 `synthesize_batch()`。
- 声音克隆资产不要写死在代码中，使用 `.env` 或 `voice_registry`。

## 10. 声音注册表

### `video_slicer/voice_registry.py`

核心函数：

- `load_registry()`
- `save_registry()`
- `list_voices()`
- `find_voice()`
- `upsert_voice()`

职责：

- 本地管理 Fish 声音模型 ID。
- 让用户可以用名字找到 voice/reference id。

后续规则：

- 商业版中它会演进成声音资产表。
- 本地注册表文件不要提交。

## 11. 质量报告

### `video_slicer/quality_report.py`

核心函数：

- `build_quality_report()`
- `write_quality_report()`
- `text_similarity()`

职责：

- 生成 `outputs/quality_report.json`。
- 检查成片风险，但目前不阻止生成。

当前检查项：

- 最终时长偏差。
- 配音和画面总时长不一致。
- 文案英文残留。
- 大模型指定字幕 id 但证据分过低。
- 大模型指定字幕 id 被顺序 fallback 修正。
- 低证据字幕 id 被降级为连续画面支撑。
- source evidence 跨度过长。
- 画面时间线倒跳。
- 相邻画面大重叠。
- 文案和原字幕文本重合度过低。
- 指标中包含 `source_major_overlap_count`、`source_major_overlap_max`、`continuity_visual_support_count`，便于批量观察画面复用和低证据画面支撑程度。

后续规则：

- 新增质量问题时，先作为 warning/info 进入质量报告。
- 观察几轮后，再决定是否升级成硬失败。
- 不要把质量判断散落在 `pipeline.py` 各处。

## 12. Scripts 目录

| 文件 | 作用 |
| --- | --- |
| `scripts/run_pipeline.py` | 完整 pipeline 入口 |
| `scripts/run_batch.py` | 按 JSON 清单批量跑多个任务 |
| `scripts/run_api.py` | 启动本地 FastAPI 后端 |
| `scripts/preview_tts.py` | 只试听 TTS |
| `scripts/create_fish_voice.py` | 创建 Fish 声音模型 |
| `scripts/mix_bgm.py` | 对已有成片单独混 BGM |
| `scripts/context_schema.py` | 导出前端上下文 schema |
| `scripts/check_dashscope.py` | 检查 DashScope 文本生成 |
| `scripts/check_ocool.py` | 检查 OCool 兼容接口 |
| `scripts/diagnose_ocool.py` | 诊断 OCool 请求问题 |

后续规则：

- `scripts/` 只做命令行入口和参数解析。
- 复杂逻辑放回 `video_slicer/`。
- 脚本不要互相调用脚本，应该调用同一个核心模块。

## 13. Tests 目录

| 文件 | 覆盖模块 |
| --- | --- |
| `tests/test_api_app.py` | `video_slicer.api.app` |
| `tests/test_api_projects.py` | `video_slicer.api.project_service` 和项目/版本 API |
| `tests/test_api_jobs.py` | `video_slicer.api.job_runner` 和渲染任务 API |
| `tests/test_alignment.py` | `video_slicer.alignment` |
| `tests/test_rendering.py` | `video_slicer.rendering` |
| `tests/test_pipeline.py` | `video_slicer.pipeline` 中仍未拆出的可测试纯逻辑 |
| `tests/test_project_models.py` | `video_slicer.project_models` |
| `tests/test_project_store.py` | `video_slicer.project_store` |
| `tests/test_pipeline_records.py` | `video_slicer.pipeline_records` 和 CLI 参数 |
| `tests/test_quality_report.py` | `video_slicer.quality_report` |

后续规则：

- 新增核心模块必须新增对应测试。
- Provider 网络调用不要直接写成必须联网的单元测试。
- FFmpeg 真实成片测试可以后面单独放到集成测试。

## 14. 输出文件关系

一次 pipeline 运行主要输出：

| 文件 | 含义 |
| --- | --- |
| `audio.wav` | 从原视频提取的音频 |
| `transcript.json` | faster-whisper 转写结果 |
| `raw_subtitles.srt` | 原视频转写字幕 |
| `voiceover_script.json` | 最终配音文案和对齐信息 |
| `voiceover_script.txt` | 可读文案 |
| `voiceover_humanize_diff.txt` | 润色前后对比 |
| `alignment.json` | 文案句子到原字幕/原视频的映射 |
| `selected_clips.json` | 最终选择的画面片段 |
| `quality_report.json` | 质量报告 |
| `time_mapping.json` | 新视频时间到原视频时间映射 |
| `voiceover.srt` | 新配音字幕 |
| `output.mp4` | 无原声剪辑预览 |
| `final_with_voiceover.mp4` | 新配音成片 |
| `final_with_bgm.mp4` | 新配音加 BGM 成片 |

后续规则：

- 前端不应该直接依赖所有中间文件。
- 前端优先读取项目/版本/任务记录。
- 中间文件可以作为调试和复跑缓存。

## 15. 后续重构顺序建议

不要一次性重写。建议按下面顺序拆：

### 第一阶段：继续加质量基线

目标：知道输出哪里不稳定。

可做：

- 把 `quality_report.json` 写入项目版本记录。
- 对 `source_timeline_backtrack` 和 `source_evidence_span_too_long` 做修复策略。
- 增加转写错词风险提示。

### 第二阶段：完善 Alignment

状态：第一阶段拆分已完成。

已有：

- `video_slicer/alignment.py`
- `tests/test_alignment.py`

已迁移函数：

- `estimate_voiceover_duration()`
- `apply_estimated_voiceover_timeline()`
- `refresh_voiceover_timeline()`
- `limit_alignment_to_target_duration()`
- `simple_text_score()`
- `score_source_evidence()`
- `evidence_warning_for_score()`
- `find_best_ordered_match()`
- `minimum_timeline_span_for_durations()`
- `latest_start_bounds_for_durations()`
- `choose_visual_window_for_row()`
- `align_voiceover_to_transcript()`
- `build_clips_from_alignment()`

下一步目标：

- 对 `source_segment_ids` 做二次校验。已完成基础版：倒跳的 LLM ids 会被 ordered fallback 替换；低证据 LLM ids 只有在找到更强证据时才替换，否则降级为 `continuity_visual_support`。
- 减少画面时间线倒跳。已完成基础版：alignment 层和最终 clip 层强制 `source_order_policy=monotonic`。
- 减少相邻片段大量重叠。已完成基础版：clip 层做从后往前的最晚开始时间排程，在保留时长的前提下尽量让相邻重叠不超过 2 秒，并避免结尾片段被压短。
- 处理 source evidence 跨度过长。已完成基础版：短跨度居中；长跨度按 `story_role` 靠前或靠后取画面。
- 区分剧情推进句和评论收束句。

### 第三阶段：拆 Rendering

状态：已完成。

目标：让 FFmpeg 逻辑集中管理。

已新增：

- `video_slicer/rendering.py`
- `tests/test_rendering.py`

已迁移函数：

- `run()`
- `run_capture()`
- `ensure_ffmpeg()`
- `ffprobe_duration_media()`
- `ffprobe_duration()`
- `clip_video_silent()`
- `render_clips_with_voiceover()`
- `add_background_music()`
- `burn_subtitles()`
- `mux_voiceover_audio()`
- `write_visual_time_mapping()`
- `validate_final_duration()`

### 第四阶段：拆 Script Generation

状态：已完成。

已新增：

- `video_slicer/script_generation.py`
- `tests/test_script_generation.py`

已迁移函数：

- `voiceover_length_requirements()`
- `parse_json_response()`
- `parse_llm_json_response()`
- `forbidden_terms_from_context()`
- `fallback_voiceover_script()`
- `generate_voiceover_with_llm()`
- `review_voiceover_with_llm()`
- `humanize_voiceover_with_llm()`
- `validate_voiceover_doc()`
- `write_humanize_diff()`
- `write_voiceover_outputs()`

### 第五阶段：接本地 API

目标：让未来前端调用稳定接口。

建议新增：

- `api/` 或 `video_slicer/api/`
- FastAPI app

先做：

- 新建项目。
- 创建版本。
- 生成文案。
- 保存编辑后文案。
- 渲染成片。
- 查询任务状态。

## 16. 新功能放置规则

以后新增功能时，优先按这个表判断放哪里：

| 新功能 | 应该放哪里 |
| --- | --- |
| 新模型服务 | `llm_providers/` |
| 新 TTS 服务 | `tts_providers/` |
| 新用户参数 | `VersionSettings` |
| 新项目级补充信息 | `UserContext` 或 `ProjectRecord` |
| 新质量检查 | `quality_report.py` |
| 新命令行入口 | `scripts/` |
| 新剪辑/混音能力 | `video_slicer/rendering.py` |
| 新本地 HTTP API / schema / 任务调度 | `video_slicer/api/` |
| 新文案策略 | `video_slicer/script_generation.py`；视频专属事实仍放 `context.json` 或项目数据 |
| 前端可编辑字段 | `frontend_context_schema()` 或未来 API schema |

## 17. 当前最重要的管理原则

1. 不把某个视频的人名、剧情、禁用词写进通用代码。
2. 不把第三方 API 请求细节写进 pipeline 主流程。
3. 不让 `pipeline.py` 继续无限变大。
4. 新增核心模块时必须配测试。
5. 输出质量问题先进入 `quality_report.json`，再决定是否修复或拦截。
6. 本地视频、输出、密钥、声音参考不进 Git。
7. 先保证本地 CLI 稳，再接前端。
