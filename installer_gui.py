"""Instalador e desinstalador gráfico Windows para o Conversor de Vídeos em Massa."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import winreg
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional


APP_NAME = "Conversor de Vídeos em Massa (MP4)"
APP_SHORTCUT_NAME = "Conversor de Vídeos.lnk"
UNINSTALL_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ConversorDeVideosEmMassa"

BG_APP = "#111622"
BG_CARD = "#1A2233"
BG_INPUT = "#0F1521"
BG_HOVER = "#26324A"
BORDER_COLOR = "#2B3750"
TEXT_PRIMARY = "#F1F5F9"
TEXT_SECONDARY = "#94A3B8"
ACCENT_GREEN = "#10B981"
ACCENT_GREEN_HOVER = "#059669"

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _subprocess_flags() -> int:
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def default_install_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / "Programs" / "ConversorDeVideos"


def _current_container_dir() -> Path:
    if sys.argv and sys.argv[0]:
        p = Path(sys.argv[0]).resolve()
        if p.is_file():
            return p.parent
    mod_parent = Path(__file__).resolve().parent
    if mod_parent.suffix.lower() == ".exe":
        return mod_parent.parent
    return mod_parent


def _embedded_archive_path() -> Optional[Path]:
    if sys.argv and sys.argv[0]:
        candidate = Path(sys.argv[0]).resolve()
        if candidate.is_file() and candidate.suffix.lower() == ".exe":
            return candidate
    mod_parent = Path(__file__).resolve().parent
    if mod_parent.is_file() and mod_parent.suffix.lower() == ".exe":
        return mod_parent
    return None


def _get_desktop_dir() -> Path:
    """Obtém a pasta real da Área de Trabalho (compatível com redirecionamento OneDrive)."""
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "[Environment]::GetFolderPath('Desktop')",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=_subprocess_flags(),
        )
        out = (proc.stdout or "").strip()
        if out:
            return Path(out)
    except Exception:
        pass
    return Path.home() / "Desktop"


def _get_start_menu_programs_dir() -> Path:
    app_data = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(app_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _create_windows_shortcut(
    shortcut_path: Path,
    target_exe: Path,
    working_dir: Path,
    icon_path: Path,
    description: str,
) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    esc = lambda p: str(p).replace("'", "''")
    ps_script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{esc(shortcut_path)}'); "
        f"$s.TargetPath = '{esc(target_exe)}'; "
        f"$s.WorkingDirectory = '{esc(working_dir)}'; "
        f"$s.IconLocation = '{esc(icon_path)}'; "
        f"$s.Description = '{esc(description)}'; "
        "$s.Save()"
    )
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        creationflags=_subprocess_flags(),
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "Falha ao criar atalho .lnk").strip())


def _copy_or_extract_file(
    archive: Optional[zipfile.ZipFile],
    payload_rel: str,
    local_source_dir: Path,
    dest_path: Path,
) -> bool:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if archive is not None:
        zip_member = f"payload/{payload_rel}".replace("\\", "/")
        if zip_member in archive.namelist():
            with archive.open(zip_member) as src, open(dest_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
            return True

    local_candidate = local_source_dir / payload_rel
    if local_candidate.is_file():
        shutil.copy2(local_candidate, dest_path)
        return True
    return False


def _register_uninstall_entry(install_dir: Path, total_bytes: int) -> None:
    exe_uninst = install_dir / "Desinstalar_Conversor.exe"
    icon_path = install_dir / "app_icon.ico"
    size_kb = max(1, total_bytes // 1024)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_PATH) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "1.0.0")
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Conversor Local")
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(icon_path))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{exe_uninst}" --uninstall')
        winreg.SetValueEx(
            key,
            "QuietUninstallString",
            0,
            winreg.REG_SZ,
            f'"{exe_uninst}" --uninstall --silent',
        )
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, size_kb)


def perform_install(
    install_dir: Path,
    create_desktop: bool,
    create_start_menu: bool,
    on_progress: Optional[Callable[[float, str], None]] = None,
) -> Path:
    """Instala o aplicativo, o motor FFmpeg, atalhos e registro no Windows."""
    install_dir = install_dir.resolve()
    install_dir.mkdir(parents=True, exist_ok=True)
    local_src = _current_container_dir()
    archive_path = _embedded_archive_path()

    files_to_install = [
        ("ConversorDeVideos.exe", True),
        ("Desinstalar_Conversor.exe", True),
        ("app_icon.ico", True),
        ("app.py", True),
        ("engine.py", True),
        ("README.md", False),
        ("bin/ffmpeg.exe", True),
    ]

    archive: Optional[zipfile.ZipFile] = None
    try:
        if archive_path is not None and zipfile.is_zipfile(archive_path):
            archive = zipfile.ZipFile(archive_path, "r")

        total_steps = len(files_to_install) + 3
        for idx, (rel_path, required) in enumerate(files_to_install, start=1):
            if on_progress:
                on_progress((idx / total_steps) * 80.0, f"Copiando {rel_path}...")
            dest = install_dir / rel_path
            copied = _copy_or_extract_file(archive, rel_path, local_src, dest)
            if not copied and rel_path == "bin/ffmpeg.exe":
                try:
                    import imageio_ffmpeg  # type: ignore

                    ffmpeg_src = Path(imageio_ffmpeg.get_ffmpeg_exe())
                    if ffmpeg_src.is_file():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(ffmpeg_src, dest)
                        copied = True
                except Exception:
                    pass
            if not copied and required:
                raise FileNotFoundError(f"Arquivo obrigatório não encontrado no pacote: {rel_path}")
    finally:
        if archive is not None:
            archive.close()

    main_exe = install_dir / "ConversorDeVideos.exe"
    icon_path = install_dir / "app_icon.ico"

    if on_progress:
        on_progress(86.0, "Criando atalhos do Windows...")

    if create_start_menu:
        start_shortcut = _get_start_menu_programs_dir() / APP_SHORTCUT_NAME
        _create_windows_shortcut(
            shortcut_path=start_shortcut,
            target_exe=main_exe,
            working_dir=install_dir,
            icon_path=icon_path,
            description="Conversor de Vídeos em Massa (MP4) + Download YouTube",
        )

    if create_desktop:
        desktop_shortcut = _get_desktop_dir() / APP_SHORTCUT_NAME
        _create_windows_shortcut(
            shortcut_path=desktop_shortcut,
            target_exe=main_exe,
            working_dir=install_dir,
            icon_path=icon_path,
            description="Conversor de Vídeos em Massa (MP4) + Download YouTube",
        )

    if on_progress:
        on_progress(94.0, "Registrando aplicativo no Windows...")

    total_bytes = sum(p.stat().st_size for p in install_dir.rglob("*") if p.is_file())
    _register_uninstall_entry(install_dir, total_bytes)

    if on_progress:
        on_progress(100.0, "Instalação concluída!")

    return main_exe


def perform_uninstall(install_dir: Optional[Path] = None) -> None:
    """Remove atalhos, registro no Windows e arquivos da pasta de instalação."""
    target_dir = install_dir
    if target_dir is None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_PATH) as key:
                val, _ = winreg.QueryValueEx(key, "InstallLocation")
                if val:
                    target_dir = Path(str(val))
        except OSError:
            target_dir = _current_container_dir()

    for shortcut in (
        _get_start_menu_programs_dir() / APP_SHORTCUT_NAME,
        _get_desktop_dir() / APP_SHORTCUT_NAME,
    ):
        try:
            if shortcut.exists():
                shortcut.unlink()
        except OSError:
            pass

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_PATH)
    except OSError:
        pass

    if target_dir and target_dir.is_dir():
        for item in list(target_dir.iterdir()):
            try:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            except OSError:
                pass
        # Agenda remoção da pasta caso o próprio Desinstalar_Conversor.exe ainda esteja em uso
        subprocess.Popen(
            [
                "cmd.exe",
                "/c",
                f'ping -n 2 127.0.0.1 >nul & rmdir /s /q "{target_dir}"',
            ],
            creationflags=_subprocess_flags(),
        )


class InstallerWindow:
    """Interface gráfica do instalador Windows."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Instalador — Conversor de Vídeos em Massa (MP4)")
        self.root.geometry("600x410")
        self.root.resizable(False, False)
        self.root.configure(bg=BG_APP)

        local_icon = _current_container_dir() / "app_icon.ico"
        if local_icon.is_file():
            try:
                self.root.iconbitmap(str(local_icon))
            except Exception:
                pass

        self.install_dir_var = tk.StringVar(value=str(default_install_dir()))
        self.desktop_var = tk.BooleanVar(value=True)
        self.start_menu_var = tk.BooleanVar(value=True)
        self.launch_after_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Pronto para instalar no seu computador.")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.is_installing = False

        self._setup_styles()
        self._build_ui()

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=BG_APP, foreground=TEXT_PRIMARY, font=("Segoe UI", 10))
        style.configure("Card.TFrame", background=BG_CARD)
        style.configure("CardLabel.TLabel", background=BG_CARD, foreground=TEXT_PRIMARY, font=("Segoe UI", 10))
        style.configure("CardMuted.TLabel", background=BG_CARD, foreground=TEXT_SECONDARY, font=("Segoe UI", 9))
        style.configure(
            "Dark.TEntry",
            fieldbackground=BG_INPUT,
            foreground=TEXT_PRIMARY,
            bordercolor=BORDER_COLOR,
            padding=(8, 6),
        )
        style.configure(
            "Dark.TCheckbutton",
            background=BG_CARD,
            foreground=TEXT_PRIMARY,
            focuscolor=BG_CARD,
        )
        style.map("Dark.TCheckbutton", background=[("active", BG_CARD)])
        style.configure(
            "Secondary.TButton",
            background=BG_HOVER,
            foreground=TEXT_PRIMARY,
            bordercolor=BORDER_COLOR,
            padding=(12, 6),
            font=("Segoe UI", 9, "bold"),
        )
        style.map("Secondary.TButton", background=[("active", "#334363")])
        style.configure(
            "Primary.TButton",
            background=ACCENT_GREEN,
            foreground="#FFFFFF",
            bordercolor=ACCENT_GREEN,
            padding=(18, 9),
            font=("Segoe UI", 10, "bold"),
        )
        style.map("Primary.TButton", background=[("active", ACCENT_GREEN_HOVER)])
        style.configure(
            "Install.Horizontal.TProgressbar",
            troughcolor=BG_INPUT,
            background=ACCENT_GREEN,
            bordercolor=BORDER_COLOR,
            thickness=14,
        )

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=BG_APP)
        header.pack(fill="x", padx=20, pady=(18, 12))

        tk.Label(
            header,
            text="Conversor de Vídeos em Massa (MP4)",
            bg=BG_APP,
            fg=TEXT_PRIMARY,
            font=("Segoe UI", 15, "bold"),
            anchor="w",
        ).pack(fill="x")

        tk.Label(
            header,
            text="Instalação rápida com compressor de alta eficiência e download do YouTube (vídeo + áudio).",
            bg=BG_APP,
            fg=TEXT_SECONDARY,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x", pady=(3, 0))

        border = tk.Frame(self.root, bg=BORDER_COLOR)
        border.pack(fill="both", expand=True, padx=20, pady=(0, 14))
        card = ttk.Frame(border, style="Card.TFrame", padding=(16, 14))
        card.pack(fill="both", expand=True, padx=1, pady=1)
        card.columnconfigure(0, weight=1)

        ttk.Label(card, text="Pasta de Instalação:", style="CardLabel.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4)
        )

        self.dir_entry = ttk.Entry(card, textvariable=self.install_dir_var, style="Dark.TEntry")
        self.dir_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(0, 12))

        self.btn_browse = ttk.Button(
            card, text="Alterar Pasta...", style="Secondary.TButton", command=self._choose_dir
        )
        self.btn_browse.grid(row=1, column=1, pady=(0, 12))

        ttk.Checkbutton(
            card,
            text="Criar atalho na Área de Trabalho",
            variable=self.desktop_var,
            style="Dark.TCheckbutton",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=3)

        ttk.Checkbutton(
            card,
            text="Criar atalho no Menu Iniciar",
            variable=self.start_menu_var,
            style="Dark.TCheckbutton",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=3)

        ttk.Checkbutton(
            card,
            text="Abrir o Conversor de Vídeos após instalar",
            variable=self.launch_after_var,
            style="Dark.TCheckbutton",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(3, 14))

        self.progress_bar = ttk.Progressbar(
            card,
            variable=self.progress_var,
            maximum=100.0,
            mode="determinate",
            style="Install.Horizontal.TProgressbar",
        )
        self.progress_bar.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(card, textvariable=self.status_var, style="CardMuted.TLabel").grid(
            row=6, column=0, columnspan=2, sticky="w"
        )

        footer = tk.Frame(self.root, bg=BG_APP)
        footer.pack(fill="x", padx=20, pady=(0, 18))

        self.btn_close = ttk.Button(
            footer, text="Fechar", style="Secondary.TButton", command=self.root.destroy
        )
        self.btn_close.pack(side="right", padx=(8, 0))

        self.btn_install = ttk.Button(
            footer, text="Instalar Agora", style="Primary.TButton", command=self._start_install
        )
        self.btn_install.pack(side="right")

    def _choose_dir(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Escolha a pasta para instalar o aplicativo",
            initialdir=str(default_install_dir().parent),
        )
        if selected:
            chosen = Path(selected)
            if chosen.name.lower() != "conversordevideos":
                chosen = chosen / "ConversorDeVideos"
            self.install_dir_var.set(str(chosen))

    def _start_install(self) -> None:
        if self.is_installing:
            return
        raw_dir = self.install_dir_var.get().strip()
        if not raw_dir:
            messagebox.showwarning("Pasta Inválida", "Informe uma pasta de instalação válida.", parent=self.root)
            return

        self.is_installing = True
        self.btn_install.configure(state="disabled")
        self.btn_browse.configure(state="disabled")
        self.dir_entry.configure(state="disabled")
        self.btn_close.configure(state="disabled")

        target_dir = Path(raw_dir)
        desktop = self.desktop_var.get()
        start_menu = self.start_menu_var.get()

        def _worker() -> None:
            try:
                exe_path = perform_install(
                    install_dir=target_dir,
                    create_desktop=desktop,
                    create_start_menu=start_menu,
                    on_progress=lambda pct, msg: self.root.after(0, self._on_progress, pct, msg),
                )
                self.root.after(0, self._on_done, exe_path, None)
            except Exception as exc:
                self.root.after(0, self._on_done, None, str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_progress(self, pct: float, msg: str) -> None:
        self.progress_var.set(pct)
        self.status_var.set(msg)

    def _on_done(self, exe_path: Optional[Path], error: Optional[str]) -> None:
        self.is_installing = False
        self.btn_close.configure(state="normal")
        if error:
            self.btn_install.configure(state="normal")
            self.btn_browse.configure(state="normal")
            self.dir_entry.configure(state="normal")
            self.status_var.set("Falha na instalação.")
            messagebox.showerror("Erro na Instalação", f"Não foi possível instalar:\n\n{error}", parent=self.root)
            return

        self.progress_var.set(100.0)
        self.status_var.set("Instalação concluída com sucesso!")
        if self.launch_after_var.get() and exe_path and exe_path.is_file():
            subprocess.Popen([str(exe_path)], cwd=str(exe_path.parent))
            self.root.destroy()
        else:
            messagebox.showinfo(
                "Instalação Concluída",
                f"Aplicativo instalado com sucesso em:\n{self.install_dir_var.get()}",
                parent=self.root,
            )
            self.root.destroy()


def main(default_mode: str = "install") -> int:
    args = sys.argv[1:]
    silent = "--silent" in args
    no_desktop = "--no-desktop" in args
    is_uninstall = (default_mode == "uninstall") or ("--uninstall" in args)

    custom_dir: Optional[Path] = None
    for arg in args:
        if arg.startswith("--dir="):
            custom_dir = Path(arg.split("=", 1)[1].strip('"'))

    if is_uninstall:
        if not silent:
            root = tk.Tk()
            root.withdraw()
            ok = messagebox.askyesno(
                "Desinstalar Conversor de Vídeos",
                "Deseja remover o Conversor de Vídeos em Massa e seus atalhos do computador?",
            )
            root.destroy()
            if not ok:
                return 0
        perform_uninstall(custom_dir)
        if not silent:
            root = tk.Tk()
            root.withdraw()
            messagebox.showinfo("Desinstalação Concluída", "O aplicativo foi removido do computador.")
            root.destroy()
        return 0

    if silent:
        target = custom_dir or default_install_dir()
        perform_install(
            install_dir=target,
            create_desktop=not no_desktop,
            create_start_menu=True,
        )
        return 0

    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = tk.Tk()
    InstallerWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
