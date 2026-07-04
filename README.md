# 自动影视解说切片 Demo

这个仓库是一个“配音文案优先”的视频自动切片 demo。流程会先从原视频提取语音字幕，再用大模型结合人工上下文包生成影视解说文案，经过语义审查后生成 TTS 配音，最后按配音文案对应的原视频字幕时间戳剪辑画面，并移除原视频声音。

当前 demo 使用同一套已验证参数：

- 默认输入视频：`videos/input.mp4`
- 上下文模板：`context.example.json`
- 文本模型：`gpt-4.1`
- 真人口播润色模型：`qwen-plus-latest`
- TTS 模型：`tts-1-hd`
- TTS voice：`echo`
- TTS speed：`0.72`
- 目标时长：约 `120` 秒

## 应该上传到 GitHub 的文件

建议提交这些文件，方便同学直接复用：

- `1.py`：主程序
- `requirements.txt`：Python 依赖
- `README.md`：使用说明
- `.gitignore`：忽略本地密钥、输出和缓存
- `.env.example`：环境变量模板，不包含真实 key
- `context.example.json`：通用上下文包模板
- `videos/.gitkeep`：保留空的视频目录

不要提交这些文件：

- `.env`：里面有你的 API key
- `.venv/`：本地虚拟环境
- `outputs/`：运行输出，别人可以自己生成
- `outputs_archive/`：历史输出归档
- `context.json`：本地实际上下文包，可以由模板复制出来
- `videos/*.mp4`：本地输入视频，别人可以换成自己的视频
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

打开 `.env`，把下面这一行换成你自己的 OCool key：

```env
OCOOL_API_KEY=put_your_ocool_api_key_here
```

`.env` 已经被 `.gitignore` 忽略，不要手动把它加进 Git。

## 配置上下文包

复制 demo 上下文模板：

```powershell
Copy-Item context.example.json context.json
```

`context.json` 是本地运行时读取的上下文包。你可以在里面改视频标题、人物关系、剧情梗概、禁用词和解说风格。

其中这几个字段和复用关系最大：

- `forbidden_terms`：不允许出现在文案里的词。
- `forbidden_story_facts`：不允许模型写错的剧情方向。
- `humanize_unsafe_detail_terms`：某个视频里容易被模型脑补、但没有证据的画面细节。
- `tts_unfriendly_terms`：TTS 容易读错或听起来别扭的表达。

## 放入视频

把要处理的视频放到 `videos/` 目录。最简单的方式是命名成默认输入：

```powershell
Copy-Item 你的视频.mp4 videos/input.mp4
```

## 运行 demo

使用已验证的同款参数运行：

```powershell
.\.venv\Scripts\python.exe 1.py `
  --input videos/input.mp4 `
  --context context.json `
  --target-duration 120 `
  --ocool-model gpt-4.1 `
  --ocool-humanize-model qwen-plus-latest `
  --require-llm `
  --tts-mode ocool `
  --ocool-tts-model tts-1-hd `
  --ocool-tts-voice echo `
  --ocool-tts-speed 0.72
```

如果想强制重新生成脚本、审稿和配音，可以加：

```powershell
--force-script --force-review --force-humanize --force-tts
```

如果只想测试“真人口播润色”后的文案，不想重新生成配音，可以用：

```powershell
.\.venv\Scripts\python.exe 1.py `
  --input videos/input.mp4 `
  --context context.json `
  --target-duration 120 `
  --require-llm `
  --force-humanize `
  --tts-mode none
```

## 输出文件

运行后主要看这些文件：

- `outputs/final_with_voiceover.mp4`：最终带新配音的视频
- `outputs/output.mp4`：无原声的剪辑预览
- `outputs/voiceover_script.txt`：大模型生成并审查后的配音文案
- `outputs/voiceover_script.json`：配音文案、来源字幕和上下文引用
- `outputs/voiceover_humanize_diff.txt`：真人口播润色前后对比
- `outputs/voiceover.srt`：新配音字幕
- `outputs/alignment.json`：配音句子和原字幕时间戳映射
- `outputs/time_mapping.json`：最终视频时间和原视频时间映射
- `outputs/final_voiceover_transcript.json`：最终配音文案时间轴

## 复用到别的视频

换新视频时，把视频放到 `videos/` 下面，然后改命令里的 `--input`。同时复制一份新的上下文包，写清楚人物、剧情背景、禁止出现的错误剧情和解说风格。

这个 demo 暂时没有做 OCR，所以如果视频里关键信息只出现在画面文字里、字幕没有说出来，需要手动补到 `context.json` 里。

## 注意

请确认你有权处理和分享输入视频。公开视频、课程内部仓库或私有仓库的使用边界不一样，正式公开前最好再检查版权风险。
