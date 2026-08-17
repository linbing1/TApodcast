# TApodcast

将 The Athletic 文章自动生成适合抖音发布的竖屏短视频（中文配音 + 图片轮播 + 字幕）。

## 五步流程

```
文章 URL
  → 第一步：解析正文/图片/视频，保存原始图注并下载图片
  → 第二步：LLM 分析正文与图注，生成播报稿、TTS 配音与字幕
  → 第三步：图片和对应中文图注轮播，合成配音与字幕
  → 第四步：使用文章主图和中文标题生成抖音封面
  → 第五步：生成抖音发布标题、作品简介和话题
```

| 步骤 | 输入 | 主要处理 | 产物 |
|------|------|----------|------|
| 第一步：内容解析 | The Athletic 文章 URL | 提取主要文字、图片、原始图注和视频清单，分离图注与署名，确定封面主图并下载图片 | `page.json`、`text.txt`、`images/`、`images.json`、`videos.json`、`cover.json` |
| 第二步：LLM + TTS | `page.json`、`images.json` | 分析正文，将英文图片说明翻译并精简为中文，生成中文播报稿、约三分钟配音和时间字幕 | `analysis.json`、`image_captions.json`、`title.txt`、`script.txt`、`audio.mp3`、`audio.vtt` |
| 第三步：视频合成 | `images/`、`image_captions.json`、`audio.mp3`、`audio.vtt` | 按图片路径匹配中文图注，生成图片轮播并烧录黄色口播字幕 | `subtitles.ass`、`<中文标题>.mp4` |
| 第四步：封面生成 | 封面主图和 `title.txt` | 生成带栏目标签、当前日期和中文标题的竖版与横版独立封面 | `cover.png`、`cover-landscape.png` |
| 第五步：发布文案 | `page.json`、`analysis.json`、`script.txt`、`title.txt` | 整理不超过30字的抖音标题，并生成作品简介和相关话题 | `publish.json`、`publish_title.txt`、`publish_description.txt` |

## 环境要求

- Python 3.12
- 支持 `libass` 的 ffmpeg-full（`brew install ffmpeg-full`）
- Playwright Chromium（`playwright install chromium`）

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `LLM_API_KEY` | 是 | OpenAI 兼容 LLM 服务的 API Key |
| `ATHLETIC_COOKIES` | 是 | The Athletic 登录 Cookie（JSON 数组，从浏览器插件导出） |
| `LLM_BASE_URL` | 否 | 默认 `https://api.deepseek.com/v1` |
| `LLM_MODEL` | 否 | 默认 `deepseek-v4-flash` |
| `TTS_VOICE` | 否 | 默认 `zh-CN-YunjianNeural`（男声） |
| `TTS_RATE` | 否 | 语速，默认 `+10%`（约 1.1 倍） |
| `CJK_FONT_PATH` | 否 | 视频字幕和封面使用的中文字体文件 |
| `COVER_DATE_FONT_PATH` | 否 | 封面日期字体，macOS 默认优先使用 DIN Condensed Bold |

### 设置环境变量

```bash
export LLM_API_KEY="your_api_key"
export ATHLETIC_COOKIES='[{"name":"...","value":"...","domain":".nytimes.com",...}]'
```

Cookie 导出推荐使用 [Cookie-Editor](https://cookie-editor.com/) 浏览器插件，在 The Athletic 文章页面导出为 JSON 格式。

### 环境变量加载说明

- 配置只从进程环境变量读取，不支持 `.env` 文件；
- 脚本、定时任务、CI 等非交互 shell 不会自动加载 `~/.zshrc`，需要在命令前显式注入变量，例如 `LLM_API_KEY=... .venv/bin/python main.py ...`；
- `LLM_API_KEY` 缺失时会在构造 LLM 客户端时直接报错退出；`ATHLETIC_COOKIES` 缺失、为空数组或不是合法 JSON 时同样会在启动时直接报错退出。

## 环境预检

正式处理文章前，可以运行 `doctor` 一次性检查 Python、Cookie 配置、LLM 配置、TTS 配置、输出目录、磁盘空间、Playwright Chromium、FFmpeg/libass 和中文字体：

```bash
.venv/bin/python main.py doctor
```

指定其他输出目录进行写入权限和磁盘检查：

```bash
.venv/bin/python main.py doctor --output-dir "/path/to/output"
```

增加在线检查，实际验证 LLM API 和 Edge TTS 服务是否可连接：

```bash
.venv/bin/python main.py doctor --online
```

也可以提供一篇 The Athletic 文章，验证 Cookie 登录状态和完整正文抽取能力：

```bash
.venv/bin/python main.py doctor \
  --url "https://www.nytimes.com/athletic/ARTICLE_ID/..."
```

在线检查和文章检查可以同时使用。所有检查都会输出 `PASS`、`WARN` 或 `FAIL`；只要存在 `FAIL`，命令就以非零状态码退出，适合用于脚本、定时任务和 CI 的运行前检查。

## 快速使用

下面的命令会连续执行全部五步，生成视频、竖横封面和发布文案：

```bash
.venv/bin/python main.py run \
  --url "https://www.nytimes.com/athletic/ARTICLE_ID/..."
```

输出文件保存在 `output/YYYY-MM-DD/<article-slug>/`，其中日期是**运行当天的日期**，不是文章发布日期。完整流程和分步骤命令使用同一套 Pipeline Runner，并在输出目录写入 `manifest.json`，记录每个阶段的状态、耗时、输入输出哈希、运行配置和提示词版本。`run --skip-video` 等价于运行到 `generate-audio` 阶段后停止。

封面和发布文案也可以单独重新生成：

```bash
.venv/bin/python main.py cover \
  --dir "output/YYYY-MM-DD/<article-slug>"
```

封面生成默认读取 `title.txt`。第五步会继续使用同一标题，不会重新生成另一个标题：

```bash
.venv/bin/python main.py publish-copy \
  --dir "output/YYYY-MM-DD/<article-slug>"
```

### 断点续跑和阶段控制

建议通过 `--dir` 固定文章输出目录，这样即使跨天重试，也会继续使用同一个 `manifest.json`：

```bash
URL="https://www.nytimes.com/athletic/ARTICLE_ID/..."
OUT="output/YYYY-MM-DD/<article-slug>"

.venv/bin/python main.py run --url "$URL" --dir "$OUT" --resume
```

`--resume` 只跳过状态为 `completed`，且输入、输出文件哈希均未变化的阶段。输出缺失、文件被修改或上游输入发生变化时，对应阶段会自动重新执行。

可以限制执行范围：

```bash
# 从音频阶段开始，并运行到视频阶段
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from generate-audio --to video

# 只运行正文和素材解析
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --to extract
```

可以在断点续跑时强制重跑指定阶段；`--force` 可以重复使用：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --resume \
  --force generate-audio --force video
```

执行前查看计划而不修改文件：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --resume --dry-run
```

当前可用阶段名为：`extract`、`download-images`、`generate-audio`、`video`、`cover`、`publish-copy`。单独执行这些分步骤命令时也会更新同一个 `manifest.json`。

结构化 JSON 产物使用 Pydantic 数据契约并带有 `schema_version`。旧版数组格式的 `images.json`、`videos.json` 和 `image_captions.json` 仍可读取；`manifest.json` 会从 schema v1 自动迁移到 v2。所有 JSON 和关键文本产物均采用临时文件加原子替换的方式写入。

## 分步骤执行

### 第一步：解析内容并下载图片

先提取文章标题、主要文字、图片和视频清单，不执行 LLM、TTS 或视频合成：

```bash
.venv/bin/python main.py extract --url "https://www.nytimes.com/athletic/ARTICLE_ID/..."
```

默认输出到 `output/YYYY-MM-DD/<article-slug>/`，也可以通过 `--dir` 指定目录：

```text
page.json      # 完整结构化内容，包含图片原始图注、署名和封面候选
text.txt       # 清理后的主要文字
images.json    # 图片 URL、尺寸、alt、原始图注和署名
videos.json    # 视频、iframe 或 JSON-LD 视频清单
```

`page.json` 同时记录 `cover_image_index` 和 `cover_image_url`。解析器优先采用文章的 `og:image` 头图；如果页面没有可匹配的头图元数据，则根据图片与文章标题的页面距离选择最接近标题的图片。

图片解析会读取图片容器中的 `figcaption`、图片说明节点和内联署名节点。图片说明保存到 `caption`，摄影师、图片机构和版权来源保存到 `credit`，两者不会混在视频图注中。

接着从 `page.json` 下载并校验文章图片：

```bash
.venv/bin/python main.py download-images \
  --dir "output/YYYY-MM-DD/<article-slug>"
```

图片会保存到 `images/`，下载后的 `images.json` 会继续保留 `alt`、`caption`、`credit`，并增加本地路径、下载状态、失败原因和 `is_cover` 标记。视频资源只记录在 `videos.json`，当前流程不下载原视频。

如果某篇文章是在加入图片图注功能之前抓取的，旧的 `page.json` 或 `images.json` 可能只有部分图注。此时需要对原 URL 重新执行本步骤的 `extract` 和 `download-images`，再继续执行第二、三步。

### 第二步：分析正文并生成音频

从第一步生成的 `page.json` 和 `images.json` 读取正文及图片说明，依次执行 LLM 分析、图片图注翻译、播报稿生成和 TTS：

```bash
.venv/bin/python main.py generate-audio \
  --dir "output/YYYY-MM-DD/<article-slug>"
```

该步骤不处理图片、视频或 ffmpeg 合成，会生成：

```text
analysis.json        # LLM 结构化分析结果
image_captions.json  # 图片本地路径、原始英文说明和精简中文图注
title.txt            # 中文标题
script.txt           # 中文播报稿
audio.mp3            # TTS 音频
audio.vtt            # TTS 时间字幕
```

播报稿以约 3 分钟口播为目标，超长时会自动压缩重写，成品通常在 2 至 3 分钟之间。

图片图注规则：

- 优先使用第一步抓到的 `caption`，缺失时才使用图片 `alt`；
- 只翻译和精简已有图片说明，不根据图片内容自行编造说明；
- 去掉摄影师、图片机构、版权和来源信息；
- 以 `local_path` 作为图片与中文图注的稳定映射，下载失败的图片不会进入视频；
- 原图文件不会被修改，中文图注单独保存在 `image_captions.json`。

### 第三步：生成抖音竖屏视频

从已经下载的图片、音频和 `audio.vtt` 生成固定规格的视频：

```bash
.venv/bin/python main.py video \
  --dir "output/YYYY-MM-DD/<article-slug>"
```

当前视频流程固定为：

- 输出 `1080×1920`、`30fps` 的 `9:16` 竖屏视频。中间帧以 15fps 渲染，最终由 FFmpeg 统一编码为 30fps，日志中的 15fps 是中间帧渲染节奏，不是最终帧率；
- 图片保持比例，横向图片在纯黑画布上尽量铺满宽度并垂直居中；
- 图片按每张约 5 秒轮播，视频时长与 `audio.mp3` 对齐；
- 图片在每个轮播片段内从 `100%` 平滑放大到约 `108%`，横向图片左右平移，纵向图片上下平移；相邻图片使用约 `0.3 秒` 淡入淡出转场；
- 每张图片按本地路径读取自己的中文图注，图注随该图片一起出现和消失；
- 图注优先控制为一行，字号会在 `38px` 到 `26px` 之间自动缩小，必要时最多拆成两行；
- 中文图注根据图片初始显示范围计算一次布局，靠图片右边缘对齐；图片运动时图注保持固定字号、换行和位置，不跟随图片缩放；空间允许时显示在图片下方，否则叠加在图片右下角；
- 图片图注使用白色文字和半透明黑底，不显示摄影师、图片机构或版权署名；
- 图注文字按字体实际可见边界垂直居中在背景框内，保持上下内边距一致；
- 暂不处理视频素材、渐变、模糊背景或视频标题层；
- 使用 `audio.vtt` 生成 `subtitles.ass`，再由带 `libass` 的 FFmpeg 烧录黄色、黑色描边字幕；
- 字幕最多两行，并统一以画面 `y=1480` 为中心；单行会位于双行区域的垂直中间，直接与音频时间轴对齐；
- 渲染产生的 `frames/` 中间帧目录会在视频编码成功后自动删除；编码失败时保留用于排查，第五步 `publish-copy` 结束时也会兜底清理（见下文“清理中间产物”）。

如果系统中有多个 ffmpeg，可通过 `FFMPEG_BIN` 指定带 `ass` 和 `subtitles` 滤镜的可执行文件；中文字幕字体可通过 `CJK_FONT_PATH` 指定。

### 第四步：生成抖音封面

封面独立于视频生成，默认读取 `title.txt` 和第一步解析得到的封面候选，从 `images/` 生成 `1080×1920` 的竖版 `cover.png` 和 `1920×1080` 的横版 `cover-landscape.png`：

```bash
.venv/bin/python main.py cover \
  --dir "output/YYYY-MM-DD/<article-slug>"
```

可以指定主图和封面文案。下面的命令使用第 7 张图片生成 Bruno Guimarães 这篇新闻的封面：

```bash
.venv/bin/python main.py cover \
  --dir "output/2026-08-11/bruno-guimaraes-arsenal-transfer-story-background-brazil" \
  --image-index 6 \
  --title "阿森纳签下领袖吉马良斯" \
  --kicker "阿森纳转会 · 深度报道" \
  --subtitle "一笔重磅转会背后的故事" \
  --output cover-v1.png
```

可用参数：

- `--image-index`：覆盖第一步选定的封面背景图索引，从 `0` 开始；省略时使用解析阶段的候选图；
- `--title`：主标题，省略时读取 `title.txt`；
- `--kicker`：标题上方的小标签；
- `--subtitle`：标题下方的辅助说明，可省略；
- `--output`：竖版输出文件名，默认 `cover.png`；横版文件名自动在词干后加 `-landscape`，如 `cover-v1.png` 对应 `cover-v1-landscape.png`；
- `--orientation`：`both`（默认，同时生成竖版和横版）、`vertical`（仅竖版）或 `landscape`（仅横版）。

竖版封面（`1080×1920`）版式固定包含：

- 主图上方左侧的黄色栏目标签和右侧当前日期，与主图保持固定间距；
- 日期格式为 `YYYY.MM.DD`，默认使用黄色 DIN Condensed Bold，可通过 `COVER_DATE_FONT_PATH` 指定其他字体；
- 中部文章主图；
- 下方中文主标题和 `英超每日观察` 品牌文字。

横版封面（`1920×1080`）版式固定包含：

- 同一张主图全幅铺底，上下叠加渐变压暗保证文字可读；
- 顶部左侧栏目标签（上方带黄色装饰条）和右侧当前日期，与竖版样式一致；
- 底部左对齐中文主标题（首行白色、第二行黄色）和 `英超每日观察` 品牌文字。

封面标题读取 `title.txt`。该标题由第二步的 LLM 生成，限制为不超过30个汉字，并同时作为第五步的抖音作品标题。这样封面标题和发布页标题保持一致。

### 第五步：生成抖音发布内容

从文章正文分析、中文口播稿和第二步生成的标题整理抖音发布页需要填写的内容：

```bash
.venv/bin/python main.py publish-copy \
  --dir "output/YYYY-MM-DD/<article-slug>"
```

也可以使用兼容别名：

```bash
.venv/bin/python main.py publish \
  --dir "output/YYYY-MM-DD/<article-slug>"
```

第五步生成：

```text
publish.json              # 结构化发布内容
publish_title.txt         # 作品标题，可直接填写到“作品描述”顶部标题栏
publish_description.txt   # 作品简介和带 # 的话题，可直接粘贴到简介输入框
```

生成规则：

- 作品标题不超过30个汉字、数字或标点，兼顾吸引力和准确性；
- 标题不使用夸张、虚构或空洞的标题党表达；
- 作品标题与第四步封面标题共用 `title.txt`，保持完全一致；
- 作品简介概括文章核心事件、人物和看点；
- 简介末尾自动添加3至6个相关话题，例如 `#英超 #切尔西 #足球新闻`；
- 最终简介与话题合计不超过1000个字符，适合直接粘贴到抖音表单；
- `publish.json` 同时保留不带话题的 `description` 和带话题的 `description_with_hashtags`。

### 清理中间产物

视频渲染的 `frames/` 中间帧目录在编码成功后会自动删除；作为整个流程的最后一步，`publish-copy` 完成时也会兜底清理一次。如果渲染中断或失败后不再重试，可以手动清理：

```bash
.venv/bin/python main.py cleanup \
  --dir "output/YYYY-MM-DD/<article-slug>"
```

### 完整的逐步执行示例

```bash
URL="https://www.nytimes.com/athletic/ARTICLE_ID/..."
OUT="output/YYYY-MM-DD/<article-slug>"

# 第一步：解析正文、图片和视频清单
.venv/bin/python main.py extract --url "$URL" --dir "$OUT"
.venv/bin/python main.py download-images --dir "$OUT"

# 第二步：LLM 分析正文和图片图注，生成播报稿、TTS 和字幕
.venv/bin/python main.py generate-audio --dir "$OUT"

# 第三步：生成带逐图中文图注和口播字幕的抖音竖屏视频
.venv/bin/python main.py video --dir "$OUT"

# 第四步：生成独立封面
.venv/bin/python main.py cover --dir "$OUT"

# 第五步：生成抖音标题、作品简介和话题
.venv/bin/python main.py publish-copy --dir "$OUT"

# 可选：清理渲染中断或失败残留的中间帧
.venv/bin/python main.py cleanup --dir "$OUT"
```

## 输出示例

```
output/
└── 2026-08-11/
    └── liverpool-transfer-summer-window-analysis/
        ├── images/          # 从文章下载的图片
        ├── manifest.json    # 流程阶段状态、耗时和输入输出哈希
        ├── page.json        # 正文、图片原始图注、视频及封面候选
        ├── images.json      # 下载状态和图片原始元数据
        ├── videos.json      # 文章视频资源清单（不下载视频）
        ├── cover.json       # 封面主图候选（cover_image_index / cover_image_url）
        ├── analysis.json    # 正文的 LLM 分析结果
        ├── image_captions.json # 原始英文图注与精简中文图注映射
        ├── title.txt        # 中文短标题
        ├── script.txt       # 中文口播稿
        ├── audio.mp3        # TTS 生成的音频
        ├── audio.vtt        # 字幕文件
        ├── subtitles.ass    # FFmpeg/libass 使用的烧录字幕
        ├── cover.png        # 抖音竖版封面（1080×1920）
        ├── cover-landscape.png # 横版封面（1920×1080）
        ├── publish.json     # 抖音发布标题、简介和话题
        ├── publish_title.txt # 可直接填写的作品标题
        ├── publish_description.txt # 可直接粘贴的简介和话题
        └── <中文标题>.mp4   # 最终视频（1080×1920，9:16），文件名为第二步生成的中文标题
```

## 运行测试

```bash
.venv/bin/python -m pytest tests/ -q
```
