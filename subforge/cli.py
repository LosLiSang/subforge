"""CLI entry point for SubForge (built on Typer & Click)."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
import typer
from typer.core import TyperGroup

from subforge import __version__
from subforge.asr.model_manager import cached_models
from subforge.config import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
    DEFAULT_CONFIG_TOML,
    DEFAULT_JOBS_DIR,
    DEFAULT_MODELS_DIR,
    Config,
    load_config,
    setup_logging,
)
from subforge.events import EventType, ProcessingEvent
from subforge.models import Job
from subforge.orchestrator import process_all
from subforge.presets import ASMR_PRESET
from subforge.resume import ResumeStore, read_reusable_srt
from subforge.scanner import SUPPORTED_EXTENSIONS, scan_paths
from subforge.ui.checks import check_model_configuration, test_profile_connection
from subforge.ui.model_profiles import ModelProfileStore
from subforge.ui.settings import UiSettingsStore

logger = logging.getLogger(__name__)
console = Console()
err_console = Console(stderr=True)

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


def _format_size(size_bytes: int) -> str:
    """Format byte size into human readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _dir_size(path: Path) -> int:
    """Calculate total byte size of files within directory."""
    if not path.is_dir():
        return 0
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except OSError:
        pass
    return total


def _mask_key(key: str) -> str:
    """Mask sensitive API key strings for CLI display."""
    if not key:
        return "(unset)"
    if len(key) <= 8:
        return "****"
    return f"{key[:3]}...{key[-4:]}"


class RichProgressAdapter:
    """Render processing events as beautiful Rich progress bars."""

    def __init__(self, job_names: dict[str, str], progress: Progress) -> None:
        self.job_names = job_names
        self.progress = progress
        self.tasks: dict[str, int] = {}

    def __call__(self, event: ProcessingEvent) -> None:
        name = self.job_names.get(event.job_id, event.job_id)
        task_id = self.tasks.get(event.job_id)
        if task_id is None:
            task_id = self.progress.add_task(
                "[dim]Queued[/]",
                total=100,
                completed=0,
                filename=name,
            )
            self.tasks[event.job_id] = task_id

        if event.type == EventType.ASR_PREPARING:
            self.progress.update(
                task_id,
                description="[cyan]Preparing ASR model...[/]",
                completed=0,
                total=100,
            )
        elif event.type == EventType.ASR_STARTED:
            self.progress.update(
                task_id,
                description="[cyan]ASR transcribing[/]",
                completed=0,
                total=100,
            )
        elif event.type == EventType.ASR_PROGRESS:
            pct = int((event.progress or 0.0) * 100)
            self.progress.update(
                task_id,
                description="[cyan]ASR transcribing[/]",
                completed=pct,
                total=100,
            )
        elif event.type == EventType.ASR_COMPLETED:
            self.progress.update(
                task_id,
                description="[cyan]ASR done[/]",
                completed=100,
                total=100,
            )
        elif event.type == EventType.TRANSLATION_STARTED:
            total_batches = event.total or 1
            self.progress.update(
                task_id,
                description=f"[yellow]Translating (0/{total_batches} batches)[/]",
                completed=0,
                total=total_batches,
            )
        elif event.type == EventType.TRANSLATION_PROGRESS:
            c = event.completed or 0
            t = event.total or 1
            self.progress.update(
                task_id,
                description=f"[yellow]Translating ({c}/{t} batches)[/]",
                completed=c,
                total=t,
            )
        elif event.type == EventType.TRANSLATION_COMPLETED:
            t = event.total or 1
            self.progress.update(
                task_id,
                description="[green]Translation complete[/]",
                completed=t,
                total=t,
            )
        elif event.type == EventType.TASK_COMPLETED:
            self.progress.update(
                task_id,
                description="[bold green]✓ Done[/]",
            )
        elif event.type == EventType.TASK_NO_SPEECH:
            self.progress.update(
                task_id,
                description="[dim]No speech detected[/]",
                completed=100,
                total=100,
            )
        elif event.type == EventType.TASK_FAILED:
            self.progress.update(
                task_id,
                description=f"[bold red]✗ Failed ({event.message or 'error'})[/]",
            )


def _render_root_help() -> str:
    """Render a unified, beautiful Rich help screen for SubForge."""
    buf = io.StringIO()
    c = Console(file=buf, force_terminal=True, width=100)

    p_usage = Panel(
        "[bold cyan]subforge[/] [dim][OPTIONS][/] [bold green]<AUDIO_OR_DIR>...[/]\n"
        "[bold cyan]subforge[/] [bold yellow]<COMMAND>[/] [dim][ARGS]...[/]",
        title="Usage",
        title_align="left",
        border_style="blue",
    )

    t_cmds = Table(box=None, show_header=False, padding=(0, 2))
    t_cmds.add_column(style="bold cyan", width=12)
    t_cmds.add_column(style="white")
    t_cmds.add_row("ui", "Launch the local Library UI web server")
    t_cmds.add_row("status", "Show overview status of system, models, and jobs")
    t_cmds.add_row("check", "Run system and environment diagnostic checks (alias: doctor)")
    t_cmds.add_row("models", "Manage faster-whisper ASR models (list, download, check)")
    t_cmds.add_row("profiles", "Inspect and test configured model profiles")
    t_cmds.add_row("jobs", "Inspect and manage batch resume checkpoints")
    p_cmds = Panel(t_cmds, title="Commands", title_align="left", border_style="cyan")

    t_opts = Table(box=None, show_header=False, padding=(0, 2))
    t_opts.add_column(style="bold yellow", width=26)
    t_opts.add_column(style="white")
    t_opts.add_row("-m, --model TEXT", "ASR model size: tiny/base/small/medium/large-v3 (default: medium)")
    t_opts.add_row("--asr-provider TEXT", "ASR provider: local / deepgram / model (default: local)")
    t_opts.add_row("--deepgram-api-key TEXT", "Deepgram API key (env: DEEPGRAM_API_KEY)")
    t_opts.add_row("--deepgram-model TEXT", "Deepgram ASR model name (default: nova-3)")
    t_opts.add_row("--profile TEXT", "ModelProfile for translation (from ~/.subforge/model-profiles.json)")
    t_opts.add_row("--mode TEXT", "continue (default) / retranslate / force")
    t_opts.add_row("--retranslate-only", "Keep existing ja.srt, only re-translate Chinese")
    t_opts.add_row("--scene TEXT", "asmr (low vad, loudnorm, hallucination guard) / general")
    t_opts.add_row("--asmr", "Shortcut for --scene asmr")
    t_opts.add_row("--dry-run", "Preview processing plan without executing")
    t_opts.add_row("--force", "Shortcut for --mode force: ignore existing SRTs, re-ASR from scratch")
    t_opts.add_row("-h, --help", "Show this message and exit")
    p_opts = Panel(t_opts, title="Batch Processing Options (default command)", title_align="left", border_style="yellow")

    t_ex = (
        "  [cyan]# Translate audio with ASMR preset[/]\n"
        "  subforge audio.m4a --asmr\n\n"
        "  [cyan]# Batch process RJ package with GPU acceleration[/]\n"
        "  subforge ./RJ01499022/ --asmr --device auto --concurrency 2\n\n"
        "  [cyan]# Translate using Web ModelProfile[/]\n"
        "  subforge audio.m4a --profile DeepSeek\n\n"
        "  [cyan]# Keep Japanese subtitles and only re-translate Chinese[/]\n"
        "  subforge audio.mp3 --mode retranslate\n\n"
        "  [cyan]# Preview batch plan without consuming tokens[/]\n"
        "  subforge ./RJ01499022/ --dry-run"
    )
    p_ex = Panel(t_ex, title="Examples", title_align="left", border_style="green")

    c.print(p_usage)
    c.print(p_cmds)
    c.print(p_opts)
    c.print(p_ex)
    return buf.getvalue().rstrip("\n")


class SubForgeTyperGroup(TyperGroup):
    """Typer/Click group that forwards unhandled file arguments to 'process'."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if not args:
            super().parse_args(ctx, args)
            return args
        cmd_name = args[0]
        if cmd_name not in self.commands:
            if not cmd_name.startswith("-") or cmd_name not in ("--help", "-h", "--version", "-v"):
                args.insert(0, "process")
        super().parse_args(ctx, args)
        return args

    def format_help(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        formatter.write(_render_root_help() + "\n")


def _version_callback(value: bool) -> None:
    if value:
        print(f"subforge, version {__version__}")
        raise typer.Exit()


app = typer.Typer(
    cls=SubForgeTyperGroup,
    no_args_is_help=False,
    add_completion=False,
    context_settings=CONTEXT_SETTINGS,
    help="Local Japanese-to-Chinese subtitle workstation for doujin audio and ASMR.",
)


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Root Typer callback: displays unified Rich help if no command given."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        raise typer.Exit(0)


# ── Batch Processing (Default command) ──────────────────────────────────────


@app.command(
    "process",
    context_settings=CONTEXT_SETTINGS,
    help="Generate subtitles from audio/video files (default command)",
)
def process_cmd(
    inputs: list[Path] = typer.Argument(
        None,
        help="Input audio/video files or directories",
    ),
    model: str = typer.Option(
        None,
        "--model",
        "-m",
        help="ASR model size: tiny/base/small/medium/large-v3 (default: medium)",
    ),
    asr_provider: str = typer.Option(
        None,
        "--asr-provider",
        click_type=click.Choice(["local", "deepgram", "model"]),
        help="ASR provider: local / deepgram / model (default: local)",
    ),
    asr_profile: str = typer.Option(
        None,
        "--asr-profile",
        help="Model profile name/ID to use as audio ASR model (e.g. Gemini audio)",
    ),
    profile: str = typer.Option(
        None,
        "--profile",
        help="Use configured ModelProfile for LLM translation (from ~/.subforge/model-profiles.json)",
    ),
    mode: str = typer.Option(
        "continue",
        "--mode",
        click_type=click.Choice(["continue", "retranslate", "force"]),
        help="Processing mode: continue (resume), retranslate (reuse ja.srt, re-translate zh), force (re-ASR)",
    ),
    retranslate_only: bool = typer.Option(
        False,
        "--retranslate-only",
        help="Shortcut for --mode retranslate: keep existing ja.srt and only re-translate Chinese subtitles",
    ),
    scene: str = typer.Option(
        None,
        "--scene",
        click_type=click.Choice(["asmr", "general"]),
        help="Audio scene preset: asmr (low vad, loudnorm, hallucination guard) / general",
    ),
    asmr: bool = typer.Option(
        False,
        "--asmr",
        help="Apply ASMR-optimized VAD and Whisper parameters for whispered audio (shortcut for --scene asmr)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Ignore existing SRT files and saved resume state, then process from ASR (shortcut for --mode force)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Scan inputs and display planned actions without running processing",
    ),
    device: str = typer.Option(
        None,
        "--device",
        click_type=click.Choice(["cpu", "cuda", "auto"]),
        help="Compute device: cpu / cuda / auto (default: cpu)",
    ),
    compute_type: str = typer.Option(
        None,
        "--compute-type",
        click_type=click.Choice(["default", "auto", "float16", "int8_float16", "int8", "float32"]),
        help="Compute type: float16 is fastest on GPU, int8 best on CPU (default: default)",
    ),
    source_lang: str = typer.Option(
        None,
        "--source-lang",
        help="Source language code (default: ja)",
    ),
    target_lang: str = typer.Option(
        None,
        "--target-lang",
        help="Target language code (default: zh)",
    ),
    concurrency: int = typer.Option(
        None,
        "--concurrency",
        min=1,
        help="Max parallel files (default: 2)",
    ),
    llm_api_key: str = typer.Option(
        None,
        "--llm-api-key",
        help="OpenAI API key (env: LLM_API_KEY)",
    ),
    llm_base_url: str = typer.Option(
        None,
        "--llm-base-url",
        help="OpenAI API base URL (env: LLM_BASE_URL)",
    ),
    llm_model: str = typer.Option(
        None,
        "--llm-model",
        help="LLM model name (env: LLM_MODEL)",
    ),
    translation_prompt: str = typer.Option(
        None,
        "--prompt",
        "--translation-prompt",
        help="Additional translation prompt rules",
    ),
    batch_size: int = typer.Option(
        None,
        "--batch-size",
        min=1,
        help="Subtitle entries per LLM translation call (default: 20)",
    ),
    context_size: int = typer.Option(
        None,
        "--context-size",
        min=0,
        help="Context subtitle entries around translation batch (default: 10)",
    ),
    translate_workers: int = typer.Option(
        None,
        "--translate-workers",
        min=1,
        help="Max parallel LLM translation calls (default: 8)",
    ),
    deepgram_api_key: str = typer.Option(
        None,
        "--deepgram-api-key",
        help="Deepgram API key (env: DEEPGRAM_API_KEY)",
    ),
    deepgram_model: str = typer.Option(
        None,
        "--deepgram-model",
        help="Deepgram ASR model name (default: nova-3)",
    ),
    config_path: Path = typer.Option(
        None,
        "--config",
        help="Path to config.toml (default: ~/.subforge/config.toml)",
    ),
    output_dir: Path = typer.Option(
        None,
        "--output-dir",
        help="Output directory for SRT files (default: same as source)",
    ),
    log_level: str = typer.Option(
        None,
        "--log-level",
        click_type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
        help="Log level (default: INFO)",
    ),
) -> None:
    """Process audio/video files into bilingual subtitles."""
    if not inputs:
        raise click.UsageError("Missing argument 'INPUTS...' (or run: subforge ui)")

    # Resolve effective mode & scene
    effective_mode = mode
    if force:
        effective_mode = "force"
    elif retranslate_only:
        effective_mode = "retranslate"

    is_asmr = asmr or (scene == "asmr")

    # Collect CLI overrides
    cli_overrides: dict[str, Any] = {}

    # Inherit common settings from ui.json if present
    ui_settings = UiSettingsStore(DEFAULT_CONFIG_DIR / "ui.json")
    if ui_settings.path.is_file():
        proxy = ui_settings.get_proxy_url()
        if proxy:
            cli_overrides.setdefault("llm_proxy_url", proxy)
        models_d = ui_settings.get_models_dir()
        if models_d:
            cli_overrides.setdefault("models_dir", models_d)
        default_prompt = ui_settings.get_translation_prompt()
        if default_prompt:
            cli_overrides.setdefault("translation_prompt", default_prompt)
        deepgram_key = ui_settings.get_deepgram_api_key()
        if deepgram_key:
            cli_overrides.setdefault("deepgram_api_key", deepgram_key)
        workers = ui_settings.get_translate_workers()
        if workers:
            cli_overrides.setdefault("translate_workers", workers)

    # ASMR preset
    if is_asmr:
        cli_overrides.update(ASMR_PRESET)

    # Model Profile for translation
    profile_store = ModelProfileStore(DEFAULT_CONFIG_DIR / "model-profiles.json")
    if profile is not None:
        matched = None
        for p in profile_store._load():
            if p.profile_id == profile or p.name.lower() == profile.lower():
                matched = profile_store.resolve(p.profile_id)
                break
        if not matched:
            raise click.BadParameter(
                f"Profile '{profile}' not found in ~/.subforge/model-profiles.json",
                param_hint="--profile",
            )
        cli_overrides["llm_base_url"] = matched.base_url
        cli_overrides["llm_model"] = matched.model
        if matched.api_key:
            cli_overrides["llm_api_key"] = matched.api_key
        if matched.proxy_url:
            cli_overrides["llm_proxy_url"] = matched.proxy_url
        cli_overrides["llm_verify_tls"] = matched.verify_tls
        if matched.ca_bundle:
            cli_overrides["llm_ca_bundle"] = matched.ca_bundle
        if matched.translate_prompt:
            cli_overrides["translation_prompt"] = matched.translate_prompt

    # ASR Profile for audio models (e.g. Gemini)
    if asr_profile is not None:
        matched_asr = None
        for p in profile_store._load():
            if p.profile_id == asr_profile or p.name.lower() == asr_profile.lower():
                matched_asr = profile_store.resolve(p.profile_id)
                break
        if not matched_asr:
            raise click.BadParameter(
                f"ASR Profile '{asr_profile}' not found in ~/.subforge/model-profiles.json",
                param_hint="--asr-profile",
            )
        cli_overrides["asr_provider"] = "model"
        cli_overrides["asr_profile"] = asdict(matched_asr)
        cli_overrides["asr_chunk_seconds"] = matched_asr.max_request_seconds

    if model is not None:
        cli_overrides["model"] = model
        if ui_settings.path.is_file() and model in {"medium", "large-v3"}:
            direct_p = ui_settings.get_direct_model_path(model)
            if direct_p and (direct_p / "model.bin").is_file():
                cli_overrides["direct_model_path"] = direct_p

    if asr_provider is not None:
        cli_overrides["asr_provider"] = asr_provider
    if device is not None:
        cli_overrides["device"] = device
    if compute_type is not None:
        cli_overrides["compute_type"] = compute_type
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
    if translation_prompt is not None:
        cli_overrides["translation_prompt"] = translation_prompt
    if batch_size is not None:
        cli_overrides["batch_size"] = batch_size
    if context_size is not None:
        cli_overrides["context_size"] = context_size
    if translate_workers is not None:
        cli_overrides["translate_workers"] = translate_workers
    if deepgram_api_key is not None:
        cli_overrides["deepgram_api_key"] = deepgram_api_key
    if deepgram_model is not None:
        cli_overrides["deepgram_model"] = deepgram_model
    if output_dir is not None:
        cli_overrides["output_dir"] = output_dir
    if effective_mode == "force":
        cli_overrides["force"] = True
    if log_level is not None:
        cli_overrides["log_level"] = log_level

    # Load configuration
    try:
        config = load_config(config_path=config_path, cli_overrides=cli_overrides)
    except ValueError as exc:
        raise click.ClickException(f"Error: Invalid configuration: {exc}") from exc
    setup_logging(config)

    # Validate and scan input paths
    paths = [Path(p) for p in inputs]
    missing = [path for path in paths if not path.exists()]
    if missing:
        first_missing = missing[0]
        if first_missing.suffix.lower() not in SUPPORTED_EXTENSIONS and "/" not in str(first_missing) and "\\" not in str(first_missing):
            raise click.UsageError(
                f"No such command or media file '{first_missing.name}'.\n"
                f"Run 'subforge -h' to see available commands."
            )
        raise click.BadParameter(f"Path does not exist: {first_missing}", param_hint="INPUTS")
    files = scan_paths(paths)

    if not files:
        logger.error("No supported media files found.")
        sys.exit(1)

    resume_store = ResumeStore(config.jobs_dir)

    # Dry-run plan preview
    if dry_run:
        table = Table(
            title=f"Dry-run Plan ({len(files)} media files) [Mode: {effective_mode.upper()}]",
            box=box.ROUNDED,
            header_style="bold cyan",
        )
        table.add_column("#", justify="right", style="dim")
        table.add_column("Media File", style="bold")
        table.add_column("Planned Action", style="magenta")
        table.add_column("Outputs", style="dim")

        plan_stats = {"skip": 0, "translate_only": 0, "resume": 0, "full": 0}
        for idx, f in enumerate(files, 1):
            out_base = (config.output_dir or f.parent) / f.stem
            source_srt = out_base.with_name(f"{f.stem}.ja.srt")
            target_srt = out_base.with_name(f"{f.stem}.zh.srt")

            job = Job(
                file_path=f,
                source_lang=config.source_lang,
                target_lang=config.target_lang,
                model_size=config.model,
            )
            state = resume_store.load(job, config) if effective_mode != "force" else None

            if effective_mode == "force":
                status = "[bold red]FULL PIPELINE[/] (--force from ASR)"
                plan_stats["full"] += 1
            elif effective_mode == "retranslate":
                if source_srt.is_file() and source_srt.stat().st_size > 0:
                    status = "[bold yellow]RETRANSLATE ONLY[/] (reusing existing ja.srt)"
                    plan_stats["translate_only"] += 1
                else:
                    status = "[bold blue]FULL PIPELINE[/] (no ja.srt found)"
                    plan_stats["full"] += 1
            elif target_srt.is_file() and target_srt.stat().st_size > 0:
                status = "[green]SKIP[/] (target SRT exists)"
                plan_stats["skip"] += 1
            elif source_srt.is_file() and source_srt.stat().st_size > 0:
                status = "[yellow]TRANSLATE ONLY[/] (source SRT exists)"
                plan_stats["translate_only"] += 1
            elif state and state.asr.get("status") == "done":
                completed = len(state.translation.get("completed_batches", {}))
                total = state.translation.get("total_batches", 0)
                status = f"[cyan]RESUME TRANSLATE[/] ({completed}/{total} batches)"
                plan_stats["resume"] += 1
            else:
                status = "[bold blue]FULL PIPELINE[/] (ASR + Translation)"
                plan_stats["full"] += 1

            table.add_row(
                str(idx),
                f.name,
                status,
                f"{source_srt.name}, {target_srt.name}",
            )
        console.print(table)
        console.print(
            Panel(
                f"[bold]Summary:[/] {plan_stats['full']} full pipeline, "
                f"{plan_stats['translate_only']} translate-only, {plan_stats['resume']} resume, "
                f"{plan_stats['skip']} skip.",
                border_style="blue",
            )
        )
        return

    # If retranslate mode: clear existing target SRT & translation resume state
    if effective_mode == "retranslate":
        for f in files:
            target_srt = (config.output_dir or f.parent) / f"{f.stem}.zh.srt"
            if target_srt.is_file():
                try:
                    target_srt.unlink()
                except OSError:
                    pass
            job = Job(
                file_path=f,
                source_lang=config.source_lang,
                target_lang=config.target_lang,
                model_size=config.model,
            )
            state_p = resume_store.state_path(job, config)
            if state_p.is_file():
                try:
                    state_p.unlink()
                except OSError:
                    pass

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

    job_names = {job.id: job.file_path.name for job in jobs}
    start_time = time.monotonic()

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold white]{task.fields[filename]:<28}"),
        BarColumn(bar_width=20),
        TaskProgressColumn(),
        TextColumn("{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as rich_prog:
        adapter = RichProgressAdapter(job_names, rich_prog)
        try:
            result = asyncio.run(process_all(jobs, config, event_sink=adapter))
        except KeyboardInterrupt:
            logger.warning("Interrupted by user.")
            sys.exit(130)

    elapsed = time.monotonic() - start_time
    succeeded = result.get("succeeded", 0)
    failed = result.get("failed", 0)
    skipped = result.get("skipped", 0)

    console.print(
        Panel(
            f"[bold green]Batch Processing Completed[/] in {elapsed:.1f}s\n\n"
            f"• [green]Succeeded:[/] {succeeded}\n"
            f"• [red]Failed:[/]    {failed}\n"
            f"• [dim]Skipped:[/]   {skipped}",
            title="SubForge Execution Report",
            border_style="green" if failed == 0 else "red",
        )
    )
    if failed > 0:
        sys.exit(1)


# ── Local Library UI ────────────────────────────────────────────────────────


@app.command(
    "ui",
    context_settings=CONTEXT_SETTINGS,
    help="Launch the local Library UI web server",
)
def ui_cmd(
    host: str = typer.Option(None, "--host", help="Host to bind (default: 127.0.0.1)"),
    port: int = typer.Option(None, "--port", "-p", help="Port to listen on (default: 8765)"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open browser automatically"),
) -> None:
    """Launch the local Library UI web server."""
    from subforge.ui.server import run_ui

    kwargs: dict[str, Any] = {}
    if host is not None:
        kwargs["host"] = host
    if port is not None:
        kwargs["port"] = port
    if no_browser:
        kwargs["open_browser"] = False
    try:
        run_ui(**kwargs)
    except KeyboardInterrupt:
        console.print("\n[yellow]SubForge UI stopped.[/]")


# ── Status Overview ─────────────────────────────────────────────────────────


@app.command(
    "status",
    context_settings=CONTEXT_SETTINGS,
    help="Show system, models, profiles, and jobs status overview",
)
def status_cmd() -> None:
    """Show quick status overview of SubForge environment."""
    ui_settings = UiSettingsStore(DEFAULT_CONFIG_DIR / "ui.json")
    p_store = ModelProfileStore(DEFAULT_CONFIG_DIR / "model-profiles.json")
    profiles = p_store.list_public()
    p_names = [p.get("name") for p in profiles if p.get("name")]

    candidates = ["tiny", "base", "small", "medium", "large-v3"]
    cached = sorted(cached_models(DEFAULT_MODELS_DIR, candidates))

    jobs_count = len(list(DEFAULT_JOBS_DIR.glob("*.json"))) if DEFAULT_JOBS_DIR.is_dir() else 0

    cuda_devices = 0
    try:
        import ctranslate2

        cuda_devices = ctranslate2.get_cuda_device_count()
    except Exception:
        pass

    table = Table(box=box.SIMPLE_HEAVY, show_header=False)
    table.add_column("Component", style="bold cyan", width=22)
    table.add_column("Status / Details", style="white")

    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    accel = f"[green]CUDA GPU ({cuda_devices} device(s))[/]" if cuda_devices > 0 else "[blue]CPU mode[/]"
    table.add_row("Runtime", f"Python {py_ver} | {accel}")

    whisper_str = f"[green]{', '.join(cached)}[/]" if cached else "[dim]None cached[/]"
    table.add_row("Whisper Models", whisper_str)

    prof_str = f"[green]{', '.join(p_names[:4])}[/]" if p_names else "[dim]None configured[/]"
    if len(p_names) > 4:
        prof_str += f" (+{len(p_names) - 4} more)"
    table.add_row("Model Profiles", prof_str)

    table.add_row("Resume Checkpoints", f"[cyan]{jobs_count}[/] active in ~/.subforge/jobs")

    active_lib = ui_settings.get_active_library() if ui_settings.path.is_file() else None
    proxy = ui_settings.get_proxy_url() if ui_settings.path.is_file() else None
    table.add_row("Active Library", str(active_lib) if active_lib else "[dim](not set)[/]")
    table.add_row("HTTP Proxy", proxy if proxy else "[dim](not set)[/]")

    console.print(Panel(table, title="[bold]SubForge Status Overview[/]", border_style="cyan"))


# ── Models Management ───────────────────────────────────────────────────────

models_app = typer.Typer(
    help="Manage faster-whisper ASR models",
    add_completion=False,
    context_settings=CONTEXT_SETTINGS,
)
app.add_typer(models_app, name="models")
app.add_typer(models_app, name="model", hidden=True)


@models_app.command("list", context_settings=CONTEXT_SETTINGS, help="List faster-whisper models and their cache status")
def models_list(
    config_path: Path = typer.Option(
        None,
        "--config",
        help="Path to config.toml",
    ),
) -> None:
    """List candidate faster-whisper models and cache status."""
    config = load_config(config_path=config_path)
    models_dir = config.models_dir
    candidates = ["tiny", "base", "small", "medium", "large-v3"]
    cached = cached_models(models_dir, candidates)

    ui_settings = UiSettingsStore(DEFAULT_CONFIG_DIR / "ui.json")

    table = Table(
        title=f"Faster-Whisper Models ({models_dir})",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Model", style="bold")
    table.add_column("Status")
    table.add_column("Disk Size", justify="right")
    table.add_column("Location / Snapshot", style="dim")

    for m in candidates:
        direct = ui_settings.get_direct_model_path(m) if ui_settings.path.is_file() else None
        if direct and (direct / "model.bin").is_file():
            size = _format_size(_dir_size(direct))
            table.add_row(m, "[green]Direct[/]", size, str(direct))
        elif m in cached:
            m_dir = models_dir / f"models--Systran--faster-whisper-{m}"
            size = _format_size(_dir_size(m_dir))
            table.add_row(m, "[cyan]Cached[/]", size, str(m_dir))
        else:
            table.add_row(m, "[dim]Not cached[/]", "-", "-")

    console.print(table)


@models_app.command("download", context_settings=CONTEXT_SETTINGS, help="Pre-download a faster-whisper model for offline use")
def models_download(
    model_size: str = typer.Argument(
        ...,
        help="Model size: tiny, base, small, medium, large-v3",
    ),
    config_path: Path = typer.Option(
        None,
        "--config",
        help="Path to config.toml",
    ),
) -> None:
    """Download a faster-whisper model snapshot to the local models directory."""
    if model_size not in {"tiny", "base", "small", "medium", "large-v3"}:
        raise click.BadParameter(
            f"Model '{model_size}' must be one of: tiny, base, small, medium, large-v3",
            param_hint="MODEL_SIZE",
        )
    config = load_config(config_path=config_path)
    models_dir = config.models_dir
    console.print(f"Downloading faster-whisper model '[bold cyan]{model_size}[/]' to {models_dir}...")
    try:
        import faster_whisper

        target = faster_whisper.download_model(model_size, output_dir=str(models_dir))
        console.print(f"[bold green]✓ Model '{model_size}' downloaded successfully:[/] {target}")
    except Exception as exc:
        raise click.ClickException(f"Failed to download model '{model_size}': {exc}") from exc


@models_app.command("check", context_settings=CONTEXT_SETTINGS, help="Check status of a specific Whisper model")
def models_check(
    model_size: str = typer.Argument(
        ...,
        help="Model size: tiny, base, small, medium, large-v3",
    ),
    config_path: Path = typer.Option(
        None,
        "--config",
        help="Path to config.toml",
    ),
) -> None:
    """Check if model is ready locally or direct path is valid."""
    config = load_config(config_path=config_path)
    ui_settings = UiSettingsStore(DEFAULT_CONFIG_DIR / "ui.json")
    direct = ui_settings.get_direct_model_path(model_size) if (ui_settings.path.is_file() and model_size in {"medium", "large-v3"}) else None
    ok, msg = check_model_configuration(model_size, config.models_dir, direct)
    if ok:
        console.print(f"[green]✓ {msg}[/]")
    else:
        console.print(f"[yellow]! {msg}[/]")


@models_app.command("path", context_settings=CONTEXT_SETTINGS, help="Print the Whisper models cache directory")
def models_path(
    config_path: Path = typer.Option(
        None,
        "--config",
        help="Path to config.toml",
    ),
) -> None:
    """Print active models cache path."""
    config = load_config(config_path=config_path)
    console.print(str(config.models_dir))


# ── Model Profiles (Inspection & Connectivity Test) ─────────────────────────

profiles_app = typer.Typer(
    help="Inspect and test unified model profiles",
    add_completion=False,
    context_settings=CONTEXT_SETTINGS,
)
app.add_typer(profiles_app, name="profiles")
app.add_typer(profiles_app, name="profile", hidden=True)


@profiles_app.command("list", context_settings=CONTEXT_SETTINGS, help="List available model profiles")
def profiles_list() -> None:
    """List all unified model profiles."""
    store = ModelProfileStore(
        DEFAULT_CONFIG_DIR / "model-profiles.json",
        legacy_llm_path=DEFAULT_CONFIG_DIR / "llm-profiles.json",
        legacy_gemini_path=DEFAULT_CONFIG_DIR / "gemini-audio-profiles.json",
    )
    profiles = store.list_public()
    if not profiles:
        console.print(f"[dim]No model profiles configured yet ({DEFAULT_CONFIG_DIR / 'model-profiles.json'}).[/]")
        return

    table = Table(
        title="Available Model Profiles (Use with --profile <name>)",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Profile Name", style="bold white")
    table.add_column("Model", style="green")
    table.add_column("Capabilities")
    table.add_column("Protocol", style="dim")
    table.add_column("API Key Status")

    for p in profiles:
        caps_badges = []
        for cap in p.get("capabilities", []):
            if cap == "transcribe":
                caps_badges.append("[cyan]transcribe[/]")
            elif cap == "translate":
                caps_badges.append("[green]translate[/]")
            elif cap == "merge":
                caps_badges.append("[yellow]merge[/]")
        table.add_row(
            p.get("name", ""),
            p.get("model", ""),
            " ".join(caps_badges),
            p.get("protocol", ""),
            p.get("api_key_masked", "-"),
        )

    console.print(table)


@profiles_app.command("test", context_settings=CONTEXT_SETTINGS, help="Test network connectivity to a model profile")
def profiles_test(
    name_or_id: str = typer.Argument(
        ...,
        help="Profile name or ID",
    ),
) -> None:
    """Test connection to a profile endpoint."""
    store = ModelProfileStore(DEFAULT_CONFIG_DIR / "model-profiles.json")
    matched = next(
        (p for p in store._load() if p.profile_id == name_or_id or p.name.lower() == name_or_id.lower()),
        None,
    )
    if not matched:
        raise click.ClickException(f"Profile '{name_or_id}' not found.")
    resolved = store.resolve(matched.profile_id)
    console.print(f"Testing profile '[bold]{resolved.name}[/]' ({resolved.base_url}, model: {resolved.model})...")
    ok, msg = asyncio.run(test_profile_connection(resolved))
    if ok:
        console.print(f"[bold green]✓ {msg}[/]")
    else:
        console.print(f"[bold red]✗ {msg}[/]")
        sys.exit(1)


# ── Jobs Management (Batch Resume Checkpoints) ──────────────────────────────

jobs_app = typer.Typer(
    help="Inspect and manage resume checkpoint files",
    add_completion=False,
    context_settings=CONTEXT_SETTINGS,
)
app.add_typer(jobs_app, name="jobs")
app.add_typer(jobs_app, name="job", hidden=True)


@jobs_app.command("list", context_settings=CONTEXT_SETTINGS, help="List saved resume checkpoint files")
def jobs_list(
    config_path: Path = typer.Option(
        None,
        "--config",
        help="Path to config.toml",
    ),
) -> None:
    """List resume checkpoint files."""
    config = load_config(config_path=config_path)
    job_files = sorted(config.jobs_dir.glob("*.json"))
    if not job_files:
        console.print(f"[dim]No resume checkpoint files found in {config.jobs_dir}.[/]")
        return

    table = Table(
        title=f"Saved Checkpoints ({len(job_files)} files)",
        box=box.ROUNDED,
        header_style="bold cyan",
    )
    table.add_column("Job Key", style="dim")
    table.add_column("Media File", style="bold")
    table.add_column("ASR")
    table.add_column("Translation")
    table.add_column("Updated At", style="dim")

    for jf in job_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            key = data.get("job_key", jf.stem)[:10]
            media = Path(data.get("media", {}).get("path", "unknown")).name
            asr_st = data.get("asr", {}).get("status", "pending")
            tr = data.get("translation", {})
            completed = len(tr.get("completed_batches", {}))
            total = tr.get("total_batches", 0)
            tr_str = f"{completed}/{total} batches" if total else tr.get("status", "pending")
            updated = data.get("updated_at", "")[:19].replace("T", " ")
            status_color = "green" if asr_st == "done" else "yellow"
            table.add_row(key, media, Text(asr_st, style=status_color), tr_str, updated)
        except Exception:
            table.add_row(jf.stem[:10], "(corrupt)", "-", "-", "-")

    console.print(table)


@jobs_app.command("show", context_settings=CONTEXT_SETTINGS, help="Show details of a specific resume checkpoint")
def jobs_show(
    job_key: str = typer.Argument(
        ...,
        help="Job key or prefix",
    ),
    config_path: Path = typer.Option(
        None,
        "--config",
        help="Path to config.toml",
    ),
) -> None:
    """Print raw checkpoint JSON data."""
    config = load_config(config_path=config_path)
    matches = [f for f in config.jobs_dir.glob("*.json") if f.stem.startswith(job_key)]
    if not matches:
        raise click.ClickException(f"No job checkpoint found matching '{job_key}'")
    data = json.loads(matches[0].read_text(encoding="utf-8"))
    console.print(
        Panel(
            json.dumps(data, indent=2, ensure_ascii=False),
            title=f"Checkpoint: {matches[0].stem}",
            border_style="cyan",
        )
    )


@jobs_app.command("clear", context_settings=CONTEXT_SETTINGS, help="Remove resume checkpoint files")
def jobs_clear(
    clear_all: bool = typer.Option(
        False,
        "--all",
        help="Remove all checkpoint files",
    ),
    job_id: str = typer.Option(
        None,
        "--id",
        help="Remove checkpoint by job key or prefix",
    ),
    file_name: str = typer.Option(
        None,
        "--file",
        help="Remove checkpoints matching media file name",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Do not prompt for confirmation",
    ),
    config_path: Path = typer.Option(
        None,
        "--config",
        help="Path to config.toml",
    ),
) -> None:
    """Clear saved resume checkpoint files."""
    if not clear_all and not job_id and not file_name:
        raise click.UsageError(
            "Specify --all, --id <key>, or --file <name> to select checkpoints to remove."
        )
    config = load_config(config_path=config_path)
    to_delete = []
    for f in config.jobs_dir.glob("*.json"):
        if clear_all:
            to_delete.append(f)
        elif job_id and f.stem.startswith(job_id):
            to_delete.append(f)
        elif file_name:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if file_name.lower() in str(data.get("media", {}).get("path", "")).lower():
                    to_delete.append(f)
            except Exception:
                pass
    if not to_delete:
        console.print("[dim]No matching checkpoints found.[/]")
        return
    if not yes and not click.confirm(f"Remove {len(to_delete)} checkpoint file(s)?"):
        console.print("[dim]Aborted.[/]")
        return
    deleted = 0
    for f in to_delete:
        try:
            f.unlink()
            tmp = f.with_suffix(".json.tmp")
            if tmp.exists():
                tmp.unlink()
            deleted += 1
        except OSError as e:
            console.print(f"[yellow]Warning: failed to delete {f.name}: {e}[/]")
    console.print(f"[green]✓ Removed {deleted} checkpoint file(s).[/]")


# ── Diagnostic Doctor ───────────────────────────────────────────────────────


@app.command("check", context_settings=CONTEXT_SETTINGS, help="Run system and environment diagnostic checks")
def check_cmd(
    test_api: bool = typer.Option(
        True,
        "--test-api/--no-test-api",
        help="Test connection to configured LLM API (default: True)",
    ),
    config_path: Path = typer.Option(
        None,
        "--config",
        help="Path to config.toml",
    ),
) -> None:
    """Run system and environment diagnostic checks."""
    console.print(Panel("[bold]SubForge Environment & System Doctor[/]", border_style="cyan"))
    warnings = 0
    errors = 0

    # 1. Python version
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):
        console.print(f"  [green]✓[/] Python {py_ver}")
    else:
        console.print(f"  [bold red]✗[/] Python {py_ver} (>= 3.11 required)")
        errors += 1

    # 2. FFmpeg check
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        try:
            res = subprocess.run(
                [ffmpeg_bin, "-version"], capture_output=True, text=True, timeout=5
            )
            first_line = res.stdout.splitlines()[0] if res.stdout else "unknown version"
            console.print(f"  [green]✓[/] FFmpeg: {first_line} ({ffmpeg_bin})")
        except Exception:
            console.print(f"  [green]✓[/] FFmpeg found at {ffmpeg_bin}")
    else:
        console.print(
            "  [yellow]![/] FFmpeg not found in PATH. Audio loudness normalization (--asmr) "
            "and video audio extraction will not work."
        )
        warnings += 1

    # 3. GPU / CTranslate2 acceleration
    try:
        import ctranslate2

        cuda_devices = ctranslate2.get_cuda_device_count()
        if cuda_devices > 0:
            console.print(f"  [green]✓[/] CUDA GPU acceleration available ({cuda_devices} device(s) detected)")
        else:
            console.print("  [blue]ℹ[/] CUDA GPU not detected; running in CPU mode")
    except Exception as exc:
        console.print(f"  [yellow]![/] Could not inspect ctranslate2: {exc}")
        warnings += 1

    # 4. Storage paths
    config = load_config(config_path=config_path)
    for name, p in [
        ("Config dir", DEFAULT_CONFIG_DIR),
        ("Models dir", config.models_dir),
        ("Jobs dir", config.jobs_dir),
    ]:
        try:
            p.mkdir(parents=True, exist_ok=True)
            console.print(f"  [green]✓[/] {name}: {p} (writable)")
        except Exception as exc:
            console.print(f"  [bold red]✗[/] {name}: {p} ({exc})")
            errors += 1

    # 5. Cached models
    candidates = ["tiny", "base", "small", "medium", "large-v3"]
    cached = sorted(cached_models(config.models_dir, candidates))
    if cached:
        console.print(f"  [green]✓[/] Cached Whisper models: {', '.join(cached)}")
    else:
        console.print(
            "  [blue]ℹ[/] No Whisper models cached locally yet (download with: subforge models download <model>)"
        )

    # 6. LLM API connectivity
    if config.llm_api_key or config.llm_base_url:
        console.print(
            f"  [blue]ℹ[/] LLM Config: model={config.llm_model}, endpoint={config.llm_base_url}"
        )
        if test_api:
            if not config.llm_api_key:
                console.print(
                    "  [yellow]![/] LLM API key is not set (set LLM_API_KEY env or configure in config.toml)"
                )
                warnings += 1
            else:
                import httpx

                t0 = time.monotonic()
                try:
                    headers = {"Authorization": f"Bearer {config.llm_api_key}"}
                    resp = httpx.get(
                        f"{config.llm_base_url.rstrip('/')}/models",
                        headers=headers,
                        timeout=10,
                    )
                    dt = time.monotonic() - t0
                    if resp.status_code == 200:
                        console.print(f"  [green]✓[/] LLM API reachable ({dt:.2f}s, HTTP 200)")
                    elif resp.status_code in (401, 403):
                        console.print(
                            f"  [bold red]✗[/] LLM API authentication failed (HTTP {resp.status_code}): {resp.text[:100]}"
                        )
                        errors += 1
                    else:
                        console.print(f"  [yellow]![/] LLM API returned HTTP {resp.status_code} ({dt:.2f}s)")
                        warnings += 1
                except Exception as exc:
                    console.print(f"  [yellow]![/] LLM API test failed: {exc}")
                    warnings += 1
    else:
        console.print("  [yellow]![/] LLM API is not configured (translation will fail unless configured)")
        warnings += 1

    # Summary
    console.print("")
    if errors == 0 and warnings == 0:
        console.print("[bold green]✓ All diagnostic checks passed! SubForge is fully ready.[/]")
    elif errors == 0:
        console.print(f"[bold yellow]✓ Ready with {warnings} notice/warning(s).[/]")
    else:
        console.print(f"[bold red]✗ Found {errors} error(s) and {warnings} warning(s).[/]")


@app.command("doctor", context_settings=CONTEXT_SETTINGS, hidden=True, help="Alias for 'check'")
def doctor_cmd(
    test_api: bool = typer.Option(
        True,
        "--test-api/--no-test-api",
        help="Test connection to configured LLM API (default: True)",
    ),
    config_path: Path = typer.Option(
        None,
        "--config",
        help="Path to config.toml",
    ),
) -> None:
    """Doctor alias for check."""
    check_cmd(test_api=test_api, config_path=config_path)


# Expose main for pyproject.toml scripts and click CliRunner compatibility
main = typer.main.get_command(app)


if __name__ == "__main__":
    main()
