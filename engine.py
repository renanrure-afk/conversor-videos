"""Motor de descoberta e conversão em massa de vídeos com foco em eficiência."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


VIDEO_EXTENSIONS: tuple[str, ...] = (
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".wmv",
    ".flv",
    ".m4v",
    ".ts",
    ".mts",
    ".mpg",
    ".mpeg",
    ".3gp",
)

TEMP_SUFFIX = ".converting.mp4"


@dataclass(frozen=True)
class ConversionProfile:
    """Define um perfil de conversão otimizado para eficiência em MP4."""

    id: str
    name: str
    description: str
    video_args: tuple[str, ...]
    audio_args: tuple[str, ...]
    requires_encoder: str
    fallback_video_args: Optional[tuple[str, ...]] = None


PROFILES: tuple[ConversionProfile, ...] = (
    ConversionProfile(
        id="hevc_balanced",
        name="MP4 • H.265 (HEVC) — Equilíbrio Ideal (Recomendado)",
        description="Reduz 40% a 65% do peso mantendo qualidade visual praticamente idêntica ao original.",
        video_args=("-c:v", "libx265", "-crf", "24", "-preset", "medium", "-tag:v", "hvc1"),
        audio_args=("-c:a", "aac", "-b:a", "128k"),
        requires_encoder="libx265",
    ),
    ConversionProfile(
        id="hevc_hq",
        name="MP4 • H.265 (HEVC) — Alta Qualidade Visual",
        description="Preserva fidelidade máxima de detalhes com excelente redução de tamanho em vídeos grandes.",
        video_args=("-c:v", "libx265", "-crf", "20", "-preset", "medium", "-tag:v", "hvc1"),
        audio_args=("-c:a", "aac", "-b:a", "160k"),
        requires_encoder="libx265",
    ),
    ConversionProfile(
        id="hevc_compact",
        name="MP4 • H.265 (HEVC) — Máxima Economia de Espaço",
        description="Compressão agressiva para deixar arquivos pesados muito leves mantendo boa nitidez.",
        video_args=("-c:v", "libx265", "-crf", "28", "-preset", "medium", "-tag:v", "hvc1"),
        audio_args=("-c:a", "aac", "-b:a", "96k"),
        requires_encoder="libx265",
    ),
    ConversionProfile(
        id="h264_balanced",
        name="MP4 • H.264 (AVC) — Eficiência & Compatibilidade Universal",
        description="Roda em 100% dos dispositivos, TVs, editores e navegadores com ótima redução de tamanho.",
        video_args=("-c:v", "libx264", "-crf", "23", "-preset", "slow", "-profile:v", "high"),
        audio_args=("-c:a", "aac", "-b:a", "128k"),
        requires_encoder="libx264",
    ),
    ConversionProfile(
        id="h264_light",
        name="MP4 • H.264 (AVC) — Super Leve (Web / WhatsApp)",
        description="Focado em compartilhamento rápido e arquivos bem menores com compatibilidade total.",
        video_args=("-c:v", "libx264", "-crf", "26", "-preset", "medium", "-profile:v", "main"),
        audio_args=("-c:a", "aac", "-b:a", "112k"),
        requires_encoder="libx264",
    ),
    ConversionProfile(
        id="av1_efficient",
        name="MP4 • AV1 (AOM-AV1) — Eficiência de Última Geração",
        description="Codec moderno de altíssima eficiência de compressão para máxima economia com qualidade.",
        video_args=("-c:v", "libaom-av1", "-crf", "30", "-cpu-used", "6", "-row-mt", "1"),
        audio_args=("-c:a", "aac", "-b:a", "128k"),
        requires_encoder="libaom-av1",
    ),
    ConversionProfile(
        id="qsv_hevc_fast",
        name="MP4 • H.265 Rápido (GPU Intel QuickSync)",
        description="Usa a placa gráfica Intel para converter em alta velocidade (com fallback para CPU se necessário).",
        video_args=("-c:v", "hevc_qsv", "-global_quality", "25", "-preset", "medium", "-tag:v", "hvc1"),
        audio_args=("-c:a", "aac", "-b:a", "128k"),
        requires_encoder="hevc_qsv",
        fallback_video_args=("-c:v", "libx265", "-crf", "24", "-preset", "fast", "-tag:v", "hvc1"),
    ),
)

PROFILE_BY_ID: dict[str, ConversionProfile] = {p.id: p for p in PROFILES}

RESOLUTION_OPTIONS: tuple[tuple[str, str], ...] = (
    ("original", "Manter Resolução Original"),
    ("1080p", "Limitar a Full HD (1080p)"),
    ("720p", "Limitar a HD (720p)"),
)


@dataclass
class VideoItem:
    """Representa um arquivo de vídeo descoberto para conversão em lote."""

    source_path: Path
    relative_path: Path
    size_bytes: int
    duration_seconds: float = 0.0
    output_path: Optional[Path] = None
    output_size_bytes: int = 0
    status: str = "Na fila"
    progress: float = 0.0
    error_message: str = ""
    used_fallback: bool = False
    note: str = ""


@dataclass
class ConversionSettings:
    """Configurações escolhidas pelo usuário para o lote."""

    profile_id: str = "hevc_balanced"
    resolution: str = "original"
    recursive: bool = False
    skip_existing: bool = True
    prevent_larger: bool = True


@dataclass
class ConversionResult:
    """Resultado da conversão de um único vídeo."""

    success: bool
    skipped: bool = False
    cancelled: bool = False
    output_path: Optional[Path] = None
    output_size_bytes: int = 0
    used_fallback: bool = False
    note: str = ""
    error_message: str = ""


@dataclass
class BatchSummary:
    """Resumo acumulado de um lote de conversões."""

    total_files: int = 0
    completed: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: bool = False
    total_input_bytes: int = 0
    total_output_bytes: int = 0
    elapsed_seconds: float = 0.0


def _subprocess_flags() -> int:
    """Oculta janelas de console ao invocar subprocessos no Windows."""
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def get_app_dir() -> Path:
    """Retorna a pasta base do aplicativo, compatível com script .py e executável .exe."""
    module_parent = Path(__file__).resolve().parent
    if module_parent.suffix.lower() == ".exe":
        return module_parent.parent
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return module_parent


def find_binaries() -> tuple[Optional[Path], Optional[Path]]:
    """Localiza os executáveis ffmpeg e ffprobe prioritariamente na pasta local ./bin."""
    candidate_dirs: list[Path] = [get_app_dir() / "bin"]
    if sys.argv and sys.argv[0]:
        argv_bin = Path(sys.argv[0]).resolve().parent / "bin"
        if argv_bin not in candidate_dirs:
            candidate_dirs.append(argv_bin)

    ffmpeg_path: Optional[Path] = None
    ffprobe_path: Optional[Path] = None

    exe_suffix = ".exe" if os.name == "nt" else ""
    for bin_dir in candidate_dirs:
        candidate = bin_dir / f"ffmpeg{exe_suffix}"
        if candidate.is_file():
            ffmpeg_path = candidate
            break

    if ffmpeg_path is None:
        which_ffmpeg = shutil.which("ffmpeg")
        if which_ffmpeg:
            ffmpeg_path = Path(which_ffmpeg)
        else:
            try:
                import imageio_ffmpeg  # type: ignore

                ffmpeg_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
            except Exception:
                ffmpeg_path = None

    for bin_dir in candidate_dirs:
        candidate = bin_dir / f"ffprobe{exe_suffix}"
        if candidate.is_file():
            ffprobe_path = candidate
            break

    if ffprobe_path is None:
        which_ffprobe = shutil.which("ffprobe")
        if which_ffprobe:
            ffprobe_path = Path(which_ffprobe)
        elif ffmpeg_path is not None:
            sibling = ffmpeg_path.with_name(f"ffprobe{exe_suffix}")
            if sibling.is_file():
                ffprobe_path = sibling

    return ffmpeg_path, ffprobe_path


def format_size(num_bytes: int) -> str:
    """Formata tamanho em bytes de forma legível em MB/GB."""
    if num_bytes <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(num_bytes)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit in ("B", "KB"):
                return f"{value:.0f} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def format_duration(seconds: float) -> str:
    """Formata duração em segundos como HH:MM:SS ou MM:SS."""
    if seconds <= 0:
        return "--:--"
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_savings(original_bytes: int, final_bytes: int) -> str:
    """Formata a economia obtida entre o tamanho original e o tamanho final."""
    if original_bytes <= 0 or final_bytes <= 0:
        return "—"
    diff = original_bytes - final_bytes
    pct = (diff / original_bytes) * 100.0
    if diff >= 0:
        return f"-{pct:.1f}% ({format_size(diff)})"
    return f"+{abs(pct):.1f}% (+{format_size(abs(diff))})"


def probe_duration(
    video_path: Path,
    ffmpeg_path: Optional[Path] = None,
    ffprobe_path: Optional[Path] = None,
) -> float:
    """Obtém a duração do vídeo em segundos usando ffprobe ou fallback via ffmpeg."""
    if ffprobe_path and ffprobe_path.is_file():
        try:
            proc = subprocess.run(
                [
                    str(ffprobe_path),
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                creationflags=_subprocess_flags(),
            )
            if proc.returncode == 0 and proc.stdout:
                data = json.loads(proc.stdout)
                raw = data.get("format", {}).get("duration")
                if raw is not None:
                    val = float(raw)
                    if val > 0:
                        return val
        except Exception:
            pass

    if ffmpeg_path and ffmpeg_path.is_file():
        try:
            proc = subprocess.run(
                [str(ffmpeg_path), "-i", str(video_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                creationflags=_subprocess_flags(),
            )
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr or "")
            if match:
                h, m, s = match.groups()
                return int(h) * 3600 + int(m) * 60 + float(s)
        except Exception:
            pass

    return 0.0


def _is_subpath(child: Path, parent: Path) -> bool:
    """Verifica se child está dentro de parent sem lançar exceções."""
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def scan_videos(
    input_dir: Path | str,
    recursive: bool = False,
    output_dir: Optional[Path | str] = None,
    probe_durations: bool = True,
) -> list[VideoItem]:
    """Localiza todos os vídeos suportados na pasta de origem."""
    src_root = Path(input_dir).resolve()
    if not src_root.is_dir():
        return []

    out_root = Path(output_dir).resolve() if output_dir else None
    ignore_output_subtree = (
        out_root is not None
        and out_root != src_root
        and _is_subpath(out_root, src_root)
    )

    ffmpeg_path, ffprobe_path = find_binaries() if probe_durations else (None, None)
    ext_set = {ext.lower() for ext in VIDEO_EXTENSIONS}

    iterator = src_root.rglob("*") if recursive else src_root.iterdir()
    found_paths: list[Path] = []
    for entry in iterator:
        if not entry.is_file():
            continue
        lower_name = entry.name.lower()
        if lower_name.endswith(TEMP_SUFFIX) or lower_name.endswith(".part.mp4"):
            continue
        if entry.suffix.lower() not in ext_set:
            continue
        if ignore_output_subtree and out_root is not None and _is_subpath(entry, out_root):
            continue
        found_paths.append(entry)

    found_paths.sort(key=lambda p: str(p).lower())

    items: list[VideoItem] = []
    for path in found_paths:
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0
        rel = path.relative_to(src_root)
        duration = (
            probe_duration(path, ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path)
            if probe_durations
            else 0.0
        )
        items.append(
            VideoItem(
                source_path=path,
                relative_path=rel,
                size_bytes=size_bytes,
                duration_seconds=duration,
            )
        )

    return items


def build_output_paths(items: list[VideoItem], output_dir: Path | str) -> None:
    """Calcula os caminhos de destino .mp4 sem colisões entre arquivos diferentes."""
    out_root = Path(output_dir).resolve()
    used_targets: set[Path] = set()

    for item in items:
        candidate = out_root / item.relative_path.with_suffix(".mp4")
        if candidate in used_targets:
            orig_ext = item.source_path.suffix.lstrip(".").lower() or "video"
            stem = item.relative_path.stem
            candidate = candidate.with_name(f"{stem}_{orig_ext}.mp4")
            counter = 2
            while candidate in used_targets:
                candidate = candidate.with_name(f"{stem}_{orig_ext}_{counter}.mp4")
                counter += 1
        used_targets.add(candidate)
        item.output_path = candidate


def build_scale_filter(resolution: str) -> str:
    """Constrói o filtro de escala garantindo dimensões pares exigidas por YUV420p."""
    if resolution == "1080p":
        return "scale='trunc(min(1920,iw)/2)*2':-2"
    if resolution == "720p":
        return "scale='trunc(min(1280,iw)/2)*2':-2"
    return "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def build_ffmpeg_command(
    ffmpeg_path: Path,
    source_path: Path,
    temp_output_path: Path,
    profile: ConversionProfile,
    resolution: str,
    use_fallback: bool = False,
) -> list[str]:
    """Monta a linha de comando do FFmpeg para conversão eficiente em MP4."""
    video_args = (
        profile.fallback_video_args
        if (use_fallback and profile.fallback_video_args)
        else profile.video_args
    )
    scale_filter = build_scale_filter(resolution)

    cmd = [
        str(ffmpeg_path),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostats",
        "-progress",
        "pipe:1",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        scale_filter,
        "-pix_fmt",
        "yuv420p",
        *video_args,
        *profile.audio_args,
        "-movflags",
        "+faststart",
        str(temp_output_path),
    ]
    return cmd


def _run_ffmpeg_with_progress(
    cmd: list[str],
    duration_seconds: float,
    cancel_event: threading.Event,
    on_progress: Optional[Callable[[float], None]] = None,
) -> tuple[int, bool, str]:
    """Executa o FFmpeg lendo -progress pipe:1 e drenando stderr sem deadlock."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_subprocess_flags(),
    )

    stderr_lines: list[str] = []

    def _drain_stderr() -> None:
        if proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                stripped = line.strip()
                if stripped:
                    stderr_lines.append(stripped)
                    if len(stderr_lines) > 30:
                        stderr_lines.pop(0)
        except Exception:
            pass

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    cancelled = False
    last_reported = -1.0

    try:
        if proc.stdout is not None:
            for raw_line in proc.stdout:
                if cancel_event.is_set():
                    cancelled = True
                    _terminate_process(proc)
                    break

                line = raw_line.strip()
                if not line or "=" not in line:
                    continue

                key, _, value = line.partition("=")
                if key == "out_time_us" and duration_seconds > 0:
                    try:
                        out_sec = int(value) / 1_000_000.0
                        pct = max(0.0, min(99.5, (out_sec / duration_seconds) * 100.0))
                        if on_progress and (pct - last_reported >= 0.5 or pct >= 99.0):
                            last_reported = pct
                            on_progress(pct)
                    except ValueError:
                        pass
                elif key == "out_time_ms" and duration_seconds > 0:
                    try:
                        # No FFmpeg, out_time_ms na prática é reportado em microssegundos.
                        out_sec = int(value) / 1_000_000.0
                        pct = max(0.0, min(99.5, (out_sec / duration_seconds) * 100.0))
                        if on_progress and (pct - last_reported >= 0.5 or pct >= 99.0):
                            last_reported = pct
                            on_progress(pct)
                    except ValueError:
                        pass
                elif key == "progress" and value == "end":
                    if on_progress:
                        on_progress(100.0)

        if cancel_event.is_set() and proc.poll() is None:
            cancelled = True
            _terminate_process(proc)

        return_code = proc.wait()
    finally:
        stderr_thread.join(timeout=2.0)

    return return_code, cancelled, "\n".join(stderr_lines)


def _terminate_process(proc: subprocess.Popen[str]) -> None:
    """Encerra o processo FFmpeg de maneira segura."""
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
    except Exception:
        pass


def _try_remux_mp4(
    ffmpeg_path: Path,
    source_path: Path,
    temp_remux_path: Path,
) -> bool:
    """Tenta remuxar diretamente para MP4 sem reencodar (-c copy)."""
    cmd = [
        str(ffmpeg_path),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(temp_remux_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=_subprocess_flags(),
        )
        return proc.returncode == 0 and temp_remux_path.is_file() and temp_remux_path.stat().st_size > 0
    except Exception:
        return False


def _cleanup_temp(path: Path) -> None:
    """Remove arquivo temporário silenciosamente se existir."""
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def convert_single_video(
    item: VideoItem,
    output_dir: Path | str,
    settings: ConversionSettings,
    cancel_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[float], None]] = None,
    ffmpeg_path: Optional[Path] = None,
    ffprobe_path: Optional[Path] = None,
) -> ConversionResult:
    """Converte um único vídeo para MP4 eficiente com suporte a progresso e proteção de tamanho."""
    cancel = cancel_event or threading.Event()
    if cancel.is_set():
        return ConversionResult(success=False, cancelled=True)

    if ffmpeg_path is None:
        ffmpeg_path, detected_ffprobe = find_binaries()
        if ffprobe_path is None:
            ffprobe_path = detected_ffprobe

    if ffmpeg_path is None or not ffmpeg_path.is_file():
        return ConversionResult(
            success=False,
            error_message="FFmpeg não encontrado na pasta bin/ nem no PATH do sistema.",
        )

    profile = PROFILE_BY_ID.get(settings.profile_id, PROFILES[0])
    out_root = Path(output_dir).resolve()
    target_path = item.output_path or (out_root / item.relative_path.with_suffix(".mp4"))
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if settings.skip_existing and target_path.exists() and target_path.resolve() != item.source_path.resolve():
        existing_size = target_path.stat().st_size
        return ConversionResult(
            success=True,
            skipped=True,
            output_path=target_path,
            output_size_bytes=existing_size,
            note="Pulado (arquivo já existe)",
        )

    duration = item.duration_seconds
    if duration <= 0:
        duration = probe_duration(item.source_path, ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path)
        item.duration_seconds = duration

    temp_path = target_path.with_name(f"{target_path.stem}{TEMP_SUFFIX}")
    _cleanup_temp(temp_path)

    used_fallback = False
    cmd = build_ffmpeg_command(
        ffmpeg_path=ffmpeg_path,
        source_path=item.source_path,
        temp_output_path=temp_path,
        profile=profile,
        resolution=settings.resolution,
        use_fallback=False,
    )
    returncode, cancelled, err_msg = _run_ffmpeg_with_progress(
        cmd=cmd,
        duration_seconds=duration,
        cancel_event=cancel,
        on_progress=on_progress,
    )

    if cancelled:
        _cleanup_temp(temp_path)
        return ConversionResult(success=False, cancelled=True)

    if returncode != 0 and profile.fallback_video_args is not None:
        _cleanup_temp(temp_path)
        used_fallback = True
        fallback_cmd = build_ffmpeg_command(
            ffmpeg_path=ffmpeg_path,
            source_path=item.source_path,
            temp_output_path=temp_path,
            profile=profile,
            resolution=settings.resolution,
            use_fallback=True,
        )
        returncode, cancelled, err_msg = _run_ffmpeg_with_progress(
            cmd=fallback_cmd,
            duration_seconds=duration,
            cancel_event=cancel,
            on_progress=on_progress,
        )
        if cancelled:
            _cleanup_temp(temp_path)
            return ConversionResult(success=False, cancelled=True)

    if returncode != 0 or not temp_path.is_file() or temp_path.stat().st_size == 0:
        _cleanup_temp(temp_path)
        return ConversionResult(
            success=False,
            error_message=err_msg or f"FFmpeg retornou código {returncode}.",
        )

    converted_size = temp_path.stat().st_size
    note = ""

    # Proteção contra aumento de tamanho quando o vídeo original já era altamente comprimido.
    if settings.prevent_larger and item.size_bytes > 0 and converted_size >= item.size_bytes:
        if item.source_path.suffix.lower() == ".mp4":
            _cleanup_temp(temp_path)
            if item.source_path.resolve() != target_path.resolve():
                shutil.copy2(item.source_path, target_path)
            final_size = target_path.stat().st_size
            return ConversionResult(
                success=True,
                output_path=target_path,
                output_size_bytes=final_size,
                used_fallback=used_fallback,
                note="Original já otimizado (mantido)",
            )

        remux_temp = target_path.with_name(f"{target_path.stem}.remux{TEMP_SUFFIX}")
        _cleanup_temp(remux_temp)
        if _try_remux_mp4(ffmpeg_path, item.source_path, remux_temp):
            remux_size = remux_temp.stat().st_size
            if remux_size < converted_size:
                _cleanup_temp(temp_path)
                os.replace(remux_temp, target_path)
                return ConversionResult(
                    success=True,
                    output_path=target_path,
                    output_size_bytes=remux_size,
                    used_fallback=used_fallback,
                    note="Remux direto MP4 (menor tamanho)",
                )
        _cleanup_temp(remux_temp)
        note = "Convertido p/ MP4 (original já muito comprimido)"

    if used_fallback and not note:
        note = "Fallback CPU aplicado"

    os.replace(temp_path, target_path)
    final_size = target_path.stat().st_size

    if on_progress:
        on_progress(100.0)

    return ConversionResult(
        success=True,
        output_path=target_path,
        output_size_bytes=final_size,
        used_fallback=used_fallback,
        note=note,
    )


def convert_batch(
    items: list[VideoItem],
    output_dir: Path | str,
    settings: ConversionSettings,
    cancel_event: Optional[threading.Event] = None,
    on_item_update: Optional[Callable[[int, VideoItem], None]] = None,
    on_batch_progress: Optional[Callable[[int, int], None]] = None,
) -> BatchSummary:
    """Processa uma lista de vídeos sequencialmente com atualização em tempo real."""
    cancel = cancel_event or threading.Event()
    started = time.monotonic()
    out_root = Path(output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    build_output_paths(items, out_root)

    ffmpeg_path, ffprobe_path = find_binaries()
    summary = BatchSummary(total_files=len(items))

    for idx, item in enumerate(items):
        if cancel.is_set():
            summary.cancelled = True
            item.status = "Cancelado"
            if on_item_update:
                on_item_update(idx, item)
            continue

        item.status = "Convertendo (0%)"
        item.progress = 0.0
        item.error_message = ""
        item.note = ""
        if on_item_update:
            on_item_update(idx, item)

        def _handle_progress(pct: float, _idx: int = idx, _item: VideoItem = item) -> None:
            _item.progress = pct
            _item.status = f"Convertendo ({pct:.0f}%)"
            if on_item_update:
                on_item_update(_idx, _item)

        res = convert_single_video(
            item=item,
            output_dir=out_root,
            settings=settings,
            cancel_event=cancel,
            on_progress=_handle_progress,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
        )

        if res.cancelled:
            summary.cancelled = True
            item.status = "Cancelado"
            item.progress = 0.0
        elif res.skipped:
            summary.skipped += 1
            item.status = "Pulado (já existe)"
            item.progress = 100.0
            item.output_size_bytes = res.output_size_bytes
            item.note = res.note
            summary.total_input_bytes += item.size_bytes
            summary.total_output_bytes += res.output_size_bytes
        elif res.success:
            summary.completed += 1
            item.progress = 100.0
            item.output_size_bytes = res.output_size_bytes
            item.used_fallback = res.used_fallback
            item.note = res.note
            item.status = f"Concluído{f' ({res.note})' if res.note else ''}"
            summary.total_input_bytes += item.size_bytes
            summary.total_output_bytes += res.output_size_bytes
        else:
            summary.failed += 1
            item.status = "Erro"
            item.error_message = res.error_message

        if on_item_update:
            on_item_update(idx, item)
        if on_batch_progress:
            on_batch_progress(idx + 1, len(items))

    summary.elapsed_seconds = time.monotonic() - started
    return summary


@dataclass
class DownloadResult:
    """Resultado do download de um vídeo do YouTube em MP4 com vídeo e áudio."""

    success: bool
    file_path: Optional[Path] = None
    title: str = ""
    size_bytes: int = 0
    duration_seconds: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    video_codec: str = ""
    audio_codec: str = ""
    cancelled: bool = False
    error_message: str = ""


class _DownloadCancelledError(Exception):
    """Exceção interna para interromper o yt-dlp em caso de cancelamento."""


class _SilentYtdlpLogger:
    """Logger silencioso para o yt-dlp capturar avisos/erros sem poluir stdout."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def debug(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        if msg:
            self.errors.append(msg.strip())


def normalize_youtube_url(raw_url: str) -> str:
    """Normaliza URLs do YouTube corrigindo prefixos truncados como 'h/www.youtube.com/...'."""
    cleaned = (raw_url or "").strip().strip("\"'<>")
    if not cleaned:
        return ""

    if re.match(r"^https?://", cleaned, flags=re.IGNORECASE):
        return cleaned

    # Corrige prefixos parciais comuns ao colar URLs (ex: h/www..., ht/www..., ttp://...)
    cleaned = re.sub(
        r"^(?:h|ht|htt|http|https)[/:]+(?=(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)\b)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"^(?:ttps?|tps?)://", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.lstrip("/")

    if re.match(r"^(?:www\.|m\.|music\.)?(?:youtube\.com|youtu\.be)\b", cleaned, flags=re.IGNORECASE):
        return f"https://{cleaned}"

    return f"https://{cleaned}"


def verify_video_and_audio_streams(
    file_path: Path,
    ffmpeg_path: Optional[Path] = None,
) -> tuple[bool, bool, str, str]:
    """Verifica via FFmpeg se o arquivo possui vídeo e áudio e retorna seus codecs."""
    if ffmpeg_path is None:
        ffmpeg_path, _ = find_binaries()
    if ffmpeg_path is None or not ffmpeg_path.is_file() or not file_path.is_file():
        return False, False, "", ""

    try:
        proc = subprocess.run(
            [str(ffmpeg_path), "-hide_banner", "-i", str(file_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            creationflags=_subprocess_flags(),
        )
        stderr = proc.stderr or ""
        video_match = re.search(r"Stream\s+#\d+:\d+.*?:\s*Video:\s*([A-Za-z0-9_+-]+)", stderr)
        audio_match = re.search(r"Stream\s+#\d+:\d+.*?:\s*Audio:\s*([A-Za-z0-9_+-]+)", stderr)
        has_video = video_match is not None
        has_audio = audio_match is not None
        video_codec = video_match.group(1).lower() if video_match else ""
        audio_codec = audio_match.group(1).lower() if audio_match else ""
        return has_video, has_audio, video_codec, audio_codec
    except Exception:
        return False, False, "", ""


def _remux_or_fix_audio_to_aac(
    ffmpeg_path: Path,
    file_path: Path,
    reencode_video: bool = False,
) -> tuple[bool, str]:
    """Garante áudio AAC e faststart no MP4 (sem perder o vídeo)."""
    temp_path = file_path.with_name(f"{file_path.stem}.fixaudio{TEMP_SUFFIX}")
    _cleanup_temp(temp_path)

    video_args = (
        ["-c:v", "libx264", "-crf", "21", "-preset", "medium", "-pix_fmt", "yuv420p"]
        if reencode_video
        else ["-c:v", "copy"]
    )
    cmd = [
        str(ffmpeg_path),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(file_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        *video_args,
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(temp_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            creationflags=_subprocess_flags(),
        )
        if proc.returncode == 0 and temp_path.is_file() and temp_path.stat().st_size > 0:
            os.replace(temp_path, file_path)
            return True, ""
        err = (proc.stderr or "").strip()
        _cleanup_temp(temp_path)
        return False, err or f"FFmpeg retornou código {proc.returncode}"
    except Exception as exc:
        _cleanup_temp(temp_path)
        return False, str(exc)


def download_youtube_video(
    url: str,
    output_dir: Path | str,
    on_progress: Optional[Callable[[float, str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> DownloadResult:
    """Baixa um vídeo do YouTube garantindo arquivo MP4 com vídeo e áudio AAC funcionais."""
    cancel = cancel_event or threading.Event()
    if cancel.is_set():
        return DownloadResult(success=False, cancelled=True)

    normalized_url = normalize_youtube_url(url)
    if not normalized_url:
        return DownloadResult(success=False, error_message="Informe uma URL do YouTube válida.")

    ffmpeg_path, ffprobe_path = find_binaries()
    if ffmpeg_path is None or not ffmpeg_path.is_file():
        return DownloadResult(
            success=False,
            error_message="FFmpeg não encontrado em bin\\ffmpeg.exe para mesclar vídeo e áudio.",
        )

    try:
        import yt_dlp  # type: ignore
    except ImportError:
        return DownloadResult(
            success=False,
            error_message="Biblioteca yt-dlp não instalada. Execute: pip install yt-dlp",
        )

    out_root = Path(output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    logger = _SilentYtdlpLogger()
    downloaded_candidates: list[Path] = []

    def _progress_hook(data: dict) -> None:
        if cancel.is_set():
            raise _DownloadCancelledError("Download cancelado pelo usuário.")

        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            pct = (downloaded / total) * 90.0 if total > 0 else 0.0
            if on_progress:
                on_progress(min(90.0, max(0.0, pct)), "Baixando faixas de vídeo e áudio...")
        elif status == "finished":
            filename = data.get("filename")
            if filename:
                downloaded_candidates.append(Path(filename))
            if on_progress:
                on_progress(92.0, "Mesclando vídeo e áudio em MP4...")

    ydl_opts = {
        "format": "bv*[vcodec^=avc1][ext=mp4]+ba[ext=m4a]/bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "ffmpeg_location": str(ffmpeg_path),
        "outtmpl": str(out_root / "%(title).120B [%(id)s].%(ext)s"),
        "windowsfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "logger": logger,
        "progress_hooks": [_progress_hook],
    }

    title = ""
    final_path: Optional[Path] = None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(normalized_url, download=True)
            if isinstance(info, dict):
                title = str(info.get("title") or "")
                req_downloads = info.get("requested_downloads") or []
                for req in req_downloads:
                    fp = req.get("filepath")
                    if fp and Path(fp).is_file():
                        final_path = Path(fp)
                        break
                if final_path is None:
                    prepared = Path(ydl.prepare_filename(info))
                    mp4_candidate = prepared.with_suffix(".mp4")
                    if mp4_candidate.is_file():
                        final_path = mp4_candidate
                    elif prepared.is_file():
                        final_path = prepared
    except _DownloadCancelledError:
        return DownloadResult(success=False, cancelled=True)
    except Exception as exc:
        err_detail = "\n".join(logger.errors) if logger.errors else str(exc)
        return DownloadResult(success=False, error_message=err_detail)

    if final_path is None or not final_path.is_file():
        for cand in reversed(downloaded_candidates):
            mp4_cand = cand.with_suffix(".mp4")
            if mp4_cand.is_file():
                final_path = mp4_cand
                break
            if cand.is_file():
                final_path = cand
                break

    if final_path is None or not final_path.is_file():
        return DownloadResult(
            success=False,
            error_message="O arquivo baixado não foi localizado após a conclusão do yt-dlp.",
        )

    has_video, has_audio, video_codec, audio_codec = verify_video_and_audio_streams(
        final_path, ffmpeg_path=ffmpeg_path
    )

    if not has_video or not has_audio:
        return DownloadResult(
            success=False,
            file_path=final_path,
            title=title,
            has_video=has_video,
            has_audio=has_audio,
            video_codec=video_codec,
            audio_codec=audio_codec,
            error_message=(
                "O arquivo resultante não contém vídeo e áudio juntos "
                f"(vídeo={has_video}, áudio={has_audio})."
            ),
        )

    # Garante áudio AAC e container MP4 compatível com players do Windows
    if audio_codec != "aac" or final_path.suffix.lower() != ".mp4":
        if on_progress:
            on_progress(96.0, "Convertendo áudio para AAC compatível...")
        target_mp4 = final_path.with_suffix(".mp4")
        ok, fix_err = _remux_or_fix_audio_to_aac(ffmpeg_path, final_path, reencode_video=False)
        if not ok:
            ok, fix_err = _remux_or_fix_audio_to_aac(ffmpeg_path, final_path, reencode_video=True)
        if not ok:
            return DownloadResult(
                success=False,
                file_path=final_path,
                title=title,
                error_message=f"Falha ao padronizar áudio AAC no MP4: {fix_err}",
            )
        if final_path != target_mp4 and final_path.is_file():
            os.replace(final_path, target_mp4)
            final_path = target_mp4
        has_video, has_audio, video_codec, audio_codec = verify_video_and_audio_streams(
            final_path, ffmpeg_path=ffmpeg_path
        )

    if not has_video or not has_audio:
        return DownloadResult(
            success=False,
            file_path=final_path,
            title=title,
            has_video=has_video,
            has_audio=has_audio,
            error_message="Verificação final falhou: vídeo ou áudio ausente no arquivo MP4.",
        )

    duration = probe_duration(final_path, ffmpeg_path=ffmpeg_path, ffprobe_path=ffprobe_path)
    size_bytes = final_path.stat().st_size

    if on_progress:
        on_progress(100.0, "Download concluído (vídeo + áudio OK)")

    return DownloadResult(
        success=True,
        file_path=final_path,
        title=title or final_path.stem,
        size_bytes=size_bytes,
        duration_seconds=duration,
        has_video=has_video,
        has_audio=has_audio,
        video_codec=video_codec,
        audio_codec=audio_codec,
    )

