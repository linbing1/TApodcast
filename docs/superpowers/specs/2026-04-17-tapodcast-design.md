# TApodcast 设计文档

日期：2026-04-17

## 概述

TApodcast 是一个独立的命令行工具，给定一篇 The Athletic 文章 URL，自动生成一个竖屏中文短视频，供手动上传至抖音。

**输入**：一篇文章的 URL
**输出**：`output/{date}/{article_slug}/video.mp4`

## Pipeline 流程

```
--url <文章链接>
      ↓
[1] Scraper        — Playwright 抓取文章全文 + 所有图片，下载图片到本地
      ↓
[2] Analyzer       — LLM 深度中文分析（复用 TAnews analyzer 逻辑和 prompt）
      ↓
[3] ScriptWriter   — LLM 将中文分析改写为口语化播报脚本（约 200-250 汉字）
      ↓
[4] TTSGenerator   — edge-tts 生成中文语音 MP3 及字幕时间戳
      ↓
[5] VideoAssembler — ffmpeg 合成：图片轮播 + 音频 + 烧录字幕
      ↓
output/{date}/{article_slug}/video.mp4
```

## 项目结构

```
main.py              # 入口；接受 --url 参数；串联 5 步
src/
  config.py          # 加载环境变量
  models.py          # Article、AnalyzedArticle、PodcastScript dataclass
  scraper.py         # Playwright 抓取文章全文 + 所有图片并下载
  analyzer.py        # LLM 深度中文分析（与 TAnews analyzer 逻辑一致）
  script_writer.py   # LLM 将分析内容改写为口语播报脚本
  tts_generator.py   # edge-tts 生成 MP3 + WebVTT，转换为 SRT
  video_assembler.py # ffmpeg 合成图片轮播 + 音频 + 字幕
output/{date}/{article_slug}/
  images/            # 下载的图片文件
  analyzed.json      # 中文分析结果
  script.json        # 口语播报脚本
  audio.mp3          # TTS 音频
  audio.srt          # 字幕文件
  video.mp4          # 最终视频
```

## 各组件详情

### Scraper
- 使用 Playwright，复用 `ATHLETIC_COOKIES`
- 提取文章全文（与 TAnews scraper 选择器逻辑一致）
- 提取页面所有 `<img>` 元素，过滤小图标（最小尺寸 300px）
- 通过 httpx 下载图片到 `output/{date}/{article_slug}/images/`
- **若图片数为 0：报错退出**（没有图片不生成视频）

### Analyzer
- 与 TAnews `analyzer.py` 使用相同的 LLM prompt 和输出结构
- 输出字段：`title_cn`、`overview`、`detail`、`impact`、`key_people_and_data`
- 保存至 `output/{date}/{article_slug}/analyzed.json`

### ScriptWriter
- 输入：Analyzer 输出的所有字段
- LLM 改写为自然口语中文，约 200-250 汉字（按 3 字/秒约 70-80 秒）
- 固定开头："今天的英超快报——"
- 固定结尾："更多内容关注每日英超快报"
- 保存至 `output/{date}/{article_slug}/script.json`

### TTSGenerator
- 库：`edge-tts`（免费，无需 API key）
- 默认发音人：`zh-CN-XiaoxiaoNeural`（可通过 `TTS_VOICE` 配置）
- 输出：`audio.mp3` + WebVTT 时间戳，转换为 `audio.srt`

### VideoAssembler
- 工具：`ffmpeg`（系统依赖）
- 分辨率：1080×1920（9:16 竖屏，适配抖音）
- 每张图片展示时长：`音频总时长 / 图片数量`
- 图片切换：淡入淡出（0.5 秒）
- 字幕：从 SRT 烧录进视频（白色文字 + 黑色描边，底部居中）
- 输出：H.264 MP4

## 错误处理

- 任意步骤失败 → 退出并打印错误，保留已生成的中间文件供排查
- 若图片数为 0 → 第一步即退出，不继续后续步骤

## 环境变量

| 变量 | 必填 | 默认值 | 用途 |
|------|------|--------|------|
| `ATHLETIC_COOKIES` | 是 | - | 与 TAnews 相同的 cookie 格式 |
| `LLM_API_KEY` | 是 | - | Analyzer 和 ScriptWriter 使用 |
| `LLM_BASE_URL` | 否 | `https://open.bigmodel.cn/api/coding/paas/v4` | LLM 接口地址 |
| `LLM_MODEL` | 否 | `deepseek-chat` | 模型名称 |
| `TTS_VOICE` | 否 | `zh-CN-XiaoxiaoNeural` | edge-tts 发音人 |

## 依赖

```
edge-tts>=6.1,<7       # 免费 TTS
httpx>=0.27,<1         # 图片下载
playwright>=1.49,<2    # 文章抓取
ffmpeg                 # 系统依赖（非 pip）
pytest>=8.0,<9
pytest-asyncio>=0.24,<1
```

## 运行方式

```bash
python main.py --url https://www.nytimes.com/athletic/7202716/2026/04/17/mikel-arteta-arsenal-pressure-title-manchester-city/
```

## 触发与视频存储

手动本地运行，视频保存在 `output/{date}/{article_slug}/video.mp4`，从此目录手动上传至抖音。

## 范围边界（不包含）

- 抖音自动上传
- 批量处理多篇文章
- 背景音乐
