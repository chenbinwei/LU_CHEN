# 自动影视解说切片 Demo

这个仓库是一个“配音文案优先”的视频自动切片 demo。流程会先从原视频提取语音字幕，再用大模型结合人工上下文包生成影视解说文案，经过语义审查后生成 TTS 配音，最后按配音文案对应的原视频字幕时间戳剪辑画面，并移除原视频声音。

当前 demo 使用同一套已验证参数：

- 默认输入视频：`videos/input.mp4`
- 上下文模板：`context.example.json`
- 文本模型：`qwen-plus-latest`
- 真人口播润色模型：`qwen-plus-latest`
- 文本接口：DashScope 官方 SDK
- TTS provider：`fish`
- Fish TTS 模型：`s2.1-pro-free`
- Fish 声音模型：通过 `.env` 里的 `FISH_REFERENCE_ID` 指定
- 目标时长：约 `120` 秒

## 项目结构

现在项目已经按“以后能接前端/后端”的方向整理：

目录总览见：`docs/README.zh-CN.md`。

更完整的函数级代码引用见：`docs/code-map.zh-CN.md`。

后续开发规则见：`docs/development-rules.zh-CN.md`。新增模块、移动函数、改目录职责时，需要同步维护目录总览和代码地图，避免代码结构失控。

- `1.py`：兼容旧命令的薄入口，内部转到 `video_slicer.pipeline`
- `video_slicer/pipeline.py`：完整视频切片主流程
- `video_slicer/alignment.py`：文案句子、原字幕时间戳和最终画面片段的对齐逻辑
- `video_slicer/rendering.py`：FFmpeg 剪辑、配音合成、BGM 混音、字幕烧录和媒体时长探测
- `video_slicer/script_generation.py`：配音文案生成、语义审稿、真人口播润色、文案校验和脚本文本输出
- `video_slicer/context_packet.py`：上下文包加载、默认叙事规则和前端字段 schema
- `video_slicer/voice_registry.py`：本地 Fish 声音 ID 注册表工具
- `tts_providers/`：TTS provider，当前有 Fish Audio 和 OCool fallback
- `scripts/run_pipeline.py`：完整流程入口
- `scripts/run_api.py`：本地 FastAPI 后端入口，供未来前端调用
- `scripts/preview_tts.py`：单独试听 TTS，不跑完整视频
- `scripts/check_dashscope.py`：检查 DashScope 官方 SDK 是否能正常生成文本
- `scripts/create_fish_voice.py`：创建 Fish 声音模型并登记到本地注册表
- `scripts/context_schema.py`：导出未来前端可编辑的上下文包 schema
- `scripts/run_batch.py`：按 JSON 清单批量跑多个视频
- `batch.example.json`：批量任务模板

## 应该上传到 GitHub 的文件

建议提交这些文件，方便同学直接复用：

- `1.py`：兼容旧命令的入口
- `video_slicer/`：后端核心流程模块
- `tts_providers/`：TTS provider
- `scripts/`：可复用命令行入口
- `requirements.txt`：Python 依赖
- `README.md`：使用说明
- `.gitignore`：忽略本地密钥、输出和缓存
- `.env.example`：环境变量模板，不包含真实 key
- `context.example.json`：通用上下文包模板
- `batch.example.json`：批量任务模板
- `videos/.gitkeep`：保留空的视频目录
- `assets/voice_refs/.gitkeep`：保留声音参考目录
- `assets/bgm/.gitkeep`：保留背景音乐目录

不要提交这些文件：

- `.env`：里面有你的 API key
- `.venv/`：本地虚拟环境
- `outputs/`：运行输出，别人可以自己生成
- `outputs_archive/`：历史输出归档
- `context.json`：本地实际上下文包，可以由模板复制出来
- `videos/*.mp4`：本地输入视频，别人可以换成自己的视频
- `assets/voice_refs/*`：本地参考音频和声音 ID 注册表
- `__pycache__/`：Python 缓存

## 环境准备

先安装 FFmpeg，并确保命令行能识别：

```powershell
ffmpeg -version
ffprobe -version
```

然后创建 Python 虚拟环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 配置 API Key

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

打开 `.env`，先填 DashScope key。这个 key 用于文案生成、语义审稿和真人口播润色：

```env
DASHSCOPE_API_KEY=put_your_dashscope_api_key_here
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/api/v1
DASHSCOPE_MODEL=qwen-plus-latest
DASHSCOPE_HUMANIZE_MODEL=qwen-plus-latest
DASHSCOPE_ENABLE_THINKING=false
DASHSCOPE_MAX_TOKENS=7000
DASHSCOPE_REPAIR_MAX_TOKENS=8000
DASHSCOPE_RETRIES=2
DASHSCOPE_TIMEOUT=90
DURATION_TOLERANCE=3.0
```

如果要使用 Fish Audio 配音和声音克隆，再填：

```env
FISH_API_KEY=put_your_fish_audio_key_here
FISH_TTS_MODEL=s2.1-pro-free
FISH_REFERENCE_ID=
```

`s2.1-pro-free` 是 Fish Audio 的免费开发/测试模型。它适合 demo 和原型验证，但没有延迟和可用性保证。`FISH_REFERENCE_ID` 先留空。创建声音模型后，把 Fish 返回的 `_id` 填进去。

如果想给最终成片垫一层背景音乐，可以额外填：

```env
BGM_AUDIO=assets/bgm/your_bgm.mp3
BGM_VOLUME=0.25
VOICEOVER_VOLUME=1.0
BGM_START=0
BGM_FADE_IN=0
BGM_FADE_OUT=2.5
```

BGM 是可选后处理层。不开时只生成 `final_with_voiceover.mp4`；开启后会额外生成 `final_with_bgm.mp4`，原始配音成片仍然保留。混音时会自动循环并裁剪 BGM 到最终视频长度，支持从音乐中间开始取，并在片头片尾做淡入淡出。

## 目标时长控制

`--target-duration` 不是只给大模型看的建议值，而且必须小于原视频时长。流程会先生成真实 TTS 配音，读取每句真实音频时长；如果总时长和目标差距超过 `DURATION_TOLERANCE`，程序会自动对配音做时间拉伸或压缩，再用调整后的真实配音时长重新剪辑画面。

默认容忍范围是 3 秒：

```env
DURATION_TOLERANCE=3.0
```

例如目标是 120 秒，而 Fish Audio 原始配音只有 75 秒，程序会把配音整体放慢，并重新生成约 120 秒的视频。剪辑前会先校验配音时间线和画面时间线是否都贴近目标；最终写出 `final_with_voiceover.mp4` 和 `final_with_bgm.mp4` 后，还会用 `ffprobe` 校验真实成片时长。如果超出容忍范围会直接失败，而不是静默产出一个明显不对的成片。

调试原始 TTS 速度时可以加：

```powershell
--no-fit-duration
```

`.env` 已经被 `.gitignore` 忽略，不要手动把它加进 Git。

## 配置上下文包

复制 demo 上下文模板：

```powershell
Copy-Item context.example.json context.json
```

`context.json` 是本地运行时读取的上下文包。你可以在里面改视频标题、人物关系、剧情梗概、禁用词和解说风格。

这个文件是每个视频项目自己的“事实包/创作配置”，不是公共代码。换视频时应该换一份新的 `context.json`，不要把某个视频的人名、剧情或禁用词写进 `video_slicer/` 里的通用代码。

其中这几个字段和复用关系最大：

- `characters`：片段里的人物、身份、关系和动机。
- `correct_synopsis`：这个视频真实发生了什么，是防止模型乱补剧情的主依据。
- `story_focus`：切片必须讲清楚的重点。
- `narration_rules`：叙事视角和口播边界，例如第三人称解说、禁止角色扮演、禁止连续复述台词。
- `forbidden_terms`：不允许出现在文案里的词。
- `forbidden_story_facts`：不允许模型写错的剧情方向。
- `humanize_unsafe_detail_terms`：某个视频里容易被模型脑补、但没有证据的画面细节。
- `tts_unfriendly_terms`：TTS 容易读错或听起来别扭的表达。

未来做前端时，可以先用这个命令导出可编辑字段 schema：

```powershell
.\.venv\Scripts\python.exe -m scripts.context_schema --output outputs/context_schema.json
```

## 放入视频

把要处理的视频放到 `videos/` 目录。最简单的方式是命名成默认输入：

```powershell
Copy-Item 你的视频.mp4 videos/input.mp4
```

## 运行 demo

使用 Fish Audio 配音运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.run_pipeline `
  --input videos/input.mp4 `
  --context context.json `
  --target-duration 120 `
  --dashscope-model qwen-plus-latest `
  --dashscope-humanize-model qwen-plus-latest `
  --require-llm `
  --tts-mode fish
```

如果要混入背景音乐，在 `.env` 填 `BGM_AUDIO`，或者运行时加：

```powershell
--bgm-audio assets/bgm/your_bgm.mp3 --bgm-volume 0.16 --voiceover-volume 1.0 --bgm-start 0 --bgm-fade-in 0.8 --bgm-fade-out 2.5
```

如果已经有 `final_with_voiceover.mp4`，只想反复试听 BGM 起点和音量，不需要重新跑完整流程：

```powershell
.\.venv\Scripts\python.exe -m scripts.mix_bgm `
  --input outputs/final_with_voiceover.mp4 `
  --output outputs/final_with_bgm.mp4 `
  --bgm-audio assets/bgm/your_bgm.mp3 `
  --bgm-volume 0.16 `
  --bgm-start 0
```

旧入口仍然可用：

```powershell
.\.venv\Scripts\python.exe 1.py --input videos/input.mp4 --context context.json --target-duration 120 --tts-mode fish
```

如果想强制重新生成脚本、审稿和配音，可以加：

```powershell
--force-script --force-review --force-humanize --force-tts
```

如果只想测试“真人口播润色”后的文案，不想重新生成配音，可以用：

```powershell
.\.venv\Scripts\python.exe -m scripts.run_pipeline `
  --input videos/input.mp4 `
  --context context.json `
  --target-duration 120 `
  --require-llm `
  --force-humanize `
  --tts-mode none
```

## 启动本地 API

后续前端会调用本地 FastAPI 后端。启动方式：

```powershell
.\.venv\Scripts\python.exe -m scripts.run_api
```

默认地址：

```text
http://127.0.0.1:8000
```

第一版 API 负责项目、上下文包、版本、渲染任务和任务状态查询；视频切片仍然复用现有 `video_slicer.pipeline`，不会从 API 层重写剪辑逻辑。

## 输出文件

运行后主要看这些文件：

- `outputs/final_with_voiceover.mp4`：最终带新配音的视频
- `outputs/final_with_bgm.mp4`：可选，带新配音和背景音乐的视频
- `outputs/output.mp4`：无原声的剪辑预览
- `outputs/voiceover_script.txt`：大模型生成并审查后的配音文案
- `outputs/voiceover_script.json`：配音文案、来源字幕和上下文引用
- `outputs/voiceover_humanize_diff.txt`：真人口播润色前后对比
- `outputs/voiceover.srt`：新配音字幕
- `outputs/alignment.json`：配音句子和原字幕时间戳映射
- `outputs/quality_report.json`：质量报告，检查时长、画面倒跳、画面重叠、证据跨度过长、模型指定字幕低证据分、顺序 fallback 修正、连续画面支撑、英文残留等风险
- `outputs/time_mapping.json`：最终视频时间和原视频时间映射
- `outputs/final_voiceover_transcript.json`：最终配音文案时间轴

`quality_report.json` 目前只做风险提示，不会自动阻止成片。建议每次生成后优先看它的 `status`、`metrics` 和 `issues`：如果出现 `source_timeline_backtrack`、`source_timeline_major_overlap`、`source_evidence_span_too_long`、`llm_source_ids_low_evidence_score`、`llm_source_ids_replaced_by_ordered_fallback`、`visual_duration_outside_tolerance`，说明这次成片需要重点复查。`continuity_visual_support_low_evidence` 是 info，表示这句不是可信字幕语义匹配，而是使用顺序画面支撑；可以结合 `continuity_visual_support_count` 判断这类句子是否过多。

## 复用到别的视频

换新视频时，把视频放到 `videos/` 下面，然后改命令里的 `--input`。同时复制一份新的上下文包，写清楚人物、剧情背景、禁止出现的错误剧情和解说风格。

这个 demo 暂时没有做 OCR，所以如果视频里关键信息只出现在画面文字里、字幕没有说出来，需要手动补到 `context.json` 里。

## 注意

请确认你有权处理和分享输入视频。公开视频、课程内部仓库或私有仓库的使用边界不一样，正式公开前最好再检查版权风险。


## Fish Audio 配音和声音克隆

Fish Audio 作为 TTS provider 使用。你只需要在 `.env` 填：

```env
FISH_API_KEY=put_your_fish_audio_key_here
FISH_TTS_MODEL=s2.1-pro-free
FISH_REFERENCE_ID=
```

先准备一段本地参考音频：

```text
assets/voice_refs/my_voice.mp3
```

建议参考音频 10 到 30 秒，单人说话，背景干净，没有音乐或多人重叠。

创建私有声音模型，并把声音 ID 记录到本地注册表：

```powershell
.\.venv\Scripts\python.exe -m scripts.create_fish_voice `
  --audio assets/voice_refs/my_voice.mp3 `
  --name narrator_a
```

命令会把 Fish 返回结果写到：

```text
outputs/fish_voice_model_narrator_a.json
```

同时会把声音记录到本地注册表：

```text
assets/voice_refs/fish_voice_models.local.json
```

如果你想让这个声音成为默认声音，把终端打印的 `_id` 填到 `.env`：

```env
FISH_REFERENCE_ID=返回的_id
```

如果只想试听声音，不跑完整切片流程，可以生成一段单独的 mp3：

```powershell
.\.venv\Scripts\python.exe -m scripts.preview_tts `
  --provider fish `
  --text "这个片段的冲突，从主角走进房间那一刻就已经开始了。" `
  --output outputs/fish_preview.mp3
```

之后正式运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.run_pipeline `
  --input videos/input.mp4 `
  --context context.json `
  --target-duration 120 `
  --tts-mode fish
```

## 批量生产

复制 `batch.example.json`，为每个视频写一个 job：

```powershell
Copy-Item batch.example.json batch.local.json
```

然后运行：

```powershell
.\.venv\Scripts\python.exe -m scripts.run_batch --manifest batch.local.json
```

每个 job 建议使用独立 `output_dir`，例如 `outputs/job_001`、`outputs/job_002`，这样批量生产时不会互相覆盖。
## 本地项目数据结构

项目正在从单个 demo pipeline 演进为“一个素材，多版本成片”的产品结构。

本地数据默认写入：

```text
projects.local/
  projects/
    <project_id>/
      project.json
      versions/
        <version_id>.json
      jobs/
        <job_id>.json
```

这类数据是本地运行产物，不应该提交到 Git。

如果想让命令行 pipeline 写入项目、版本和任务记录，可以在原命令后增加：

```powershell
--record-project --project-root projects.local
```

也可以指定项目和版本：

```powershell
--record-project --project-id project_demo --version-id version_120s
```

不加 `--record-project` 时，旧流程完全不写项目记录。

项目记录会预留隐私和数据治理字段：

- `user_id`：本地模式为 `local_user`，未来用于账号归属。
- `data_region`：本地模式为 `local`，未来用于云端数据区域。
- `privacy_flags`：标记是否包含声音克隆、人物音频、敏感内容。
- `retention_until`：未来用于自动清理。
- `deleted_at`：未来用于软删除和异步物理删除。

### 概念

- 项目：一个原视频素材。
- 版本：同一个素材的一套成片方案，例如 60 秒纯解说版、120 秒关键原声版。
- 任务：一次生成或渲染动作，记录当前阶段、状态、导出路径和最终成片时长。
