import argparse
import asyncio
import logging

from src.pipeline_definition import (
    PIPELINE_STEP_NAMES,
    run,
    run_content_audio_pipeline,
    run_pipeline_step,
)
from src.workflow import run_cleanup_only, run_doctor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a Douyin short video from a The Athletic article"
    )
    sub = parser.add_subparsers(dest="cmd")

    full = sub.add_parser("run", help="Full pipeline from URL")
    full.add_argument("--url", required=True, help="The Athletic article URL")
    full.add_argument(
        "--dir",
        default="",
        help="Output directory (defaults to output/date/article-slug)",
    )
    full.add_argument(
        "--skip-video",
        action="store_true",
        help="Stop after TTS, skip video assembly",
    )
    resume_group = full.add_mutually_exclusive_group()
    resume_group.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        help="Skip completed steps whose inputs and outputs are unchanged",
    )
    resume_group.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Run selected steps even when an existing manifest could skip them",
    )
    full.set_defaults(resume=None)
    full.add_argument(
        "--from",
        dest="from_step",
        choices=PIPELINE_STEP_NAMES,
        help="Start from this pipeline step",
    )
    full.add_argument(
        "--to",
        dest="to_step",
        choices=PIPELINE_STEP_NAMES,
        help="Stop after this pipeline step",
    )
    full.add_argument(
        "--force",
        dest="force_steps",
        action="append",
        choices=PIPELINE_STEP_NAMES,
        default=[],
        help="Force a pipeline step to run; may be repeated",
    )
    full.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which pipeline steps would run without changing files",
    )

    vid = sub.add_parser("video", help="Assemble video from existing output directory")
    vid.add_argument(
        "--dir",
        required=True,
        help="Output directory containing images.json, audio.mp3, and audio.vtt",
    )
    vid.add_argument(
        "--title",
        default="",
        help="Override title (reads title.txt if omitted)",
    )
    vid.add_argument("--force", action="store_true", help="Regenerate this stage")

    cover = sub.add_parser("cover", help="Generate a Douyin cover from existing images")
    cover.add_argument("--dir", required=True, help="Output directory containing images/")
    cover.add_argument("--title", default="", help="Cover title (reads title.txt if omitted)")
    cover.add_argument(
        "--image-index",
        type=int,
        default=None,
        help="Override the image index selected during extraction",
    )
    cover.add_argument("--kicker", default="英超新闻 · 深度报道", help="Small label above the title")
    cover.add_argument("--subtitle", default="", help="Optional supporting line below the title")
    cover.add_argument("--output", default="cover.png", help="Output filename inside --dir")
    cover.add_argument(
        "--orientation",
        choices=["both", "vertical", "landscape"],
        default="both",
        help="Generate vertical cover.png, landscape cover-landscape.png, or both",
    )
    cover.add_argument("--force", action="store_true", help="Regenerate this stage")

    publish = sub.add_parser(
        "publish-copy",
        aliases=["publish"],
        help="Generate Douyin title, description, and hashtags",
    )
    publish.add_argument("--dir", required=True, help="Directory containing article outputs")
    publish.add_argument("--force", action="store_true", help="Regenerate this stage")

    ext = sub.add_parser("extract", help="Extract article text, images, and videos")
    ext.add_argument("--url", required=True, help="The Athletic article URL")
    ext.add_argument(
        "--dir",
        default="",
        help="Output directory (defaults to output/date/article-slug)",
    )
    ext.add_argument("--force", action="store_true", help="Regenerate this stage")

    dl = sub.add_parser(
        "download-images",
        help="Download images from an extracted page manifest",
    )
    dl.add_argument("--dir", required=True, help="Directory containing page.json")
    dl.add_argument("--force", action="store_true", help="Regenerate this stage")

    content_commands = {
        "analyze-content": "Summarize the article for a short news video",
        "write-script": "Generate the final title and podcast script",
    }
    for command, help_text in content_commands.items():
        content = sub.add_parser(command, help=help_text)
        content.add_argument("--dir", required=True, help="Article output directory")
        content.add_argument("--force", action="store_true", help="Regenerate this stage")

    audio = sub.add_parser(
        "generate-audio",
        help="Generate image captions and podcast audio from existing content outputs",
    )
    audio.add_argument(
        "--dir",
        required=True,
        help="Directory containing images.json and script.txt",
    )
    audio.add_argument("--force", action="store_true", help="Regenerate this stage")

    clean = sub.add_parser(
        "cleanup",
        help="Remove leftover intermediate frames directory",
    )
    clean.add_argument("--dir", required=True, help="Output directory of the article")

    doctor = sub.add_parser(
        "doctor",
        help="Check configuration and runtime dependencies",
    )
    doctor.add_argument(
        "--output-dir",
        default="output",
        help="Output directory or parent path to check for write access and free space",
    )
    doctor.add_argument(
        "--online",
        action="store_true",
        help="Also verify live LLM and TTS connectivity",
    )
    doctor.add_argument(
        "--url",
        default="",
        help="Optionally verify authenticated extraction of a The Athletic article",
    )

    parser.add_argument("--url", help=argparse.SUPPRESS)
    parser.add_argument("--skip-video", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "video":
        asyncio.run(
            run_pipeline_step(
                "video",
                args.dir,
                video_title=args.title,
                force=args.force,
            )
        )
    elif args.cmd == "cover":
        asyncio.run(
            run_pipeline_step(
                "cover",
                args.dir,
                cover_title=args.title,
                cover_image_index=args.image_index,
                cover_kicker=args.kicker,
                cover_subtitle=args.subtitle,
                cover_output_name=args.output,
                cover_orientation=args.orientation,
                force=args.force,
            )
        )
    elif args.cmd in ("publish-copy", "publish"):
        asyncio.run(run_pipeline_step("publish-copy", args.dir, force=args.force))
    elif args.cmd == "cleanup":
        run_cleanup_only(args.dir)
    elif args.cmd == "doctor":
        passed = asyncio.run(
            run_doctor(
                output_dir=args.output_dir,
                online=args.online,
                article_url=args.url,
            )
        )
        if not passed:
            raise SystemExit(1)
    elif args.cmd == "extract":
        asyncio.run(
            run_pipeline_step(
                "extract",
                args.dir,
                article_url=args.url,
                force=args.force,
            )
        )
    elif args.cmd == "download-images":
        asyncio.run(run_pipeline_step("download-images", args.dir, force=args.force))
    elif args.cmd in {"analyze-content", "write-script"}:
        asyncio.run(run_pipeline_step(args.cmd, args.dir, force=args.force))
    elif args.cmd == "generate-audio":
        asyncio.run(run_content_audio_pipeline(args.dir, force=args.force))
    else:
        if not args.url:
            parser.print_help()
            return
        asyncio.run(
            run(
                args.url,
                skip_video=args.skip_video,
                output_dir=getattr(args, "dir", ""),
                resume=getattr(args, "resume", None),
                from_step=getattr(args, "from_step", None),
                to_step=getattr(args, "to_step", None),
                force_steps=set(getattr(args, "force_steps", [])),
                dry_run=getattr(args, "dry_run", False),
            )
        )
