"""CLI entry point for base-auto-subtitle."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click

from subforge import __version__
from subforge.config import load_config
from subforge.models import Job
from subforge.orchestrator import process_all
from subforge.scanner import scan_paths


@click.command(context_settings={"max_content_width": 100})
@click.argument("inputs", nargs=-1, required=True, type=click.Path(exists=True))
@click.option(
    "--model",
    default=None,
    help="ASR model size: tiny/base/small/medium/large (default: medium)",
)
@click.option(
    "--source-lang",
    default=None,
    help="Source language code (default: ja)",
)
@click.option(
    "--target-lang",
    default=None,
    help="Target language code (default: zh)",
)
@click.option(
    "--concurrency",
    type=int,
    default=None,
    help="Max parallel files (default: 2)",
)
@click.option(
    "--llm-api-key",
    default=None,
    help="OpenAI API key (env: LLM_API_KEY)",
)
@click.option(
    "--llm-base-url",
    default=None,
    help="OpenAI API base URL (env: LLM_BASE_URL)",
)
@click.option(
    "--llm-model",
    default=None,
    help="LLM model name (env: LLM_MODEL)",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(path_type=Path),
    help="Path to config.toml (default: ~/.subforge/config.toml)",
)
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Output directory for SRT files (default: same as source)",
)
@click.version_option(version=__version__, prog_name="subforge")
def main(
    inputs: tuple[str, ...],
    model: str | None,
    source_lang: str | None,
    target_lang: str | None,
    concurrency: int | None,
    llm_api_key: str | None,
    llm_base_url: str | None,
    llm_model: str | None,
    config_path: Path | None,
    output_dir: Path | None,
) -> None:
    """Generate subtitles from audio/video files.

    INPUTS can be one or more files or directories. Supported formats:
    .mp3, .mp4, .wav, .m4a, .flac

    \b
    Pipeline: Scan → ASR (faster-whisper) → Timeline fix → LLM Translate → SRT

    \b
    Examples:
      base-auto-subtitle audio.mp3
      base-auto-subtitle *.mp3 --target-lang en --concurrency 4
      base-auto-subtitle ./downloads/ --model large --source-lang ja
    """

    # Collect CLI overrides (only non-None values)
    cli_overrides: dict = {}
    if model is not None:
        cli_overrides["model"] = model
    if source_lang is not None:
        cli_overrides["source_lang"] = source_lang
    if target_lang is not None:
        cli_overrides["target_lang"] = target_lang
    if concurrency is not None:
        cli_overrides["concurrency"] = concurrency
    if llm_api_key is not None:
        cli_overrides["llm_api_key"] = llm_api_key
    if llm_base_url is not None:
        cli_overrides["llm_base_url"] = llm_base_url
    if llm_model is not None:
        cli_overrides["llm_model"] = llm_model
    if output_dir is not None:
        cli_overrides["output_dir"] = output_dir

    # Load configuration
    config = load_config(config_path=config_path, cli_overrides=cli_overrides)

    # Scan input paths
    paths = [Path(p) for p in inputs]
    files = scan_paths(paths)

    if not files:
        print("Error: No supported media files found.", file=sys.stderr)
        sys.exit(1)

    # Create jobs
    jobs = [
        Job(
            file_path=f,
            source_lang=config.source_lang,
            target_lang=config.target_lang,
            model_size=config.model,
        )
        for f in files
    ]

    # Run pipeline
    try:
        result = asyncio.run(process_all(jobs, config))
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        sys.exit(130)

    if result["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
