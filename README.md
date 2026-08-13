# TApodcast

将 The Athletic 文章自动生成适合抖音发布的竖屏短视频（中文配音 + 图片轮播 + 字幕）。

## 四步流程

```
文章 URL
  → 第一步：解析正文/图片/视频，保存原始图注并下载图片
  → 第二步：LLM 分析正文与图注，生成播报稿、TTS 配音与字幕
  → 第三步：图片和对应中文图注轮播，合成配音与字幕
  → 第四步：使用文章主图和中文标题生成抖音封面
```

| 步骤 | 输入 | 主要处理 | 产物 |
|------|------|----------|------|
| 第一步：内容解析 | The Athletic 文章 URL | 提取主要文字、图片、原始图注和视频清单，分离图注与署名，确定封面主图并下载图片 | `page.json`、`text.txt`、`images/`、`images.json`、`videos.json`、`cover.json` |
| 第二步：LLM + TTS | `page.json`、`images.json` | 分析正文，将英文图片说明翻译并精简为中文，生成中文播报稿、约三分钟配音和时间字幕 | `analysis.json`、`image_captions.json`、`title.txt`、`script.txt`、`audio.mp3`、`audio.vtt` |
| 第三步：视频合成 | `images/`、`image_captions.json`、`audio.mp3`、`audio.vtt` | 按图片路径匹配中文图注，生成图片轮播并烧录黄色口播字幕 | `subtitles.ass`、`<中文标题>.mp4` |
| 第四步：封面生成 | 封面主图和 `title.txt` | 生成带栏目标签、当前日期和中文标题的独立竖屏封面 | `cover.png` |

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

## 快速使用

下面的命令会连续执行第一至第三步，生成视频，但不会自动生成第四步的独立封面：

```bash
.venv/bin/python main.py run \
  --url "https://www.nytimes.com/athletic/ARTICLE_ID/..."
```

输出文件保存在 `output/YYYY-MM-DD/<article-slug>/`。视频完成后执行第四步：

```bash
.venv/bin/python main.py cover \
  --dir "output/YYYY-MM-DD/<article-slug>"
```

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

- 输出 `1080×1920`、`30fps` 的 `9:16` 竖屏视频；
- 图片保持比例，横向图片在纯黑画布上尽量铺满宽度并垂直居中；
- 图片按每张约 5 秒轮播，视频时长与 `audio.mp3` 对齐；
- 每张图片按本地路径读取自己的中文图注，图注随该图片一起出现和消失；
- 图注优先控制为一行，字号会在 `38px` 到 `26px` 之间自动缩小，必要时最多拆成两行；
- 中文图注按图片实际显示范围动态定位，靠图片右边缘对齐；空间允许时显示在图片下方，否则叠加在图片右下角；
- 图片图注使用白色文字和半透明黑底，不显示摄影师、图片机构或版权署名；
- 暂不处理视频素材、渐变、模糊背景或视频标题层；
- 使用 `audio.vtt` 生成 `subtitles.ass`，再由带 `libass` 的 FFmpeg 烧录黄色、黑色描边字幕；
- 字幕最多两行，并统一以画面 `y=1480` 为中心；单行会位于双行区域的垂直中间，直接与音频时间轴对齐。

如果系统中有多个 ffmpeg，可通过 `FFMPEG_BIN` 指定带 `ass` 和 `subtitles` 滤镜的可执行文件；中文字幕字体可通过 `CJK_FONT_PATH` 指定。

### 第四步：生成抖音封面

封面独立于视频生成，默认读取 `title.txt` 和第一步解析得到的封面候选，从 `images/` 生成 `1080×1920` 的 `cover.png`：

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
- `--output`：输出文件名，默认 `cover.png`。

当前封面版式固定包含：

- 左上角黄色栏目标签；
- 右上角自动生成的当前日期，格式为 `YYYY.MM.DD`；
- 日期默认使用黄色 DIN Condensed Bold，可通过 `COVER_DATE_FONT_PATH` 指定其他字体；
- 中部文章主图；
- 下方中文主标题和 `英超每日观察` 品牌文字。

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
```

## 输出示例

```
output/
└── 2026-08-11/
    └── liverpool-transfer-summer-window-analysis/
        ├── images/          # 从文章下载的图片
        ├── page.json        # 正文、图片原始图注、视频及封面候选
        ├── images.json      # 下载状态和图片原始元数据
        ├── videos.json      # 文章视频资源清单（不下载视频）
        ├── analysis.json    # 正文的 LLM 分析结果
        ├── image_captions.json # 原始英文图注与精简中文图注映射
        ├── title.txt        # 中文短标题
        ├── script.txt       # 中文口播稿
        ├── audio.mp3        # TTS 生成的音频
        ├── audio.vtt        # 字幕文件
        ├── subtitles.ass    # FFmpeg/libass 使用的烧录字幕
        ├── cover.png        # 抖音封面
        └── video.mp4        # 最终视频（1080×1920，9:16）
```

## 运行测试

```bash
.venv/bin/python -m pytest tests/ -q
```
