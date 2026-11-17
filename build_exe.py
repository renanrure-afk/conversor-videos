"""Gera os executáveis .exe do aplicativo, do desinstalador e do instalador Windows."""

from __future__ import annotations

import math
import struct
import sys
import zipfile
from io import BytesIO
from pathlib import Path

from pip._vendor.distlib.scripts import ScriptMaker


def _make_icon_dib(size: int) -> bytes:
    """Cria uma imagem DIB RGBA (BGRA + máscara AND) para embutir em arquivo .ico."""
    pixels = bytearray(size * size * 4)
    radius = size * 0.22
    cx = (size - 1) / 2.0
    cy = (size - 1) / 2.0

    # Desenha de baixo para cima (ordem exigida pelo formato BMP/DIB do .ico)
    for y_bmp in range(size):
        y = size - 1 - y_bmp
        for x in range(size):
            # Distância de bordas arredondadas (rounded rect)
            dx = max(abs(x - cx) - (size / 2.0 - radius), 0.0)
            dy = max(abs(y - cy) - (size / 2.0 - radius), 0.0)
            dist = math.hypot(dx, dy)

            if dist > radius + 0.5:
                b, g, r, a = 0, 0, 0, 0
            else:
                # Gradiente azul escuro -> índigo
                t = (x + y) / (2.0 * max(1, size - 1))
                r = int(26 + (59 - 26) * t)
                g = int(42 + (130 - 42) * t)
                b = int(84 + (246 - 84) * t)
                a = 255 if dist <= radius - 0.3 else int(max(0, min(255, (radius + 0.5 - dist) * 255)))

                # Borda sutil clara
                if radius - 1.4 <= dist <= radius - 0.1:
                    r = min(255, r + 40)
                    g = min(255, g + 45)
                    b = min(255, b + 50)

                # Triângulo de play verde-esmeralda/branco centralizado
                nx = x / size
                ny = y / size
                if 0.33 <= nx <= 0.73:
                    span = (0.73 - nx) / (0.73 - 0.33)
                    half_h = 0.23 * span
                    if abs(ny - 0.5) <= half_h:
                        r, g, b, a = 242, 252, 248, 255
                        if nx >= 0.52:
                            r, g, b = 16, 215, 145

            offset = (y_bmp * size + x) * 4
            pixels[offset : offset + 4] = bytes((b, g, r, a))

    # BITMAPINFOHEADER (40 bytes): altura é 2 * size porque inclui imagem XOR + máscara AND
    header = struct.pack(
        "<IIIHHIIIIII",
        40,          # biSize
        size,        # biWidth
        size * 2,    # biHeight
        1,           # biPlanes
        32,          # biBitCount
        0,           # biCompression (BI_RGB)
        len(pixels), # biSizeImage
        0, 0, 0, 0,
    )
    and_row_bytes = ((size + 31) // 32) * 4
    and_mask = b"\x00" * (and_row_bytes * size)
    return header + bytes(pixels) + and_mask


def generate_app_icon(output_path: Path) -> None:
    """Gera o arquivo app_icon.ico com tamanhos 32x32 e 48x48."""
    sizes = (32, 48)
    dibs = [_make_icon_dib(s) for s in sizes]
    icon_dir = struct.pack("<HHH", 0, 1, len(sizes))

    entries = bytearray()
    offset = 6 + 16 * len(sizes)
    for size, dib in zip(sizes, dibs):
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                size if size < 256 else 0,
                size if size < 256 else 0,
                0,
                0,
                1,
                32,
                len(dib),
                offset,
            )
        )
        offset += len(dib)

    output_path.write_bytes(icon_dir + bytes(entries) + b"".join(dibs))


HIDE_CONSOLE_PREAMBLE = (
    "import ctypes, sys\n"
    "if '--self-test' not in sys.argv and '--silent' not in sys.argv:\n"
    "    try:\n"
    "        hwnd = ctypes.windll.kernel32.GetConsoleWindow()\n"
    "        if hwnd:\n"
    "            ctypes.windll.user32.ShowWindow(hwnd, 0)\n"
    "    except Exception:\n"
    "        pass\n"
)


def _build_exe(
    target_exe: Path,
    main_code: str,
    files: list[tuple[Path, str, int]],
    python_exe: Path,
) -> None:
    """Empacota arquivos Python e recursos em um executável Windows (.exe) via stub t64."""
    maker = ScriptMaker(None, str(target_exe.parent))
    maker.executable = str(python_exe)
    launcher = maker._get_launcher("t")
    shebang = maker._get_shebang("utf-8")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("__main__.py", main_code.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        for src_path, arcname, compression in files:
            zf.write(src_path, arcname=arcname, compress_type=compression)

    target_exe.write_bytes(launcher + shebang + buf.getvalue())


def build_all() -> None:
    base_dir = Path(__file__).resolve().parent
    python_exe = Path(sys.executable).resolve()

    icon_path = base_dir / "app_icon.ico"
    generate_app_icon(icon_path)
    print("Gerado:", icon_path)

    app_exe = base_dir / "ConversorDeVideos.exe"
    _build_exe(
        target_exe=app_exe,
        main_code=HIDE_CONSOLE_PREAMBLE + "from app import main\nraise SystemExit(main())\n",
        files=[
            (base_dir / "app.py", "app.py", zipfile.ZIP_DEFLATED),
            (base_dir / "engine.py", "engine.py", zipfile.ZIP_DEFLATED),
        ],
        python_exe=python_exe,
    )
    print("Gerado:", app_exe, f"({app_exe.stat().st_size} bytes)")

    uninstall_exe = base_dir / "Desinstalar_Conversor.exe"
    _build_exe(
        target_exe=uninstall_exe,
        main_code=HIDE_CONSOLE_PREAMBLE + "from installer_gui import main\nraise SystemExit(main(default_mode='uninstall'))\n",
        files=[
            (base_dir / "installer_gui.py", "installer_gui.py", zipfile.ZIP_DEFLATED),
        ],
        python_exe=python_exe,
    )
    print("Gerado:", uninstall_exe, f"({uninstall_exe.stat().st_size} bytes)")

    ffmpeg_exe = base_dir / "bin" / "ffmpeg.exe"
    if not ffmpeg_exe.is_file():
        raise FileNotFoundError(f"FFmpeg não encontrado em {ffmpeg_exe}")

    installer_exe = base_dir / "Instalador_Conversor_de_Videos.exe"
    payload_files = [
        (base_dir / "installer_gui.py", "installer_gui.py", zipfile.ZIP_DEFLATED),
        (app_exe, "payload/ConversorDeVideos.exe", zipfile.ZIP_DEFLATED),
        (uninstall_exe, "payload/Desinstalar_Conversor.exe", zipfile.ZIP_DEFLATED),
        (icon_path, "payload/app_icon.ico", zipfile.ZIP_DEFLATED),
        (base_dir / "app.py", "payload/app.py", zipfile.ZIP_DEFLATED),
        (base_dir / "engine.py", "payload/engine.py", zipfile.ZIP_DEFLATED),
        (base_dir / "README.md", "payload/README.md", zipfile.ZIP_DEFLATED),
        (ffmpeg_exe, "payload/bin/ffmpeg.exe", zipfile.ZIP_DEFLATED),
    ]
    _build_exe(
        target_exe=installer_exe,
        main_code=HIDE_CONSOLE_PREAMBLE + "from installer_gui import main\nraise SystemExit(main(default_mode='install'))\n",
        files=payload_files,
        python_exe=python_exe,
    )
    print("Gerado:", installer_exe, f"({installer_exe.stat().st_size} bytes)")


if __name__ == "__main__":
    build_all()
