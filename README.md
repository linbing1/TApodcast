# TApodcast

将 The Athletic 的英超新闻文章快速转换为可发布到抖音的中文竖屏视频：中文口播、图片轮播、字幕、封面和发布文案。

## 产品边界

本工程服务于每日英超新闻视频，不是新闻事实审计系统。流程聚焦最值得播报的新闻主题、球队、人物、比赛结果、转会和关键数字；允许省略次要背景与细节。标题和口播稿不仅要说明发生了什么，还要让球迷产生继续观看和收听的兴趣。

- 不运行 LLM 审校、评分、事实清单核验或自动改稿。
- 不要求覆盖原文全部内容。
- 标题的吸引力来自原文中的冲突、转折、悬念、影响或人物选择；不得凭空补充信息，也不得制造错误悬念。
- 不得把比分、转会状态、球队和主要人物讲反。
- 只保留不增加 LLM 成本的安全检查：空稿、固定节目开头和结尾、Markdown 代码块污染、空标题、TTS 截断、图片/视频产物缺失。

## Agent 自动处理协议

其他 Agent 处理文章时应优先遵循本节，不要自行添加审校、改稿或额外 LLM 调用。

### 输入和目录

必需输入是一条完整的 The Athletic 文章 URL。可选输入为输出目录；未指定时使用 `output/<运行日期>/<article-slug>/`。

```bash
URL="https://www.nytimes.com/athletic/ARTICLE_ID/article-slug/"
SLUG="${URL%/}"
SLUG="${SLUG##*/}"
OUT="output/$(date +%F)/$SLUG"
```

同一篇文章的重试必须继续使用同一个 `OUT`。仅当用户明确要求不生成视频时，才添加 `--skip-video`。

### 标准执行

先检查环境；本地检查出现 `FAIL` 时先修复环境再处理文章。

```bash
git status --short --branch
.venv/bin/python main.py doctor
.venv/bin/python main.py doctor --online --url "$URL"
```

首次处理：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT"
```

只生成到音频：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --skip-video
```

已有输出目录时先预览、再断点续跑：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --resume --dry-run
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --resume
```

`--force <阶段>` 只强制该阶段重新执行，**不会关闭 LLM 缓存**；输入和提示词未改变时仍会复用 `.llm-cache/` 中的响应。例如重新生成口播及其下游产物：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from write-script --force write-script
```

### 完成定义

仅在以下条件满足后报告“处理完成”：

1. `manifest.json` 中本次执行范围的阶段均为 `completed`。
2. `title.txt` 和 `script.txt` 存在且非空；口播稿以固定节目开头开始，并以固定节目结尾结束。
3. `audio.mp3`、`audio.vtt`、`image_captions.json` 存在且非空。
4. 完整流程还生成竖屏 MP4、`cover.png`、`cover-landscape.png`、`publish.json`、`publish_title.txt` 和 `publish_description.txt`。
5. MP4 为 `1080×1920`、`30fps`，并同时包含 H.264 视频流和 AAC 音频流。
6. `cover.png` 为 `1080×1920`，`cover-landscape.png` 为 `1920×1080`。
7. `publish.json` 的标题与 `title.txt` 完全一致，成功结束后没有残留 `frames/` 目录。

不要把仅运行测试、历史抓取复用、部分产物或失败阶段说成一次完整的新处理。

### 失败恢复

| 情况 | 处理方式 |
|------|----------|
| 文章提取失败 | 重试一次；仍失败时只能复用 URL 完全匹配的历史 `page.json`，并在交付时明确说明。 |
| 图片下载失败 | 重试下载；仍失败时只能复用同一 URL 的历史图片资产。 |
| 分析或口播 LLM 输出格式不合法 | 从失败阶段重新运行；口播稿失败使用 `--from write-script --force write-script`。 |
| TTS 连接失败或截断 | 等待内置重试；仍失败时从 `generate-audio` 重跑。 |
| 视频、封面或发布文案失败 | 修复本地依赖或输入后，从相应阶段重跑。 |

历史页面复用示例：

```bash
rg -l --fixed-strings "$URL" output -g 'page.json'
MATCH="/path/to/matched/page.json"
mkdir -p "$OUT"
cp "$MATCH" "$OUT/page.json"
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from download-images
```

复用前必须确认 `page.json` 的 `url` 与输入 URL 完全一致，且 `main_text` 非空。不得用搜索摘要、其他报道或模型记忆替代原文。

## 流程和产物

完整流程共八个阶段：

```text
extract
→ download-images
→ analyze-content
→ write-script
→ generate-audio
→ video
→ cover
→ publish-copy
```

| 阶段 | 作用 | 主要产物 |
|------|------|----------|
| `extract` | 提取正文、图片、视频清单 | `page.json`、`text.txt`、`images.json`、`videos.json` |
| `download-images` | 下载文章图片并确定封面主图 | `images/`、`images.json`、`cover.json` |
| `analyze-content` | 用 LLM 提炼适合新闻视频的中文上下文 | `analysis.json` |
| `write-script` | 用 LLM 直接生成有新闻钩子的中文标题和最终口播稿 | `title.txt`、`script.txt` |
| `generate-audio` | 生成图片中文图注、TTS 音频和时间字幕 | `image_captions.json`、`audio.mp3`、`audio.vtt` |
| `video` | 合成图片轮播、口播音频和字幕 | `subtitles.ass`、`<中文标题>.mp4` |
| `cover` | 生成竖版和横版封面 | `cover.png`、`cover-landscape.png` |
| `publish-copy` | 生成抖音标题、简介和传播导向标签 | `publish.json`、`publish_title.txt`、`publish_description.txt` |

`write-script` 的目标长度随清洗后的原文长度线性变化：

```text
target_chars = clamp(round(source_chars × 0.04 + 400), 500, 1000)
```

这是一次性精炼目标，不会为调节长度再次请求 LLM。原文约 3,000、8,000、10,000 字时，目标稿长约为 520、720、800 字。

标题生成规则：标题不只是文章主旨的平铺直叙，而是从原文提炼一个可验证的新闻钩子，例如意外结果、关键转折、潜在影响、人物选择、转会悬念、战术问题或冲突。标题应具体、有信息量，并让球迷产生继续观看或收听的兴趣；标题的吸引力不能依靠夸大、虚构或错误悬念。

发布文案包含 5 至 10 个标签。标签以核心球队和主题为主，也可包含原文明确关联的球队以及真实相关的英超、足球新闻、转会、比赛或战术话题，以提升发现性；不添加文章无关的人物、球队或热点。

## 命令

```bash
# 从 URL 跑完整视频流程
.venv/bin/python main.py run --url "$URL" --dir "$OUT"

# 只运行单一阶段
.venv/bin/python main.py analyze-content --dir "$OUT"
.venv/bin/python main.py write-script --dir "$OUT"
.venv/bin/python main.py generate-audio --dir "$OUT"
.venv/bin/python main.py video --dir "$OUT"
.venv/bin/python main.py cover --dir "$OUT"
.venv/bin/python main.py publish-copy --dir "$OUT"

# 删除视频编码失败时留下的中间帧
.venv/bin/python main.py cleanup --dir "$OUT"
```

`run --from`、`run --to` 和 `run --force` 均只接受上述八个阶段名。

## 环境要求

- Python 3.12
- 支持 `libass` 的 `ffmpeg-full`（macOS：`brew install ffmpeg-full`）
- Playwright Chromium（`playwright install chromium`）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

| 变量 | 必填 | 说明 |
|------|------|------|
| `LLM_API_KEY` | 是 | OpenAI 兼容 LLM 服务的 API Key |
| `ATHLETIC_COOKIES` | 是 | The Athletic 登录 Cookie（JSON 数组） |
| `LLM_BASE_URL` | 否 | 默认 `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 否 | 默认 `deepseek-v4-flash` |
| `LLM_MAX_REQUESTS_PER_ARTICLE` | 否 | 单篇文章最多实际 LLM 请求数，默认 `12`；缓存命中不计入 |
| `TTS_VOICE` | 否 | 默认 `zh-CN-YunjianNeural` |
| `TTS_RATE` | 否 | 默认 `+10%` |
| `CJK_FONT_PATH` | 否 | 字幕和封面使用的中文字体文件 |
| `COVER_DATE_FONT_PATH` | 否 | 封面日期字体 |

配置只从进程环境变量读取，不会自动加载 `.env`。脚本、定时任务和 CI 需要自行显式注入所需变量。

## 输出目录

```text
output/YYYY-MM-DD/<article-slug>/
├── manifest.json              # 阶段状态、配置、提示词版本和 LLM 用量
├── llm-usage.jsonl            # 每次 LLM 请求、缓存命中和 Token 记录
├── .llm-cache/                # 可复用的 LLM 响应缓存
├── page.json                  # 原始正文、图片元数据和封面候选
├── text.txt
├── images/                    # 下载的文章图片
├── images.json
├── videos.json
├── cover.json
├── analysis.json              # 新闻视频所需的中文摘要上下文
├── title.txt                  # 中文视频标题
├── script.txt                 # 最终中文口播稿
├── image_captions.json
├── audio.mp3
├── audio.vtt
├── subtitles.ass
├── cover.png
├── cover-landscape.png
├── publish.json
├── publish_title.txt
├── publish_description.txt
└── <中文标题>.mp4
```

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
```
