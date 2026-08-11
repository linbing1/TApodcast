# TApodcast

将 The Athletic 文章自动生成适合抖音发布的竖屏短视频（中文配音 + 图片轮播 + 字幕）。

## 流程

```
文章 URL → 抓取正文 & 图片 → LLM 分析 → 生成播报脚本 → TTS 配音 → ffmpeg 合成视频
```

## 环境要求

- Python 3.12
- ffmpeg（`brew install ffmpeg`）
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
| `LLM_API_KEY` | 是 | 智谱 GLM API Key |
| `ATHLETIC_COOKIES` | 是 | The Athletic 登录 Cookie（JSON 数组，从浏览器插件导出） |
| `LLM_BASE_URL` | 否 | 默认 `https://open.bigmodel.cn/api/coding/paas/v4` |
| `LLM_MODEL` | 否 | 默认 `glm-4.7` |
| `TTS_VOICE` | 否 | 默认 `zh-CN-YunjianNeural`（男声） |
| `TTS_RATE` | 否 | 语速，默认 `+40%` |

### 设置环境变量

```bash
export LLM_API_KEY="your_api_key"
export ATHLETIC_COOKIES='[{"name":"...","value":"...","domain":".nytimes.com",...}]'
```

Cookie 导出推荐使用 [Cookie-Editor](https://cookie-editor.com/) 浏览器插件，在 The Athletic 文章页面导出为 JSON 格式。

## 使用

```bash
.venv/bin/python main.py --url "https://www.nytimes.com/athletic/ARTICLE_ID/..."
```

输出文件保存在 `output/YYYY-MM-DD/<article-slug>/video.mp4`。

## 输出示例

```
output/
└── 2026-04-18/
    └── liverpool-transfer-summer-window-analysis/
        ├── images/          # 从文章下载的图片
        ├── audio.mp3        # TTS 生成的音频
        ├── audio.vtt        # 字幕文件
        ├── concat.txt       # ffmpeg 图片序列
        └── video.mp4        # 最终视频（1080×1920，约 2 分钟）
```

## 运行测试

```bash
.venv/bin/python -m pytest tests/ -q
```
