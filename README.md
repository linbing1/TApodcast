# TApodcast

将 The Athletic 的英超新闻文章转换为可发布到抖音的中文竖屏视频：中文标题、口播、图片轮播、字幕、封面和发布文案。

本 README 同时是其他 Agent 的执行协议。处理文章时，优先按“给 Agent 的最短流程”和“失败恢复”执行，不要自行增加审校、改稿或额外 LLM 调用。

**处理文章期间禁止修改项目代码。** Agent 只能按照现有流程运行命令、检查输出和报告问题，不得为了让当前文章跑通而修改 Python、README、配置默认值、测试或其他项目文件。遇到无法通过重试、断点续跑或已有恢复方式解决的错误时，必须暂停处理，不要绕过检查、伪造产物或临时改代码，并向用户报告错误信息、失败阶段、输出目录、已尝试的命令和建议的下一步；等待用户确认后再进行代码级修复。

## 给 Agent 的最短流程

### 1. 准备输入和输出目录

输入必须是一条完整的 The Athletic 文章 URL，例如：

```bash
URL="https://www.nytimes.com/athletic/ARTICLE_ID/article-slug/"
SLUG="${URL%/}"
SLUG="${SLUG##*/}"
OUT="output/$(date +%F)/$SLUG"
```

同一篇文章的重试、断点续跑和补跑必须使用同一个 `OUT`。不要因为失败就创建新的目录，否则会分散 manifest、缓存、Token 记录和历史产物。

### 2. 首次或环境变化时检查本机

每台机器首次使用、依赖变更或出现环境异常时执行一次：

```bash
.venv/bin/python main.py doctor
```

只有 `doctor` 没有 `FAIL` 时才开始处理文章。连续处理多篇文章且环境没有变化时，不必重复执行；不要把 `doctor --online` 当作每篇文章的固定步骤。

### 3. 运行完整流程

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT"
```

这条命令按八个阶段顺序运行。输出目录已有 `manifest.json` 时，程序默认启用断点续跑：输入和输出没有变化的阶段会跳过，变化的阶段会重新运行。

如果命令返回错误，先按“失败恢复”处理。若没有明确的恢复方式，或重试后仍然失败，立即暂停，不要在处理文章的过程中修改代码。

### 4. 最后执行交付验证

```bash
.venv/bin/python main.py verify --dir "$OUT"
```

只有 `verify` 返回成功，才能向用户报告“完整处理完成”。验证失败时，先根据报告修复或重跑，再重新执行 `verify`。

### 5. 处理完成后的报告

交付时至少说明：

- 输出目录 `OUT`；
- 最终 MP4 文件路径；
- `verify` 是否通过；
- 标题和口播稿是否生成；
- `manifest.json` 或 `llm-usage.jsonl` 中记录的 LLM 请求和 Token 用量。

## 产品边界

本工程服务于每日英超新闻视频，不是新闻事实审计系统。目标是快速抓住最值得播报的新闻主题、球队、人物、比赛结果、转会和关键数字；允许省略次要背景与细节。

- 不运行 LLM 审校、评分、事实清单核验或自动改稿。
- 不要求覆盖原文全部内容。
- 标题和口播稿要让球迷产生继续观看或收听的兴趣，但吸引力必须来自原文中的冲突、转折、悬念、影响或人物选择。
- 不得凭空补充信息，也不得把比分、转会状态、球队和主要人物讲反。
- 只保留不增加 LLM 成本的安全检查：空稿、固定节目开头和结尾、Markdown 代码块污染、空标题、TTS 截断、图片/视频产物缺失。

## 运行方式

### 新文章和普通重试

新文章直接执行完整流程：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT"
```

同一目录再次执行时，默认会根据 `manifest.json`、输入文件指纹、配置和提示词版本判断是否跳过阶段。需要先查看计划时：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --resume --dry-run
```

确认计划后再次执行：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --resume
```

### 只生成音频

只有用户明确不需要视频时，才使用：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --skip-video
```

`--skip-video` 会在 `generate-audio` 后停止，因此不会生成视频、封面或发布文案；这种输出不是完整交付，不能用 `verify` 作为完整流程通过证明。

### 从指定阶段补跑

`--from` 和 `--to` 选择一个连续的阶段范围，范围之前的输入必须已经存在。发生阶段失败时，通常从失败阶段开始补跑：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from analyze-content
```

如果修改了口播生成逻辑，强制重跑 `write-script`，并让后续依赖阶段重新判断：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from write-script --force write-script
```

`--force <阶段>` 只强制指定阶段，不会关闭 LLM 缓存。输入和提示词未变化时，LLM 仍会复用该文章目录中的 `.llm-cache/`，不会因为 `--force` 自动增加 API 请求。只有确实需要从头重建时才使用 `--no-resume`；不要把它作为普通重试选项。

### 单阶段命令

单阶段命令主要用于故障恢复，不是首选的日常入口：

```bash
.venv/bin/python main.py extract --url "$URL" --dir "$OUT"
.venv/bin/python main.py download-images --dir "$OUT"
.venv/bin/python main.py analyze-content --dir "$OUT"
.venv/bin/python main.py write-script --dir "$OUT"
.venv/bin/python main.py generate-audio --dir "$OUT"
.venv/bin/python main.py video --dir "$OUT"
.venv/bin/python main.py cover --dir "$OUT"
.venv/bin/python main.py publish-copy --dir "$OUT"
```

单阶段命令默认也会跳过输入未变化且产物完整的阶段；需要重新执行时在对应命令后加 `--force`。如果重跑了某个阶段，仍要执行后续依赖阶段，最后再运行 `verify`。

## 失败恢复

| 情况 | 处理方式 |
|------|----------|
| `doctor` 出现 `FAIL` | 先按“环境配置”修复，重新执行 `doctor`，不要直接运行文章流程。 |
| 文章提取失败 | 原目录重试一次；仍失败时，只能复用 URL 完全匹配的历史 `page.json`，并在交付说明。 |
| 图片下载失败 | 检查 Cookie、网络和磁盘后，从 `download-images` 重跑。不要把其他文章的图片当作替代品。 |
| `analyze-content` 或 `write-script` 失败 | 从失败阶段重跑；不要额外调用审校模型。LLM 预算耗尽时先查看 `manifest.json` 和 `llm-usage.jsonl`。 |
| TTS 连接失败或音频疑似截断 | 等待内置重试；仍失败时从 `generate-audio` 重跑。 |
| 视频失败且留下 `frames/` | 修复 FFmpeg、字体或输入后重跑 `video`；交付前执行 `cleanup` 删除中间帧。 |
| 封面失败 | 修复图片、字体或标题后从 `cover` 重跑。 |
| 发布文案失败 | 确认 `title.txt`、`script.txt`、`analysis.json` 存在且标题不为空、长度不超过 30 字，再从 `publish-copy` 重跑。 |
| `verify` 失败 | 按报告逐项修复；需要重跑相应阶段，直到 `verify` 返回成功。 |

遇到不可恢复错误时，Agent 应停止后续阶段，并按以下格式报告，不要继续猜测或强行生成结果：

```text
处理已暂停
失败阶段：<阶段名>
错误：<完整错误信息>
输出目录：<OUT>
已尝试：<执行过的重试、补跑或检查命令>
当前状态：<已有产物和 manifest 状态>
建议下一步：<需要用户确认的代码修复、配置修复或人工操作>
```

文章提取确实无法完成时，才允许复用同一 URL 的历史页面：

```bash
rg -l --fixed-strings "$URL" output -g 'page.json'
MATCH="/path/to/matched/page.json"
mkdir -p "$OUT"
cp "$MATCH" "$OUT/page.json"
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from download-images
```

复用前必须确认历史 `page.json` 的 `url` 与输入 URL 完全一致、`main_text` 非空。不得用搜索摘要、其他报道或模型记忆替代原文。复用历史页面必须在交付时明确说明，不能当作本次成功抓取。

## 八个阶段

完整流程固定为八个阶段；`verify` 是八阶段之后的只读交付检查，不是第九个 Pipeline 阶段。

```text
extract
→ download-images
→ analyze-content
→ write-script
→ generate-audio
→ video
→ cover
→ publish-copy
→ verify（只读交付检查，不属于 Pipeline）
```

| 阶段 | 输入和作用 | 主要产物 | LLM |
|------|------------|----------|-----|
| `extract` | 访问文章 URL，提取正文、图片和视频元数据 | `page.json`、`text.txt`、`videos.json` | 否 |
| `download-images` | 根据 `page.json` 下载图片，并确定封面候选 | `images/`、`images.json`、`cover.json` | 否 |
| `analyze-content` | 从原文提炼适合短新闻视频的中文上下文 | `analysis.json` | 是 |
| `write-script` | 根据原文和分析一次性生成吸引人的中文标题与最终口播稿 | `title.txt`、`script.txt` | 是 |
| `generate-audio` | 用 LLM 翻译并精简图片图注，再使用 Edge TTS 生成音频和时间字幕 | `image_captions.json`、`audio.mp3`、`audio.vtt` | 是 |
| `video` | 按成功下载顺序合成图片、音频和字幕，并校验媒体参数 | `subtitles.ass`、`<安全标题>.mp4` | 否 |
| `cover` | 使用已下载图片生成竖版和横版封面，并校验尺寸 | `cover.png`、`cover-landscape.png` | 否 |
| `publish-copy` | 根据标题、口播和分析本地生成抖音发布文案与标签 | `publish.json`、`publish_title.txt`、`publish_description.txt` | 否 |

### 内容生成规则

`write-script` 的目标口播长度根据清洗后的原文长度线性计算：

```text
target_chars = clamp(round(source_chars × 0.04 + 400), 500, 1000)
```

这是一次性精炼目标，不会为了调整长度反复请求 LLM。实际稿件可能与目标有偏差，流程只记录目标字数、实际字数和偏差，不会因为偏差再次调用或直接失败。

标题不只是原文标题的直译，而是从原文提炼一个可验证的新闻钩子，例如意外结果、关键转折、潜在影响、人物选择、转会悬念、战术问题或冲突。标题最多 30 个字符，不能依靠夸大、虚构或错误悬念吸引点击。

`publish-copy` 完全本地运行，不调用 LLM。它只读取 `title.txt`、`script.txt` 和 `analysis.json`；`title.txt` 是唯一标题来源，不会回退到原文标题或再次改写。标签通常生成 5 至 10 个，除核心球队和主题外，可加入原文明确关联的球队、英超、足球新闻、转会、比赛或战术话题，以提高发现性；不得添加无关热点。

### 阶段实现约束

- `analyze-content`、`write-script` 和 `generate-audio` 是文章处理中的 LLM 阶段；`generate-audio` 通常为整篇文章的图片图注发起一次翻译请求。
- `generate-audio` 会保留已有中文图注，并将英文图片说明批量交给 LLM 翻译和精简；输入和提示词不变时复用 `.llm-cache/`，缓存命中不计入 API 请求预算。
- `video` 只使用 `images.json` 中 `status=downloaded` 且文件实际存在的图片，不扫描 `images/` 中的历史遗留文件。
- `video` 写入临时 MP4，随后用 `ffprobe` 检查时长、分辨率、帧率、H.264 视频流和 AAC 音频流；校验通过后才替换正式文件。
- `cover` 写入临时 PNG，校验非空、格式和尺寸后才替换正式文件。竖版为 `1080×1920`，横版为 `1920×1080`。
- `publish-copy` 写入并校验标题、简介、标签及三个发布文件的一致性。

## LLM 调用和预算

每篇文章的实际 LLM API 请求预算由 `LLM_MAX_REQUESTS_PER_ARTICLE` 控制，默认 `12`。正常情况下，`analyze-content`、`write-script` 和 `generate-audio` 各最多产生一次未命中缓存的请求；缓存命中不计入预算，网络重试会记录在对应请求的尝试次数中。预算使用情况会持续写入：

- `llm-usage.jsonl`：逐次记录 API 请求、缓存命中、Token 和错误；
- `manifest.json`：记录累计 API 请求、缓存命中、Prompt/Completion/Total Token、剩余预算和按阶段汇总。

当单篇文章的实际 API 请求达到预算时，下一次未命中缓存的 LLM 请求会直接使当前阶段失败，不会静默超额调用。此时不要用 `--no-resume` 反复重跑；先确认是否有缓存可复用，或提高预算后从失败阶段继续。

`doctor --online` 会额外进行在线连通性检查，其中 LLM 检查会消耗少量 Token；它不属于文章八阶段，也不会替代 `analyze-content` 或 `write-script`。

## 环境配置

### 依赖

- Python 3.12 或更高版本；
- 支持 `libass` 的 FFmpeg（macOS 可执行 `brew install ffmpeg-full`）；
- Playwright Chromium。

首次安装：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

### 环境变量

配置只从当前进程环境变量读取，不会自动加载 `.env`。必填变量如下：

| 变量 | 必填 | 默认值或说明 |
|------|------|-------------|
| `LLM_API_KEY` | 是 | OpenAI 兼容 LLM 服务的 API Key |
| `ATHLETIC_COOKIES` | 是 | The Athletic 登录 Cookie 的 JSON 数组 |
| `LLM_BASE_URL` | 否 | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 否 | `deepseek-v4-flash` |
| `LLM_MAX_REQUESTS_PER_ARTICLE` | 否 | `12`；单篇文章实际 API 请求上限 |
| `TTS_VOICE` | 否 | `zh-CN-YunjianNeural` |
| `TTS_RATE` | 否 | `+10%` |
| `CJK_FONT_PATH` | 否 | 字幕和封面使用的中文字体路径 |
| `COVER_DATE_FONT_PATH` | 否 | 封面日期字体路径 |
| `FFMPEG_BIN` | 否 | FFmpeg 可执行文件路径 |
| `FFPROBE_BIN` | 否 | 与 FFmpeg 配套的 ffprobe 路径 |

### 安全注入敏感变量

不要把真实的 API Key、Cookie JSON、`.env` 文件或包含它们的脚本写入仓库、输出目录、提交记录或服务器代码目录。可使用当前终端、本机受保护配置、系统钥匙串、CI/CD Secret 或服务器 Secret 管理功能注入。

临时输入到当前终端时，使用下面的有效 shell 写法：

```bash
printf "LLM_API_KEY: "
read -r -s LLM_API_KEY
printf "\nATHLETIC_COOKIES JSON: "
read -r -s ATHLETIC_COOKIES
printf "\n"
export LLM_API_KEY ATHLETIC_COOKIES
```

如果本机已经在 `~/.zshrc` 中配置并导出变量，可以执行：

```bash
source ~/.zshrc
.venv/bin/python main.py doctor
```

项目不直接读取 `~/.zshrc`，只读取当前进程环境。服务器或 CI 不会自动拥有本机的 `~/.zshrc`，应通过服务器的 Secret 功能注入同名变量，不要上传该文件。

获取 Cookie 时，在浏览器登录 The Athletic 后用 Cookie-Editor 导出当前站点的 Cookie JSON 数组。它必须是非空数组，每个有效条目至少包含 `name` 和 `value`；导出内容不要保存到 Git 或上传到服务器代码目录。

### doctor 检查

```bash
.venv/bin/python main.py doctor
```

`doctor` 只做本机准备检查，包括 Python、Cookie、LLM 配置、TTS 配置、输出目录和磁盘空间、Playwright Chromium、FFmpeg/libass 及中文字体。出现 `FAIL` 时先修复再处理文章；`WARN` 可以继续，但应理解对应风险。

排查网络、Cookie 或 LLM/TTS 服务连通性时，按需执行：

```bash
.venv/bin/python main.py doctor --online --url "$URL"
```

该命令会产生额外网络请求，LLM 检查会消耗少量 Token；不要把它作为每篇文章的固定步骤。

## 完成定义和 verify

完整交付必须满足：

1. `manifest.json` 中八个阶段均为 `completed`；
2. `title.txt`、`script.txt` 非空，口播包含固定节目开头和结尾；
3. `audio.mp3`、`audio.vtt`、`image_captions.json` 存在且非空；
4. 竖版 MP4、`cover.png`、`cover-landscape.png`、`publish.json`、`publish_title.txt` 和 `publish_description.txt` 存在且非空；
5. MP4 为 `1080×1920`、`30fps`，同时包含 H.264 视频流和 AAC 音频流；
6. `cover.png` 为 `1080×1920`，`cover-landscape.png` 为 `1920×1080`；
7. `publish.json`、`publish_title.txt` 与 `title.txt` 标题一致，发布描述文件与 `publish.json` 一致；
8. 输出目录没有残留 `frames/`。

执行：

```bash
.venv/bin/python main.py verify --dir "$OUT"
```

`verify` 只读、不联网、不调用 LLM、不修改输出目录；失败返回非零退出码。若只想删除视频编码失败留下的中间帧：

```bash
.venv/bin/python main.py cleanup --dir "$OUT"
```

## 输出目录

```text
output/YYYY-MM-DD/<article-slug>/
├── manifest.json              # 八阶段状态、配置、提示词版本和 LLM 用量
├── llm-usage.jsonl            # 每次 LLM 请求、缓存命中和 Token 记录
├── .llm-cache/                # 当前文章可复用的 LLM 响应缓存
├── page.json                  # 原文正文、图片元数据和封面候选
├── text.txt                   # 清洗后的正文
├── videos.json                # 文章视频元数据
├── images/                    # 已下载文章图片
├── images.json                # 图片下载状态和顺序
├── cover.json                 # 封面图片选择
├── analysis.json              # LLM 生成的新闻上下文
├── title.txt                  # 唯一的中文视频标题来源
├── script.txt                 # 最终中文口播稿
├── image_captions.json        # 本地图注
├── audio.mp3                  # TTS 音频
├── audio.vtt                  # TTS 时间字幕
├── subtitles.ass              # 视频烧录字幕
├── cover.png                  # 竖版封面
├── cover-landscape.png        # 横版封面
├── publish.json               # 抖音发布文案结构化结果
├── publish_title.txt          # 抖音标题
├── publish_description.txt    # 抖音描述和标签
└── <安全标题>.mp4              # 最终竖屏视频
```

不要把 `.llm-cache/`、`llm-usage.jsonl` 或文章输出目录当作新的输入来源；它们只用于断点续跑、成本统计和交付检查。

## 常用命令速查

```bash
# 查看所有命令
.venv/bin/python main.py --help

# 查看完整流程将运行哪些阶段
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --resume --dry-run

# 只查看某个阶段的帮助
.venv/bin/python main.py write-script --help

# 删除视频中间帧
.venv/bin/python main.py cleanup --dir "$OUT"

# 验证完整交付
.venv/bin/python main.py verify --dir "$OUT"
```

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
```
