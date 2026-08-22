# TApodcast

将 The Athletic 文章自动生成适合抖音发布的竖屏短视频（中文配音 + 图片轮播 + 字幕）。

## Agent 自动处理协议

本节是其他 Agent 处理文章时的**最高优先级操作协议**。后续章节用于解释每个命令和产物；如果只是要自动完成一篇文章，应先完整执行本节，而不是自行猜测步骤。

### 任务输入

必需输入：

- 一条完整的 The Athletic 文章 URL。

可选输入：

- 用户指定的输出目录；如果没有指定，使用 `output/<运行日期>/<article-slug>/`。
- 是否只生成内容和音频、不生成视频；只有用户明确要求时才使用 `--skip-video`。

开始前先固定变量，后续所有重试必须继续使用同一个 `OUT`：

```bash
URL="https://www.nytimes.com/athletic/ARTICLE_ID/article-slug/"
SLUG="${URL%/}"
SLUG="${SLUG##*/}"
OUT="output/$(date +%F)/$SLUG"
MODE="fresh"
SCOPE="full"
```

`MODE` 可取 `fresh`、`reused-page` 或 `reused-assets`；`SCOPE="full"` 表示完整生成视频、封面和发布文案，用户明确要求跳过视频时改为 `SCOPE="audio"`。如果 Agent 的多次 Shell 调用彼此隔离，每次调用都必须重新声明 `URL`、`OUT`、`MODE` 和 `SCOPE`，不能假设变量会自动保留。

### 完成定义

Agent 只有在满足以下条件后才能报告“处理完成”：

1. `manifest.json` 中本次要求执行的阶段全部为 `completed`。
2. `content-quality.json` 中 `passed` 为 `true`。
3. 正式的 `title.txt` 和 `script.txt` 均存在；`title-candidate.txt` 和 `script-candidate.txt` 不存在。
4. `audio.mp3`、`audio.vtt`、`image_captions.json` 均存在且非空。
5. 完整流程还必须生成：竖屏 MP4、`cover.png`、`cover-landscape.png`、`publish.json`、`publish_title.txt` 和 `publish_description.txt`。
6. MP4 必须为 `1080×1920`、`30fps`，并同时包含 H.264 视频流和 AAC 音频流。
7. `cover.png` 必须为 `1080×1920`，`cover-landscape.png` 必须为 `1920×1080`。
8. `publish.json` 中的标题必须与 `title.txt` 完全一致。
9. `frames/` 不应在成功完成后残留。

以下情况不能报告完成：

- 只运行了测试，没有运行真实文章；
- 页面提取失败，却把历史内容说成刚刚抓取的内容；
- 内容质量门禁失败；
- 只有候选稿，没有正式标题或正式稿件；
- TTS、视频、封面或发布文案仍有失败阶段。

### 标准自动执行顺序

#### 1. 检查仓库和环境

不要删除既有输出目录，不要修改与当前文章无关的文件，也不要自动提交、推送或合并 Git 代码。

```bash
git status --short --branch
.venv/bin/python main.py doctor
```

本地 `doctor` 存在 `FAIL` 时，先修复环境问题，不要启动正式流程。

#### 2. 检查在线服务和文章访问

```bash
.venv/bin/python main.py doctor --online --url "$URL"
```

处理规则：

- LLM 连接失败：停止处理并报告阻塞原因。
- TTS 出现连接重置或超时：可以重试一次在线检查；正式 TTS 阶段本身也会自动重试三次。
- 文章页面出现连接超时：重试一次；仍失败时按下文“历史抓取产物复用”处理。
- Cookie 失效、登录页或正文为空：不能继续使用当前抓取结果。

#### 3. 选择新运行或断点续跑

如果 `OUT/manifest.json` 不存在，运行完整流程：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT"
```

用户明确要求只处理到音频时：

```bash
SCOPE="audio"
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --skip-video
```

如果输出目录已经存在，先查看执行计划，再断点续跑：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --resume --dry-run
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --resume
```

必须使用 `--dir "$OUT"` 固定目录。不要因为跨天重试而创建另一个默认日期目录。

#### 4. 历史抓取产物复用

只有当在线文章访问连续失败时，才允许查找历史 `page.json`：

```bash
rg -l --fixed-strings "$URL" output -g 'page.json'
```

复用规则：

1. `page.json` 中的 `url` 必须与输入 URL 完全一致。
2. `main_text` 必须非空，并记录复用目录和原抓取日期。
3. 默认复制匹配的 `page.json` 到本次固定的 `OUT`，从 `download-images` 开始运行，避免覆盖历史目录。
4. 必须在最终报告中明确写明“文章本次未重新抓取，复用了历史抓取产物”。
5. 如果没有完全匹配的历史产物，停止并报告文章访问阻塞；禁止用搜索摘要、其他报道或模型记忆替代原文。

```bash
MATCH="/path/to/matched/page.json"
MODE="reused-page"
mkdir -p "$OUT"
cp "$MATCH" "$OUT/page.json"
TO_STEP="publish-copy"
if [ "$SCOPE" = "audio" ]; then TO_STEP="generate-audio"; fi
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from download-images --to "$TO_STEP"
```

如果 `download-images` 因图片 CDN 超时而失败，但同一历史目录中已经存在成功下载的 `images/`、`images.json` 和 `cover.json`，可以连同历史图片资产一起复用：

```bash
HIST_DIR="$(dirname "$MATCH")"
MODE="reused-assets"
mkdir -p "$OUT/images"
cp "$HIST_DIR/page.json" "$OUT/page.json"
cp "$HIST_DIR/images.json" "$OUT/images.json"
cp "$HIST_DIR/cover.json" "$OUT/cover.json"
cp -R "$HIST_DIR/images/." "$OUT/images/"
TO_STEP="publish-copy"
if [ "$SCOPE" = "audio" ]; then TO_STEP="generate-audio"; fi
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from analyze-content --to "$TO_STEP"
```

历史图片资产只能在以下检查通过后使用：`images.json` 至少有一条 `status=downloaded`，每条已下载记录的 `local_path` 都存在，并且图片可以被 Pillow 解码。

```bash
OUT="$OUT" .venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
from PIL import Image

out = Path(os.environ["OUT"])
manifest = json.loads((out / "images.json").read_text(encoding="utf-8"))
records = manifest if isinstance(manifest, list) else manifest.get("images", [])
downloaded = [record for record in records if record.get("status") == "downloaded"]
assert downloaded
for record in downloaded:
    path = out / record["local_path"]
    assert path.exists()
    with Image.open(path) as image:
        image.verify()
print("historical image assets are reusable:", len(downloaded))
PY
```

复制前应读取并校验历史文件：

```bash
URL="$URL" MATCH="$MATCH" .venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

page = json.loads(Path(os.environ["MATCH"]).read_text(encoding="utf-8"))
assert page.get("url") == os.environ["URL"]
assert str(page.get("main_text", "")).strip()
print("historical page is reusable")
PY
```

#### 5. 验收内容质量

读取 `content-quality.json`，不要只看命令退出码：

```bash
OUT="$OUT" MODE="$MODE" SCOPE="$SCOPE" .venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

out = Path(os.environ["OUT"])
mode = os.environ.get("MODE", "fresh")
scope = os.environ.get("SCOPE", "full")
manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
report = json.loads((out / "content-quality.json").read_text(encoding="utf-8"))
required = [
    "extract",
    "download-images",
    "analyze-content",
    "write-script",
    "review-content",
    "finalize-content",
    "generate-audio",
    "video",
    "cover",
    "publish-copy",
]
if mode in {"reused-page", "reused-assets"}:
    required.remove("extract")
if mode == "reused-assets":
    required.remove("download-images")
if scope == "audio":
    required = required[: required.index("generate-audio") + 1]
incomplete = {
    name: manifest.get("steps", {}).get(name, {}).get("status", "missing")
    for name in required
    if manifest.get("steps", {}).get(name, {}).get("status") != "completed"
}
print("stage statuses:", {
    name: manifest.get("steps", {}).get(name, {}).get("status", "missing")
    for name in required
})
print("passed:", report["passed"])
print("scores:", report["final_review"]["scores"])
print("revisions:", len(report["revisions"]))
for issue in report["final_review"]["issues"]:
    print(issue["severity"], issue["dimension"], issue["description"])
if incomplete or not report["passed"]:
    raise SystemExit(1)
PY
```

`warning` 可以保留，但必须在最终报告中列出。存在 `error`、`blocker` 或 `passed=false` 时，不得继续生成音频、视频和发布文案。

#### 6. 验收最终媒体和发布产物

仅当 `SCOPE="full"` 时执行本节；`SCOPE="audio"` 时以第五步的门禁、音频和字幕检查作为完成条件。

```bash
VIDEO="$(find "$OUT" -maxdepth 1 -type f -name '*.mp4' -print -quit)"
ffprobe -v error \
  -show_entries format=duration:stream=codec_name,width,height,r_frame_rate \
  -of json "$VIDEO"
```

检查封面尺寸和标题一致性：

```bash
OUT="$OUT" .venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
from PIL import Image

out = Path(os.environ["OUT"])
title = (out / "title.txt").read_text(encoding="utf-8").strip()
publish = json.loads((out / "publish.json").read_text(encoding="utf-8"))
assert publish["title"] == title
assert Image.open(out / "cover.png").size == (1080, 1920)
assert Image.open(out / "cover-landscape.png").size == (1920, 1080)
assert not (out / "frames").exists()
print("title:", title)
print("publish title matches: yes")
PY
```

### 失败恢复矩阵

| 失败位置 | Agent 应执行的动作 | 禁止行为 |
|----------|--------------------|----------|
| `doctor` 本地检查 | 修复缺失环境变量、Chromium、FFmpeg/libass 或字体 | 跳过预检直接运行 |
| 文章提取超时 | 重试一次；再查找 URL 完全匹配的历史 `page.json` | 把历史抓取说成新抓取，或用其他来源替代 |
| 图片 CDN 下载失败 | 优先重试；仍失败时验证并复用同一历史目录的 `images/`、`images.json` 和 `cover.json` | 使用缺失、损坏或 URL 不匹配的图片资产 |
| LLM JSON 结构变化 | 保存失败目录，补数据归一化和回归测试，从失败阶段重跑 | 手工篡改 JSON 后宣称流程正常 |
| 初次 `review-content` 未通过 | 正常继续执行 `finalize-content`，让系统自动修订和复审 | 绕过 `finalize-content` 直接生成 TTS |
| `finalize-content` 未通过 | 查看 `content-quality.json`、候选标题和候选稿；修复后强制重跑该阶段 | 把候选文件改名为正式文件 |
| TTS 连接重置 | 等待内置重试；仍失败时从 `generate-audio` 重跑 | 伪造空音频或跳过字幕 |
| 视频编码失败 | 保留 `frames/` 排查 FFmpeg、字体和字幕，修复后重跑 `video` | 删除唯一的故障现场后直接报告完成 |
| 封面或发布文案失败 | 单独重跑 `cover` 或 `publish-copy`；必要时加 `--force` | 只交付部分产物却报告完整成功 |

常用恢复命令：

```bash
# 强制重新审校和定稿
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --force review-content --force finalize-content

# 只重新生成音频
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from generate-audio --to generate-audio

# 只重新生成视频到发布文案
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from video --to publish-copy
```

### 真实运行暴露代码缺陷时

如果真实文章触发了代码缺陷，Agent 应按以下顺序处理：

1. 保留失败输出目录、`manifest.json` 和错误日志。
2. 找到根因，不要只针对当前文章手工修产物。
3. 增加能够复现真实响应形态的回归测试。
4. 先运行相关测试，再运行完整测试：`.venv/bin/python -m pytest tests/ -q`。
5. 从失败阶段重新运行同一篇文章并完成上述验收。
6. 在最终报告中区分“代码测试通过”和“真实文章流程通过”。
7. 除非用户明确要求，否则不要执行 `git commit`、`git push` 或合并分支。

### Agent 最终报告格式

最终回复至少包含：

```text
状态：成功 / 部分成功 / 阻塞
文章 URL：...
输出目录：...
执行范围：full / audio
文章来源：本次重新抓取 / 复用 YYYY-MM-DD 的历史 page.json / 同时复用历史图片资产
质量门禁：通过或失败；总分、事实准确度、完整度、修订次数
非阻断警告：逐条列出
最终产物：标题、音视频时长、视频规格、封面规格、发布文案
验证：manifest 阶段状态、测试结果（如果修改了代码）
未完成项：没有则写“无”
```

## 五步流程

```
文章 URL
  → 第一步：解析正文/图片/视频，保存原始图注并下载图片
  → 第二步：提取事实、生成初稿、审校并自动修订，再生成 TTS 配音与字幕
  → 第三步：图片和对应中文图注轮播，合成配音与字幕
  → 第四步：使用文章主图和中文标题生成抖音封面
  → 第五步：生成抖音发布标题、作品简介和话题
```

| 步骤 | 输入 | 主要处理 | 产物 |
|------|------|----------|------|
| 第一步：内容解析 | The Athletic 文章 URL | 提取主要文字、图片、原始图注和视频清单，分离图注与署名，确定封面主图并下载图片 | `page.json`、`text.txt`、`images/`、`images.json`、`videos.json`、`cover.json` |
| 第二步：内容质量 + TTS | `page.json`、`images.json` | 提取可追踪事实、生成初稿；低风险文章走本地静态门禁，高风险文章才调用 LLM 审校；仅事实错误或 critical 事实遗漏默认自动修订一轮；通过质量门禁后翻译图注并生成音频 | `analysis.json`、`script-draft.txt`、`content-review.json`、`content-quality.json`、`title.txt`、`script.txt`、`image_captions.json`、`audio.mp3`、`audio.vtt` |
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
| `LLM_MAX_REQUESTS_PER_ARTICLE` | 否 | 单篇文章最多实际访问 LLM 的逻辑请求数，默认 `12`；缓存命中不计入 |
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

建议通过 `--dir` 固定文章输出目录，这样即使跨天重试，也会继续使用同一个 `manifest.json`。当目录中已有 `manifest.json` 时，`run` 默认自动续跑；新目录则从第一个未完成阶段开始：

```bash
URL="https://www.nytimes.com/athletic/ARTICLE_ID/..."
OUT="output/YYYY-MM-DD/<article-slug>"

.venv/bin/python main.py run --url "$URL" --dir "$OUT"
```

`--resume` 仍可显式表达同样的行为；`--no-resume` 用于明确要求本次不跳过已完成阶段。无论哪种方式，只有状态为 `completed`，且输入、输出文件哈希、相关模型配置和提示词版本均未变化的阶段才会跳过。输出缺失、文件被修改、上游输入发生变化，或相关模型/提示词版本升级时，对应阶段会自动重新执行。

可以限制执行范围：

```bash
# 最终稿已存在时，只重新生成音频和视频
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from generate-audio --to video

# 从内容分析开始，运行到最终内容质量门禁
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from analyze-content --to finalize-content

# 只运行正文和素材解析
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --to extract
```

可以在断点续跑时强制重跑指定阶段；`--force` 可以重复使用：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --force generate-audio --force video
```

`--force` 只强制流水线阶段重新执行，不会关闭 `.llm-cache/`。如果模型、提示词版本和输入均未变化，LLM 阶段仍会复用已成功的缓存响应，避免同一请求再次产生 API 费用。

执行前查看计划而不修改文件：

```bash
.venv/bin/python main.py run --url "$URL" --dir "$OUT" --dry-run
```

当前可用阶段名为：`extract`、`download-images`、`analyze-content`、`write-script`、`review-content`、`finalize-content`、`generate-audio`、`video`、`cover`、`publish-copy`。单独执行这些分步骤命令时也会更新同一个 `manifest.json`。

结构化 JSON 产物使用 Pydantic 数据契约并带有 `schema_version`。旧版数组格式的 `images.json`、`videos.json` 和 `image_captions.json` 仍可读取；`manifest.json` 会从 schema v1/v2 自动迁移到 v3。所有 JSON 和关键文本产物均采用临时文件加原子替换的方式写入。

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

### 第二步：内容审校

先完成事实提取、初稿生成、原文审校和自动修订：

```bash
.venv/bin/python main.py run \
  --url "https://www.nytimes.com/athletic/ARTICLE_ID/..." \
  --dir "output/YYYY-MM-DD/<article-slug>" \
  --from analyze-content --to finalize-content
```

### 第三步：生成音频

`generate-audio` 是纯下游阶段，只读取已经通过质量门禁的 `script.txt` 和已下载的 `images.json`，不会重新执行文章分析、播报稿生成、内容审校或自动修订：

```bash
.venv/bin/python main.py generate-audio \
  --dir "output/YYYY-MM-DD/<article-slug>"
```

该步骤不处理视频或 ffmpeg 合成，会生成：

```text
image_captions.json    # 图片本地路径、原始英文说明和精简中文图注
audio.mp3              # TTS 音频
audio.vtt              # TTS 时间字幕
```

内容质量流程可以独立执行，方便只重跑有问题的阶段；这些命令默认复用未变化的阶段，强制重跑时加 `--force`：

```bash
.venv/bin/python main.py analyze-content --dir "$OUT" --force
.venv/bin/python main.py write-script --dir "$OUT"
.venv/bin/python main.py review-content --dir "$OUT"
.venv/bin/python main.py finalize-content --dir "$OUT"
```

`analysis.json` 中的 `source_facts` 为每条事实分配 `F001` 形式的编号，并保存中文事实、原文依据、类别和重要级别。流程会先用本地规则判断文章风险，但只检查原文/中文标题和 `importance=critical` 的核心事实，不再扫描整篇原文中的所有背景词。只有未确认的转会、合同、投资或所有权交易，以及涉及法律调查、纪律处罚、严重伤害或事故的核心内容才标记为高风险。已经确认的转会和金额、普通伤病、战术预测，以及仅出现在 supporting 事实或原文背景中的敏感词都走低风险静态门禁。低风险文章由本地事实覆盖、数字/金额、不确定性措辞和格式规则完成审校，不调用 LLM；高风险文章才调用 LLM，逐项检查所有 `critical` 事实，以及人物、俱乐部、数字、金额、日期、引语归属、因果关系和不确定性措辞。

`content-review.json` 会记录 `review_mode`（`static` 或 `llm`）、`risk_level`（`low` 或 `high`）和 `risk_reasons`，便于确认某篇文章是否实际消耗了审校调用。由 critical 事实触发的原因会包含对应的 `F001` 形式编号，方便直接定位误判来源。审校和重写请求会发送文章标题、URL、`source_facts`、精简分析摘要、标题、当前播报稿和审校报告，但不会重复发送完整原文；其中 `analysis.detail` 只作为前一步分析生成的上下文，不能替代带有 `evidence` 的 `source_facts`，也不能单独证明稿件中的新事实。完整原文仍保存在本地 `page.json`/`text.txt`，供流程追溯。

质量门禁要求事实准确度至少 90、完整度至少 85、结构/口语性/标题质量至少 80、总分至少 85，且不能存在 `error` 或 `blocker`。未通过时默认最多自动修订一轮，且只有事实准确度错误/阻断问题，或明确关联 `critical` 事实的完整度错误/阻断问题，才会触发 LLM 重写；纯格式、风格、标题吸引力或缺少事实清单的问题不会盲目重写，会保留报告供人工处理或重新运行上游分析。修订后如果原问题仅是本地规则可以确定验证的数字、金额或比例错误，流程会使用本地规则复核，不再重复调用 LLM；涉及事实覆盖、人物、因果、引语归属或不确定性语气等语义问题时，仍会调用 LLM 进行二次审校。修订预算会持久化到 `content-quality.json`，同一原文、分析、初稿和提示词版本重复执行 `finalize-content --force` 时会继承已用次数，不会再次获得一轮修订；只有这些输入或提示词版本变化时才会开始新的预算。修订后仍未通过则停止后续 TTS 和视频生成，保留 `content-quality.json`、`title-candidate.txt` 和 `script-candidate.txt` 供人工检查。最终 `title.txt` 和 `script.txt` 只在质量门禁通过后生成。

`content-quality.json` 中的 `max_revisions`、`revision_budget_used`、`revision_budget_remaining` 和 `revision_budget_exhausted` 会直接显示当前文章的累计质量修订预算状态。

每篇文章的 LLM 请求会记录到 `llm-usage.jsonl`，成功响应会缓存到 `.llm-cache/`。缓存 Key 包含模型、阶段、提示词版本和完整输入；缓存命中不会访问 API，也不计入 `LLM_MAX_REQUESTS_PER_ARTICLE`。`manifest.json.configuration.llm_max_requests` 保存本次运行采用的预算，`manifest.json.llm_usage` 会在每次 API 请求、缓存命中或预算拦截后实时汇总：

```json
{
  "configuration": {
    "llm_max_requests": "12"
  },
  "llm_usage": {
    "max_requests": 12,
    "api_requests": 5,
    "cache_hits": 2,
    "prompt_tokens": 12345,
    "completion_tokens": 2345,
    "total_tokens": 14690,
    "remaining_requests": 7,
    "budget_exhausted": false,
    "stopped_before_stage": null,
    "by_stage": {
      "analyze-content": {
        "api_requests": 1,
        "cache_hits": 0,
        "prompt_tokens": 3000,
        "completion_tokens": 800,
        "total_tokens": 3800
      }
    }
  }
}
```

预算按**未命中缓存的逻辑请求**计算。完成第 N 次实际请求后，`remaining_requests` 变为 `0`，`budget_exhausted` 变为 `true`；当后续阶段准备发起第 N+1 次未缓存请求时，流程会在访问 API 之前停止，该阶段在 `manifest.json.steps` 中标记为 `failed`，阶段名写入 `llm_usage.stopped_before_stage`。预算耗尽后，已经存在的缓存仍可命中，因为缓存读取发生在预算检查之前。

播报稿使用单一线性规则根据原文长度确定目标字数，不按文章长度分段或分桶：

```text
source_chars = len(page.json.main_text 去掉空白后的字符数)
target_chars = clamp(round(source_chars * 0.04 + 400), 500, 1000)
```

目标字数包含固定节目开头和结尾。`500` 和 `1000` 分别是安全下限和上限，避免短文信息不足或长文稿件失控；例如原文 `3,000` 字约生成 `520` 字，原文 `8,000` 字约生成 `720` 字，原文 `10,000` 字约生成 `800` 字。长度只作为播报稿生成时的一次性精炼目标，模型必须保留所有 `critical` 事实，不会为了凑字数扩写，也不会在生成后再次调用 LLM 压缩或扩充；稿件不会因长度略有偏差而阻断质量门禁，仍会由确定性规则检查固定节目开头、结尾、空稿和 Markdown 污染。

图片图注规则：

- 优先使用第一步抓到的 `caption`，缺失时才使用图片 `alt`；
- 只翻译和精简已有图片说明，不根据图片内容自行编造说明；
- 去掉摄影师、图片机构、版权和来源信息；
- 以 `local_path` 作为图片与中文图注的稳定映射，下载失败的图片不会进入视频；
- 原图文件不会被修改，中文图注单独保存在 `image_captions.json`。

### 第四步：生成抖音竖屏视频

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

### 第五步：生成抖音封面

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

### 第六步：生成抖音发布内容

从文章正文分析、中文口播稿和内容阶段生成的标题整理抖音发布页需要填写的内容。默认使用本地模板，不调用 LLM：

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

# 第二步：运行内容质量流程
.venv/bin/python main.py run --url "$URL" --dir "$OUT" \
  --from analyze-content --to finalize-content

# 第三步：只生成图片图注、TTS 音频和时间字幕
.venv/bin/python main.py generate-audio --dir "$OUT"

# 如需逐阶段排查，也可以替换内容质量命令：
# .venv/bin/python main.py analyze-content --dir "$OUT"
# .venv/bin/python main.py write-script --dir "$OUT"
# .venv/bin/python main.py review-content --dir "$OUT"
# .venv/bin/python main.py finalize-content --dir "$OUT"
# .venv/bin/python main.py generate-audio --dir "$OUT" --force

# 第四步：生成带逐图中文图注和口播字幕的抖音竖屏视频
.venv/bin/python main.py video --dir "$OUT"

# 第五步：生成独立封面
.venv/bin/python main.py cover --dir "$OUT"

# 第六步：本地生成抖音标题、作品简介和话题
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
        ├── manifest.json    # 阶段状态、运行配置、LLM 预算和实时汇总
        ├── llm-usage.jsonl  # 每次 LLM 请求、缓存命中、Token 和预算记录
        ├── .llm-cache/      # 当前文章的成功 LLM 响应缓存
        ├── page.json        # 正文、图片原始图注、视频及封面候选
        ├── images.json      # 下载状态和图片原始元数据
        ├── videos.json      # 文章视频资源清单（不下载视频）
        ├── cover.json       # 封面主图候选（cover_image_index / cover_image_url）
        ├── analysis.json    # 正文分析和带原文依据的事实清单
        ├── script-draft.txt # 第一版口播稿
        ├── content-review.json # 第一轮内容审校和评分
        ├── content-quality.json # 累计修订预算、修订历史及最终质量门禁结果
        ├── image_captions.json # 原始英文图注与精简中文图注映射
        ├── title.txt        # 中文短标题
        ├── script.txt       # 通过质量门禁的最终中文口播稿
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
