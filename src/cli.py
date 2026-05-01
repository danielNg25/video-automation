"""CLI interface for the Douyin Video Repurposing Pipeline.

Uses Click for argument parsing and Rich for formatted output.
Entry point: `python -m src` or `douyin-repurpose` (if pip-installed).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _run_async(coro):
    """Run an async coroutine from synchronous Click commands."""
    return asyncio.run(coro)


def _load_config():
    """Load config with a user-friendly error on missing file."""
    from src.utils.config import load_config

    try:
        return load_config()
    except FileNotFoundError:
        console.print(
            "[red]Error:[/red] config/config.yaml not found. "
            "Copy config/config.example.yaml and edit it."
        )
        sys.exit(1)


@click.group()
@click.version_option(version="0.1.0", prog_name="douyin-repurpose")
def main():
    """Douyin Video Repurposing Pipeline"""


@main.command()
@click.argument("url")
@click.option("--platforms", "-p", default="youtube,tiktok", help="Comma-separated platforms")
@click.option("--subtitle-lang", default="zh", help="Source subtitle language")
@click.option("--translate", "translate_profile", default=None, help="Translation profile name")
@click.option("--tts", "tts_profile", default=None, help="TTS voice profile name")
@click.option("--title", default=None, help="Custom video title")
@click.option("--tags", default=None, help="Comma-separated tags")
@click.option("--privacy", default="private", type=click.Choice(["private", "public", "unlisted"]))
@click.option("--force", is_flag=True, help="Ignore duplicate detection")
def process(url, platforms, subtitle_lang, translate_profile, tts_profile, title, tags, privacy, force):
    """Process a single Douyin video URL through the full pipeline."""
    from src.pipeline import Pipeline

    config = _load_config()
    pipeline = Pipeline(config)

    platform_list = [p.strip() for p in platforms.split(",") if p.strip()]
    options = {
        "force": force,
        "subtitle_lang": subtitle_lang,
        "translate_profile": translate_profile,
        "tts_profile": tts_profile,
        "title": title,
        "tags": tags,
        "privacy": privacy,
    }

    stage_icons = {
        "download": "[cyan]↓[/cyan]",
        "transcribe": "[yellow]✎[/yellow]",
        "translate": "[magenta]🌐[/magenta]",
        "tts": "[green]♪[/green]",
        "process": "[blue]⚙[/blue]",
        "upload": "[green]↑[/green]",
        "skip": "[dim]⏭[/dim]",
    }
    stage_idx = {"download": 1, "transcribe": 2, "translate": 2, "tts": 3, "process": 3, "upload": 4}

    def on_progress(stage: str, progress: float, message: str):
        icon = stage_icons.get(stage, "")
        step = stage_idx.get(stage, "")
        if step:
            console.print(f"  {icon} [{step}/4] {message}")
        else:
            console.print(f"  {icon} {message}")

    console.print(f"\n[bold]Processing:[/bold] {url}")
    console.print(f"[dim]Platforms: {', '.join(platform_list)}[/dim]\n")

    result = _run_async(pipeline.process_single(url, platform_list, options, on_progress))

    status = result.get("status", "unknown")
    if status == "done":
        console.print(f"\n[bold green]Pipeline complete[/bold green] ✓")
        outputs = result.get("stage_results", {}).get("process", {}).get("outputs", {})
        for plat, path in outputs.items():
            console.print(f"  [dim]{plat}:[/dim] {path}")
    elif status == "skipped":
        console.print(f"\n[yellow]{result.get('message', 'Skipped')}[/yellow]")
    elif status == "failed":
        console.print(f"\n[bold red]Pipeline failed:[/bold red] {result.get('error', 'Unknown error')}")
        sys.exit(1)
    elif status == "interrupted":
        console.print("\n[yellow]Pipeline interrupted. Run same command to resume.[/yellow]")
        sys.exit(130)


@main.command()
@click.argument("url")
@click.option("--output-dir", default="data/raw", help="Output directory")
def download(url, output_dir):
    """Download a Douyin video."""
    from src.downloader import download_with_fallback

    config = _load_config()

    async def _download():
        return await download_with_fallback(url, Path(output_dir), config)

    console.print(f"Downloading: {url}")
    metadata = _run_async(_download())
    console.print(f"[green]Downloaded:[/green] {metadata.file_path}")
    console.print(f"  Title: {metadata.title}")
    console.print(f"  Video ID: {metadata.video_id}")


@main.command()
@click.argument("video_path")
@click.option("--lang", default="zh", help="Source language")
@click.option("--translate", "translate_profile", default=None, help="Translation profile")
@click.option("--model", default=None, help="Whisper model size")
def transcribe(video_path, lang, translate_profile, model):
    """Transcribe a local video file."""
    from src.transcriber import get_transcriber

    config = _load_config()

    console.print(f"Transcribing: {video_path}")

    ocr_config = config.get("ocr", {})
    transcriber = get_transcriber(ocr_config)

    segments = transcriber.transcribe(video_path, lang, "transcribe")

    video_id = Path(video_path).stem
    srt_dir = Path("data/srt")
    srt_dir.mkdir(parents=True, exist_ok=True)
    srt_path = srt_dir / f"{video_id}_{lang}.srt"
    transcriber.generate_srt(segments, srt_path)

    console.print(f"[green]Transcribed:[/green] {srt_path} ({len(segments)} segments)")


@main.command()
@click.argument("url_file")
@click.option("--platforms", "-p", default="youtube,tiktok", help="Comma-separated platforms")
@click.option("--concurrency", default=3, help="Max concurrent downloads")
@click.option("--subtitle-lang", default="zh", help="Source subtitle language")
@click.option("--translate", "translate_profile", default=None, help="Translation profile")
@click.option("--privacy", default="private", type=click.Choice(["private", "public", "unlisted"]))
@click.option("--force", is_flag=True, help="Ignore duplicate detection")
def batch(url_file, platforms, concurrency, subtitle_lang, translate_profile, privacy, force):
    """Process multiple URLs from a file."""
    from src.pipeline import Pipeline

    url_path = Path(url_file)
    if not url_path.exists():
        console.print(f"[red]Error:[/red] File not found: {url_file}")
        sys.exit(1)

    urls = [line.strip() for line in url_path.read_text().splitlines() if line.strip() and not line.startswith("#")]

    if not urls:
        console.print("[yellow]No URLs to process.[/yellow]")
        return

    config = _load_config()
    pipeline = Pipeline(config)
    platform_list = [p.strip() for p in platforms.split(",") if p.strip()]

    options = {
        "force": force,
        "concurrency": concurrency,
        "subtitle_lang": subtitle_lang,
        "translate_profile": translate_profile,
        "privacy": privacy,
    }

    console.print(f"\n[bold]Batch processing:[/bold] {len(urls)} URLs")
    console.print(f"[dim]Platforms: {', '.join(platform_list)} | Concurrency: {concurrency}[/dim]\n")

    def on_progress(stage: str, progress: float, message: str):
        console.print(f"  [dim]{message}[/dim]")

    results = _run_async(pipeline.process_batch(urls, platform_list, options, on_progress))

    # Summary
    succeeded = sum(1 for r in results if r.get("status") == "done")
    failed = sum(1 for r in results if r.get("status") == "failed")
    skipped = sum(1 for r in results if r.get("status") == "skipped")

    console.print(f"\n[bold]Batch complete:[/bold] {len(urls)} videos")
    console.print(f"  [green]Succeeded:[/green] {succeeded}")
    if failed:
        console.print(f"  [red]Failed:[/red] {failed}")
        for r in results:
            if r.get("status") == "failed":
                vid = r.get("video_id", r.get("url", "?"))
                console.print(f"    {vid}: {r.get('error', 'unknown')}")
    if skipped:
        console.print(f"  [yellow]Skipped:[/yellow] {skipped} (duplicates)")


@main.command()
@click.argument("video_id", required=False)
def status(video_id):
    """Show processing status."""
    from src.utils.state import PipelineState, get_all_states

    if video_id:
        state = PipelineState.load(video_id)
        if state.status == "pending" and not state.completed_stages:
            console.print(f"[yellow]No state found for video {video_id}[/yellow]")
            return

        console.print(f"\n[bold]Video:[/bold] {state.video_id}")
        console.print(f"  URL: {state.url}")
        console.print(f"  Status: {_status_color(state.status)}")
        console.print(f"  Platforms: {', '.join(state.platforms)}")
        console.print(f"  Completed stages: {', '.join(state.completed_stages)}")
        if state.error:
            console.print(f"  [red]Error:[/red] {state.error}")
        resume = state.get_resume_stage()
        if resume:
            console.print(f"  Resume from: {resume}")
        return

    # Show all recent states
    states = get_all_states()
    if not states:
        console.print("[dim]No pipeline runs found.[/dim]")
        return

    table = Table(title="Pipeline Status")
    table.add_column("Video ID", style="cyan")
    table.add_column("Status")
    table.add_column("Platforms")
    table.add_column("Stages")
    table.add_column("Updated")

    for s in states[:20]:
        vid = s.get("video_id", "?")
        status_str = _status_color(s.get("status", "unknown"))
        platforms_str = ", ".join(s.get("platforms", []))
        stages = ", ".join(s.get("completed_stages", []))
        updated = s.get("updated_at", "")[:19]  # Trim to seconds
        table.add_row(vid, status_str, platforms_str, stages, updated)

    console.print(table)


@main.command()
def server():
    """Start the web UI server."""
    import uvicorn

    from src.api import create_app

    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)


def _status_color(status: str) -> str:
    """Return a rich-formatted status string."""
    colors = {
        "done": "[green]done[/green]",
        "failed": "[red]failed[/red]",
        "pending": "[dim]pending[/dim]",
        "downloading": "[cyan]downloading[/cyan]",
        "transcribing": "[yellow]transcribing[/yellow]",
        "processing": "[blue]processing[/blue]",
        "uploading": "[magenta]uploading[/magenta]",
        "skipped": "[dim]skipped[/dim]",
        "interrupted": "[yellow]interrupted[/yellow]",
    }
    return colors.get(status, status)
