"""Interface gráfica Windows para conversão de vídeos em massa com alta eficiência."""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Optional

from engine import (
    PROFILES,
    RESOLUTION_OPTIONS,
    BatchSummary,
    ConversionSettings,
    DownloadResult,
    VideoItem,
    convert_batch,
    download_youtube_video,
    find_binaries,
    format_duration,
    format_savings,
    format_size,
    get_app_dir,
    scan_videos,
)

# Garante streams válidos quando executado via pythonw.exe / .exe GUI sem console
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _enable_dpi_awareness() -> None:
    """Melhora a nitidez da interface em telas Windows com escala DPI."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# Paleta de cores do tema escuro moderno
BG_APP = "#111622"
BG_CARD = "#1A2233"
BG_INPUT = "#0F1521"
BG_ROW_ALT = "#1E273B"
BG_HOVER = "#26324A"
BORDER_COLOR = "#2B3750"
TEXT_PRIMARY = "#F1F5F9"
TEXT_SECONDARY = "#94A3B8"
ACCENT_BLUE = "#3B82F6"
ACCENT_BLUE_HOVER = "#2563EB"
ACCENT_GREEN = "#10B981"
ACCENT_GREEN_HOVER = "#059669"
ACCENT_RED = "#EF4444"
ACCENT_RED_HOVER = "#DC2626"
ACCENT_AMBER = "#F59E0B"


class VideoConverterApp:
    """Aplicação principal Tkinter para conversão de vídeos em massa para MP4."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Conversor de Vídeos em Massa — Alta Eficiência (MP4)")
        self.root.geometry("1080x810")
        self.root.minsize(920, 690)
        self.root.configure(bg=BG_APP)
        self._apply_window_icon()

        self.ffmpeg_path, _ = find_binaries()

        # Estado da aplicação
        self.items: list[VideoItem] = []
        self.tree_item_ids: list[str] = []
        self.ui_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.is_scanning = False
        self.is_converting = False
        self.is_downloading = False
        self.cancel_event = threading.Event()
        self._auto_output_dir: Optional[str] = None
        self._scan_generation = 0

        # Variáveis de formulário
        self.youtube_url_var = tk.StringVar()
        self.input_dir_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.profile_names = [p.name for p in PROFILES]
        self.profile_name_to_id = {p.name: p.id for p in PROFILES}
        self.profile_name_var = tk.StringVar(value=PROFILES[0].name)
        self.profile_desc_var = tk.StringVar(value=PROFILES[0].description)

        self.resolution_labels = [label for _, label in RESOLUTION_OPTIONS]
        self.resolution_label_to_id = {label: key for key, label in RESOLUTION_OPTIONS}
        self.resolution_var = tk.StringVar(value=self.resolution_labels[0])

        self.recursive_var = tk.BooleanVar(value=False)
        self.skip_existing_var = tk.BooleanVar(value=True)
        self.prevent_larger_var = tk.BooleanVar(value=True)

        self.current_file_label_var = tk.StringVar(value="Arquivo atual: aguardando início")
        self.batch_label_var = tk.StringVar(value="Progresso do lote: 0 de 0 vídeos")
        self.summary_var = tk.StringVar(
            value="Selecione a pasta com os vídeos de origem para começar."
        )
        self.current_progress_var = tk.DoubleVar(value=0.0)
        self.batch_progress_var = tk.DoubleVar(value=0.0)

        self._configure_styles()
        self._build_ui()
        self._update_controls_state()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(80, self._process_ui_queue)

    def _apply_window_icon(self) -> None:
        """Aplica o ícone personalizado app_icon.ico à janela quando disponível."""
        icon_path = get_app_dir() / "app_icon.ico"
        if icon_path.is_file():
            try:
                self.root.iconbitmap(str(icon_path))
            except Exception:
                pass

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        default_font = ("Segoe UI", 10)
        bold_font = ("Segoe UI", 10, "bold")
        heading_font = ("Segoe UI", 9, "bold")

        style.configure(".", background=BG_APP, foreground=TEXT_PRIMARY, font=default_font)
        style.configure("Card.TFrame", background=BG_CARD)
        style.configure("CardTitle.TLabel", background=BG_CARD, foreground=TEXT_PRIMARY, font=("Segoe UI", 11, "bold"))
        style.configure("CardLabel.TLabel", background=BG_CARD, foreground=TEXT_PRIMARY, font=default_font)
        style.configure("CardMuted.TLabel", background=BG_CARD, foreground=TEXT_SECONDARY, font=("Segoe UI", 9))

        style.configure(
            "Dark.TEntry",
            fieldbackground=BG_INPUT,
            foreground=TEXT_PRIMARY,
            insertcolor=TEXT_PRIMARY,
            bordercolor=BORDER_COLOR,
            lightcolor=BORDER_COLOR,
            darkcolor=BORDER_COLOR,
            padding=(8, 6),
        )

        style.configure(
            "Dark.TCombobox",
            fieldbackground=BG_INPUT,
            background=BG_HOVER,
            foreground=TEXT_PRIMARY,
            arrowcolor=TEXT_PRIMARY,
            bordercolor=BORDER_COLOR,
            lightcolor=BORDER_COLOR,
            darkcolor=BORDER_COLOR,
            padding=(8, 5),
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", BG_INPUT), ("disabled", "#151B28")],
            foreground=[("readonly", TEXT_PRIMARY), ("disabled", TEXT_SECONDARY)],
            selectbackground=[("readonly", BG_INPUT)],
            selectforeground=[("readonly", TEXT_PRIMARY)],
        )

        # Estiliza a lista dropdown do Combobox
        self.root.option_add("*TCombobox*Listbox.background", BG_INPUT)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT_PRIMARY)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT_BLUE)
        self.root.option_add("*TCombobox*Listbox.selectForeground", TEXT_PRIMARY)
        self.root.option_add("*TCombobox*Listbox.font", default_font)

        style.configure(
            "Dark.TCheckbutton",
            background=BG_CARD,
            foreground=TEXT_PRIMARY,
            focuscolor=BG_CARD,
            font=default_font,
        )
        style.map(
            "Dark.TCheckbutton",
            background=[("active", BG_CARD)],
            foreground=[("disabled", TEXT_SECONDARY)],
        )

        style.configure(
            "Secondary.TButton",
            background=BG_HOVER,
            foreground=TEXT_PRIMARY,
            bordercolor=BORDER_COLOR,
            focuscolor=BG_HOVER,
            padding=(12, 6),
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#334363"), ("disabled", "#182030")],
            foreground=[("disabled", "#64748B")],
        )

        style.configure(
            "Primary.TButton",
            background=ACCENT_GREEN,
            foreground="#FFFFFF",
            bordercolor=ACCENT_GREEN,
            focuscolor=ACCENT_GREEN,
            padding=(18, 9),
            font=bold_font,
        )
        style.map(
            "Primary.TButton",
            background=[("active", ACCENT_GREEN_HOVER), ("disabled", "#1F3B37")],
            foreground=[("disabled", "#7C9D96")],
        )

        style.configure(
            "AccentBlue.TButton",
            background=ACCENT_BLUE,
            foreground="#FFFFFF",
            bordercolor=ACCENT_BLUE,
            focuscolor=ACCENT_BLUE,
            padding=(14, 6),
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "AccentBlue.TButton",
            background=[("active", ACCENT_BLUE_HOVER), ("disabled", "#1E2D4A")],
            foreground=[("disabled", "#6C82A8")],
        )

        style.configure(
            "Danger.TButton",
            background=ACCENT_RED,
            foreground="#FFFFFF",
            bordercolor=ACCENT_RED,
            focuscolor=ACCENT_RED,
            padding=(14, 9),
            font=bold_font,
        )
        style.map(
            "Danger.TButton",
            background=[("active", ACCENT_RED_HOVER), ("disabled", "#3A2229")],
            foreground=[("disabled", "#8A656E")],
        )

        style.configure(
            "Dark.Treeview",
            background=BG_INPUT,
            fieldbackground=BG_INPUT,
            foreground=TEXT_PRIMARY,
            bordercolor=BORDER_COLOR,
            rowheight=28,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Dark.Treeview.Heading",
            background=BG_HOVER,
            foreground=TEXT_PRIMARY,
            bordercolor=BORDER_COLOR,
            relief="flat",
            padding=(8, 6),
            font=heading_font,
        )
        style.map(
            "Dark.Treeview.Heading",
            background=[("active", "#31405E")],
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", "#274173")],
            foreground=[("selected", "#FFFFFF")],
        )

        style.configure(
            "File.Horizontal.TProgressbar",
            troughcolor=BG_INPUT,
            background=ACCENT_BLUE,
            bordercolor=BORDER_COLOR,
            lightcolor=ACCENT_BLUE,
            darkcolor=ACCENT_BLUE,
            thickness=12,
        )
        style.configure(
            "Batch.Horizontal.TProgressbar",
            troughcolor=BG_INPUT,
            background=ACCENT_GREEN,
            bordercolor=BORDER_COLOR,
            lightcolor=ACCENT_GREEN,
            darkcolor=ACCENT_GREEN,
            thickness=14,
        )

        style.configure(
            "Vertical.TScrollbar",
            background=BG_HOVER,
            troughcolor=BG_INPUT,
            bordercolor=BORDER_COLOR,
            arrowcolor=TEXT_PRIMARY,
        )

    def _create_card(self, parent: tk.Widget, padx: int = 16, pady: tuple[int, int] = (0, 10)) -> ttk.Frame:
        outer = tk.Frame(parent, bg=BORDER_COLOR, bd=0, highlightthickness=0)
        outer.pack(fill="x", padx=padx, pady=pady)
        inner = ttk.Frame(outer, style="Card.TFrame", padding=(14, 12))
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return inner

    def _build_ui(self) -> None:
        # Cabeçalho
        header = tk.Frame(self.root, bg=BG_APP)
        header.pack(fill="x", padx=16, pady=(14, 10))

        title_col = tk.Frame(header, bg=BG_APP)
        title_col.pack(side="left", fill="x", expand=True)

        tk.Label(
            title_col,
            text="Conversor de Vídeos em Massa — Alta Eficiência (MP4)",
            bg=BG_APP,
            fg=TEXT_PRIMARY,
            font=("Segoe UI", 16, "bold"),
            anchor="w",
        ).pack(fill="x")

        tk.Label(
            title_col,
            text="Reduza drasticamente o peso de vídeos grandes mantendo ótima qualidade visual e compatibilidade.",
            bg=BG_APP,
            fg=TEXT_SECONDARY,
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        badge_text = "Motor FFmpeg Pronto" if self.ffmpeg_path else "FFmpeg Não Encontrado"
        badge_bg = "#133A2E" if self.ffmpeg_path else "#421B21"
        badge_fg = "#34D399" if self.ffmpeg_path else "#FCA5A5"
        self.engine_badge = tk.Label(
            header,
            text=badge_text,
            bg=badge_bg,
            fg=badge_fg,
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=6,
        )
        self.engine_badge.pack(side="right", anchor="n")

        # Seção compacta: Baixar do YouTube (MP4 com Vídeo + Áudio Funcional)
        yt_card = self._create_card(self.root)
        yt_card.columnconfigure(1, weight=1)

        ttk.Label(
            yt_card,
            text="Baixar do YouTube (MP4 com Vídeo + Áudio Funcional)",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        ttk.Label(
            yt_card,
            text="URL do YouTube:",
            style="CardLabel.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=2)

        self.yt_url_entry = ttk.Entry(yt_card, textvariable=self.youtube_url_var, style="Dark.TEntry")
        self.yt_url_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=2)
        self.yt_url_entry.bind("<Return>", lambda _event: self._start_youtube_download())

        self.btn_yt_download = ttk.Button(
            yt_card,
            text="Baixar Vídeo + Áudio (MP4)",
            style="AccentBlue.TButton",
            command=self._start_youtube_download,
        )
        self.btn_yt_download.grid(row=1, column=2, pady=2)

        # Card 1: Pastas de Origem e Saída
        folders_card = self._create_card(self.root)
        folders_card.columnconfigure(1, weight=1)

        ttk.Label(
            folders_card,
            text="1. Pastas de Origem e Saída",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        ttk.Label(
            folders_card,
            text="Pasta com os Vídeos (Origem):",
            style="CardLabel.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)

        self.input_entry = ttk.Entry(folders_card, textvariable=self.input_dir_var, style="Dark.TEntry")
        self.input_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=4)
        self.input_entry.bind("<Return>", lambda _event: self._start_scan())

        self.btn_browse_input = ttk.Button(
            folders_card,
            text="Selecionar Pasta...",
            style="Secondary.TButton",
            command=self._choose_input_dir,
        )
        self.btn_browse_input.grid(row=1, column=2, padx=(0, 6), pady=4)

        self.btn_reload = ttk.Button(
            folders_card,
            text="Recarregar",
            style="Secondary.TButton",
            command=self._start_scan,
        )
        self.btn_reload.grid(row=1, column=3, pady=4)

        ttk.Label(
            folders_card,
            text="Pasta de Destino (Saída):",
            style="CardLabel.TLabel",
        ).grid(row=2, column=0, sticky="w", padx=(0, 10), pady=4)

        self.output_entry = ttk.Entry(folders_card, textvariable=self.output_dir_var, style="Dark.TEntry")
        self.output_entry.grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=4)

        self.btn_browse_output = ttk.Button(
            folders_card,
            text="Selecionar Pasta...",
            style="Secondary.TButton",
            command=self._choose_output_dir,
        )
        self.btn_browse_output.grid(row=2, column=2, padx=(0, 6), pady=4)

        self.btn_open_output_top = ttk.Button(
            folders_card,
            text="Abrir Pasta",
            style="Secondary.TButton",
            command=self._open_output_dir,
        )
        self.btn_open_output_top.grid(row=2, column=3, pady=4)

        # Card 2: Formato e Configurações de Eficiência
        options_card = self._create_card(self.root)
        options_card.columnconfigure(0, weight=3)
        options_card.columnconfigure(1, weight=2)

        ttk.Label(
            options_card,
            text="2. Formato e Configurações de Eficiência",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(
            options_card,
            text="Formato / Perfil de Eficiência (MP4):",
            style="CardLabel.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=(0, 14), pady=(0, 4))

        ttk.Label(
            options_card,
            text="Resolução Máxima:",
            style="CardLabel.TLabel",
        ).grid(row=1, column=1, sticky="w", pady=(0, 4))

        self.profile_combo = ttk.Combobox(
            options_card,
            textvariable=self.profile_name_var,
            values=self.profile_names,
            state="readonly",
            style="Dark.TCombobox",
        )
        self.profile_combo.grid(row=2, column=0, sticky="ew", padx=(0, 14))
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_changed)

        self.resolution_combo = ttk.Combobox(
            options_card,
            textvariable=self.resolution_var,
            values=self.resolution_labels,
            state="readonly",
            style="Dark.TCombobox",
        )
        self.resolution_combo.grid(row=2, column=1, sticky="ew")

        self.profile_desc_label = ttk.Label(
            options_card,
            textvariable=self.profile_desc_var,
            style="CardMuted.TLabel",
            wraplength=920,
        )
        self.profile_desc_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 8))

        checks_row = ttk.Frame(options_card, style="Card.TFrame")
        checks_row.grid(row=4, column=0, columnspan=2, sticky="w")

        self.chk_recursive = ttk.Checkbutton(
            checks_row,
            text="Incluir subpastas",
            variable=self.recursive_var,
            style="Dark.TCheckbutton",
            command=self._on_recursive_toggled,
        )
        self.chk_recursive.pack(side="left", padx=(0, 20))

        self.chk_skip = ttk.Checkbutton(
            checks_row,
            text="Pular vídeos já existentes na pasta de saída",
            variable=self.skip_existing_var,
            style="Dark.TCheckbutton",
        )
        self.chk_skip.pack(side="left", padx=(0, 20))

        self.chk_prevent_larger = ttk.Checkbutton(
            checks_row,
            text="Impedir que o vídeo final fique maior que o original",
            variable=self.prevent_larger_var,
            style="Dark.TCheckbutton",
        )
        self.chk_prevent_larger.pack(side="left")

        # Card 3: Lista de Vídeos (expande com a janela)
        list_border = tk.Frame(self.root, bg=BORDER_COLOR, bd=0, highlightthickness=0)
        list_border.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        list_card = ttk.Frame(list_border, style="Card.TFrame", padding=(14, 12))
        list_card.pack(fill="both", expand=True, padx=1, pady=1)

        list_header = ttk.Frame(list_card, style="Card.TFrame")
        list_header.pack(fill="x", pady=(0, 8))

        ttk.Label(
            list_header,
            text="3. Fila de Vídeos para Conversão",
            style="CardTitle.TLabel",
        ).pack(side="left")

        ttk.Label(
            list_header,
            text="Dica: clique duas vezes em um vídeo para ver detalhes",
            style="CardMuted.TLabel",
        ).pack(side="right")

        tree_container = ttk.Frame(list_card, style="Card.TFrame")
        tree_container.pack(fill="both", expand=True)
        tree_container.rowconfigure(0, weight=1)
        tree_container.columnconfigure(0, weight=1)

        columns = ("arquivo", "duracao", "original", "status", "final", "economia")
        self.tree = ttk.Treeview(
            tree_container,
            columns=columns,
            show="headings",
            style="Dark.Treeview",
            selectmode="browse",
        )
        self.tree.heading("arquivo", text="Arquivo", anchor="w")
        self.tree.heading("duracao", text="Duração", anchor="center")
        self.tree.heading("original", text="Tamanho Original", anchor="e")
        self.tree.heading("status", text="Status / Progresso", anchor="w")
        self.tree.heading("final", text="Tamanho Final", anchor="e")
        self.tree.heading("economia", text="Economia", anchor="e")

        self.tree.column("arquivo", width=320, minwidth=180, anchor="w", stretch=True)
        self.tree.column("duracao", width=85, minwidth=70, anchor="center", stretch=False)
        self.tree.column("original", width=120, minwidth=95, anchor="e", stretch=False)
        self.tree.column("status", width=200, minwidth=150, anchor="w", stretch=False)
        self.tree.column("final", width=115, minwidth=95, anchor="e", stretch=False)
        self.tree.column("economia", width=150, minwidth=120, anchor="e", stretch=False)

        self.tree.tag_configure("odd", background="#131A29")
        self.tree.tag_configure("even", background=BG_INPUT)
        self.tree.tag_configure("converting", foreground="#60A5FA")
        self.tree.tag_configure("done", foreground="#34D399")
        self.tree.tag_configure("skipped", foreground=ACCENT_AMBER)
        self.tree.tag_configure("error", foreground="#F87171")
        self.tree.tag_configure("cancelled", foreground=TEXT_SECONDARY)

        self.tree.bind("<Double-1>", self._on_tree_double_click)

        v_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=v_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")

        # Rodapé: Progresso e Botões de Ação
        footer_card = self._create_card(self.root, pady=(0, 14))
        footer_card.columnconfigure(0, weight=1)

        progress_area = ttk.Frame(footer_card, style="Card.TFrame")
        progress_area.grid(row=0, column=0, sticky="ew", padx=(0, 16))
        progress_area.columnconfigure(0, weight=1)

        ttk.Label(
            progress_area,
            textvariable=self.current_file_label_var,
            style="CardMuted.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 3))

        self.current_progress_bar = ttk.Progressbar(
            progress_area,
            variable=self.current_progress_var,
            maximum=100.0,
            mode="determinate",
            style="File.Horizontal.TProgressbar",
        )
        self.current_progress_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(
            progress_area,
            textvariable=self.batch_label_var,
            style="CardMuted.TLabel",
        ).grid(row=2, column=0, sticky="w", pady=(0, 3))

        self.batch_progress_bar = ttk.Progressbar(
            progress_area,
            variable=self.batch_progress_var,
            maximum=100.0,
            mode="determinate",
            style="Batch.Horizontal.TProgressbar",
        )
        self.batch_progress_bar.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        self.summary_label = ttk.Label(
            progress_area,
            textvariable=self.summary_var,
            style="CardLabel.TLabel",
        )
        self.summary_label.grid(row=4, column=0, sticky="w")

        buttons_area = ttk.Frame(footer_card, style="Card.TFrame")
        buttons_area.grid(row=0, column=1, sticky="se")

        self.btn_start = ttk.Button(
            buttons_area,
            text="Iniciar Conversão em Massa",
            style="Primary.TButton",
            command=self._start_conversion,
        )
        self.btn_start.pack(fill="x", pady=(0, 8))

        bottom_row = ttk.Frame(buttons_area, style="Card.TFrame")
        bottom_row.pack(fill="x")

        self.btn_cancel = ttk.Button(
            bottom_row,
            text="Cancelar",
            style="Danger.TButton",
            command=self._cancel_conversion,
        )
        self.btn_cancel.pack(side="left", padx=(0, 8))

        self.btn_open_output_bottom = ttk.Button(
            bottom_row,
            text="Abrir Pasta de Saída",
            style="Secondary.TButton",
            command=self._open_output_dir,
        )
        self.btn_open_output_bottom.pack(side="left")

    def _on_profile_changed(self, _event: object = None) -> None:
        profile_id = self.profile_name_to_id.get(self.profile_name_var.get(), PROFILES[0].id)
        for p in PROFILES:
            if p.id == profile_id:
                self.profile_desc_var.set(p.description)
                break

    def _on_recursive_toggled(self) -> None:
        if self.input_dir_var.get().strip() and not self.is_converting:
            self._start_scan()

    def _choose_input_dir(self) -> None:
        initial = self.input_dir_var.get().strip() or str(Path.home())
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Selecione a pasta que contém os vídeos",
            initialdir=initial if Path(initial).is_dir() else str(Path.home()),
        )
        if not selected:
            return

        normalized = str(Path(selected))
        self.input_dir_var.set(normalized)

        current_out = self.output_dir_var.get().strip()
        if not current_out or current_out == self._auto_output_dir:
            auto_out = str(Path(normalized) / "Convertidos_MP4")
            self._auto_output_dir = auto_out
            self.output_dir_var.set(auto_out)

        self._start_scan()

    def _choose_output_dir(self) -> None:
        initial = self.output_dir_var.get().strip() or self.input_dir_var.get().strip() or str(Path.home())
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Selecione a pasta de saída para os vídeos convertidos",
            initialdir=initial if Path(initial).is_dir() else str(Path.home()),
        )
        if selected:
            self.output_dir_var.set(str(Path(selected)))
            self._auto_output_dir = None

    def _open_output_dir(self) -> None:
        raw_out = self.output_dir_var.get().strip()
        if not raw_out:
            messagebox.showinfo(
                "Pasta de Saída",
                "Selecione ou informe uma pasta de saída primeiro.",
                parent=self.root,
            )
            return

        out_path = Path(raw_out)
        if not out_path.exists():
            try:
                out_path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                messagebox.showerror(
                    "Erro ao Abrir Pasta",
                    f"Não foi possível acessar ou criar a pasta:\n{out_path}\n\n{exc}",
                    parent=self.root,
                )
                return

        if os.name == "nt":
            os.startfile(str(out_path))  # type: ignore[attr-defined]
        else:
            messagebox.showinfo("Pasta de Saída", str(out_path), parent=self.root)

    def _start_scan(self) -> None:
        if self.is_converting:
            return
        raw_input = self.input_dir_var.get().strip()
        if not raw_input:
            return

        input_path = Path(raw_input)
        if not input_path.is_dir():
            messagebox.showwarning(
                "Pasta Inválida",
                f"A pasta de origem informada não existe:\n{input_path}",
                parent=self.root,
            )
            return

        raw_output = self.output_dir_var.get().strip() or None
        recursive = self.recursive_var.get()
        self._scan_generation += 1
        generation = self._scan_generation
        self.is_scanning = True
        self.summary_var.set("Analisando vídeos na pasta selecionada...")
        self._update_controls_state()

        def _worker() -> None:
            found = scan_videos(
                input_dir=input_path,
                recursive=recursive,
                output_dir=raw_output,
                probe_durations=True,
            )
            self.ui_queue.put(("scan_done", (generation, found)))

        threading.Thread(target=_worker, daemon=True).start()

    def _populate_tree(self, items: list[VideoItem]) -> None:
        self.items = items
        self.tree_item_ids.clear()
        for row_id in self.tree.get_children():
            self.tree.delete(row_id)

        for idx, item in enumerate(self.items):
            base_tag = "even" if idx % 2 == 0 else "odd"
            row_id = self.tree.insert(
                "",
                "end",
                values=(
                    str(item.relative_path),
                    format_duration(item.duration_seconds),
                    format_size(item.size_bytes),
                    item.status,
                    "—",
                    "—",
                ),
                tags=(base_tag,),
            )
            self.tree_item_ids.append(row_id)

        total_bytes = sum(i.size_bytes for i in self.items)
        self.current_progress_var.set(0.0)
        self.batch_progress_var.set(0.0)
        self.current_file_label_var.set("Arquivo atual: aguardando início")
        self.batch_label_var.set(f"Progresso do lote: 0 de {len(self.items)} vídeos")
        if self.items:
            self.summary_var.set(
                f"Vídeos encontrados: {len(self.items)} | Tamanho total original: {format_size(total_bytes)}"
            )
        else:
            self.summary_var.set("Nenhum vídeo compatível foi encontrado na pasta selecionada.")

    def _update_tree_row(self, idx: int, item: VideoItem) -> None:
        if idx < 0 or idx >= len(self.tree_item_ids):
            return
        row_id = self.tree_item_ids[idx]
        final_str = format_size(item.output_size_bytes) if item.output_size_bytes > 0 else "—"
        savings_str = (
            format_savings(item.size_bytes, item.output_size_bytes)
            if item.output_size_bytes > 0
            else "—"
        )
        self.tree.item(
            row_id,
            values=(
                str(item.relative_path),
                format_duration(item.duration_seconds),
                format_size(item.size_bytes),
                item.status,
                final_str,
                savings_str,
            ),
        )

        base_tag = "even" if idx % 2 == 0 else "odd"
        status_lower = item.status.lower()
        if status_lower.startswith("convertendo"):
            self.tree.item(row_id, tags=(base_tag, "converting"))
            self.tree.see(row_id)
        elif status_lower.startswith("concluído"):
            self.tree.item(row_id, tags=(base_tag, "done"))
        elif status_lower.startswith("pulado"):
            self.tree.item(row_id, tags=(base_tag, "skipped"))
        elif status_lower.startswith("erro"):
            self.tree.item(row_id, tags=(base_tag, "error"))
        elif status_lower.startswith("cancelado"):
            self.tree.item(row_id, tags=(base_tag, "cancelled"))
        else:
            self.tree.item(row_id, tags=(base_tag,))

    def _start_conversion(self) -> None:
        if self.is_converting or self.is_scanning:
            return

        if not self.ffmpeg_path:
            messagebox.showerror(
                "FFmpeg Não Encontrado",
                "O executável bin\\ffmpeg.exe não foi encontrado.",
                parent=self.root,
            )
            return

        raw_input = self.input_dir_var.get().strip()
        raw_output = self.output_dir_var.get().strip()
        if not raw_input or not Path(raw_input).is_dir():
            messagebox.showwarning(
                "Pasta de Origem",
                "Selecione uma pasta de origem válida com vídeos.",
                parent=self.root,
            )
            return

        if not raw_output:
            messagebox.showwarning(
                "Pasta de Saída",
                "Selecione ou informe uma pasta de saída para os vídeos convertidos.",
                parent=self.root,
            )
            return

        if not self.items:
            messagebox.showinfo(
                "Nenhum Vídeo",
                "Não há vídeos listados na fila para converter.",
                parent=self.root,
            )
            return

        # Reinicia status visual antes de iniciar novo lote
        for idx, item in enumerate(self.items):
            item.status = "Na fila"
            item.progress = 0.0
            item.output_size_bytes = 0
            item.error_message = ""
            item.note = ""
            self._update_tree_row(idx, item)

        settings = ConversionSettings(
            profile_id=self.profile_name_to_id.get(self.profile_name_var.get(), PROFILES[0].id),
            resolution=self.resolution_label_to_id.get(self.resolution_var.get(), "original"),
            recursive=self.recursive_var.get(),
            skip_existing=self.skip_existing_var.get(),
            prevent_larger=self.prevent_larger_var.get(),
        )

        self.cancel_event.clear()
        self.is_converting = True
        self.current_progress_var.set(0.0)
        self.batch_progress_var.set(0.0)
        self.batch_label_var.set(f"Progresso do lote: 0 de {len(self.items)} vídeos")
        self.summary_var.set("Conversão em andamento...")
        self._update_controls_state()

        items_ref = self.items
        output_path = Path(raw_output)

        def _worker() -> None:
            def _on_item_update(idx: int, updated_item: VideoItem) -> None:
                self.ui_queue.put(("item_update", (idx, updated_item)))

            def _on_batch_progress(done_count: int, total_count: int) -> None:
                self.ui_queue.put(("batch_progress", (done_count, total_count)))

            summary = convert_batch(
                items=items_ref,
                output_dir=output_path,
                settings=settings,
                cancel_event=self.cancel_event,
                on_item_update=_on_item_update,
                on_batch_progress=_on_batch_progress,
            )
            self.ui_queue.put(("batch_done", summary))

        threading.Thread(target=_worker, daemon=True).start()

    def _start_youtube_download(self) -> None:
        if self.is_converting or self.is_scanning or self.is_downloading:
            return

        raw_url = self.youtube_url_var.get().strip()
        if not raw_url:
            messagebox.showwarning(
                "URL do YouTube",
                "Cole a URL de um vídeo do YouTube para baixar com vídeo e áudio.",
                parent=self.root,
            )
            return

        if not self.ffmpeg_path:
            messagebox.showerror(
                "FFmpeg Não Encontrado",
                "O executável bin\\ffmpeg.exe é necessário para mesclar vídeo e áudio.",
                parent=self.root,
            )
            return

        raw_input = self.input_dir_var.get().strip()
        if raw_input:
            download_dir = Path(raw_input)
        else:
            download_dir = get_app_dir() / "downloads"
            self.input_dir_var.set(str(download_dir))
            if not self.output_dir_var.get().strip():
                auto_out = str(download_dir / "Convertidos_MP4")
                self._auto_output_dir = auto_out
                self.output_dir_var.set(auto_out)

        self.cancel_event.clear()
        self.is_downloading = True
        self.current_progress_var.set(0.0)
        self.current_file_label_var.set("YouTube: iniciando download (vídeo + áudio)...")
        self.summary_var.set("Baixando vídeo do YouTube com mesclagem MP4 (H.264 + AAC)...")
        self._update_controls_state()

        def _worker() -> None:
            def _on_yt_progress(pct: float, msg: str) -> None:
                self.ui_queue.put(("yt_progress", (pct, msg)))

            result = download_youtube_video(
                url=raw_url,
                output_dir=download_dir,
                on_progress=_on_yt_progress,
                cancel_event=self.cancel_event,
            )
            self.ui_queue.put(("yt_done", (download_dir, result)))

        threading.Thread(target=_worker, daemon=True).start()

    def _handle_youtube_done(self, download_dir: Path, result: DownloadResult) -> None:
        self.is_downloading = False
        self._update_controls_state()

        if result.cancelled:
            self.current_file_label_var.set("Arquivo atual: download cancelado")
            self.summary_var.set("Download do YouTube cancelado pelo usuário.")
            return

        if not result.success or not result.file_path:
            self.current_file_label_var.set("Arquivo atual: falha no download do YouTube")
            self.summary_var.set("Erro ao baixar do YouTube.")
            messagebox.showerror(
                "Erro no Download do YouTube",
                f"Não foi possível concluir o download com vídeo + áudio:\n\n{result.error_message}",
                parent=self.root,
            )
            return

        self.current_progress_var.set(100.0)
        self.current_file_label_var.set(f"YouTube concluído: {result.file_path.name}")
        self.youtube_url_var.set("")
        self.summary_var.set(
            f"Download pronto: {result.file_path.name} ({format_size(result.size_bytes)}) "
            f"| Vídeo: {result.video_codec.upper()} | Áudio: {result.audio_codec.upper()}"
        )
        self._start_scan()
        messagebox.showinfo(
            "Download Concluído (Vídeo + Áudio)",
            f"Vídeo baixado com vídeo e áudio funcionais!\n\n"
            f"Arquivo: {result.file_path.name}\n"
            f"Pasta: {download_dir}\n"
            f"Duração: {format_duration(result.duration_seconds)}\n"
            f"Tamanho: {format_size(result.size_bytes)}\n"
            f"Codecs: {result.video_codec.upper()} + {result.audio_codec.upper()}",
            parent=self.root,
        )

    def _cancel_conversion(self) -> None:
        if not (self.is_converting or self.is_downloading):
            return
        self.cancel_event.set()
        self.btn_cancel.configure(state="disabled")
        self.summary_var.set("Cancelando operação em andamento...")

    def _update_live_summary(self, done_count: int, total_count: int) -> None:
        processed_in = sum(i.size_bytes for i in self.items if i.output_size_bytes > 0)
        processed_out = sum(i.output_size_bytes for i in self.items if i.output_size_bytes > 0)
        if processed_in > 0:
            savings_text = format_savings(processed_in, processed_out)
            self.summary_var.set(
                f"Vídeos: {done_count}/{total_count} | Original: {format_size(processed_in)} | "
                f"Convertido: {format_size(processed_out)} | Economia: {savings_text}"
            )
        else:
            self.summary_var.set(f"Vídeos processados: {done_count}/{total_count}")

    def _process_ui_queue(self) -> None:
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "scan_done":
                    generation, found_items = payload
                    if generation == self._scan_generation:
                        self.is_scanning = False
                        self._populate_tree(found_items)
                        self._update_controls_state()
                elif kind == "item_update":
                    idx, item = payload
                    self._update_tree_row(idx, item)
                    if item.status.startswith("Convertendo"):
                        self.current_file_label_var.set(f"Arquivo atual: {item.relative_path}")
                        self.current_progress_var.set(item.progress)
                elif kind == "batch_progress":
                    done_count, total_count = payload
                    pct = (done_count / total_count) * 100.0 if total_count > 0 else 0.0
                    self.batch_progress_var.set(pct)
                    self.batch_label_var.set(f"Progresso do lote: {done_count} de {total_count} vídeos")
                    self._update_live_summary(done_count, total_count)
                elif kind == "batch_done":
                    self._handle_batch_done(payload)
                elif kind == "yt_progress":
                    pct, msg = payload
                    self.current_progress_var.set(pct)
                    self.current_file_label_var.set(f"YouTube: {msg} ({pct:.0f}%)")
                elif kind == "yt_done":
                    download_dir, yt_res = payload
                    self._handle_youtube_done(download_dir, yt_res)
        except queue.Empty:
            pass
        finally:
            if self.root.winfo_exists():
                self.root.after(80, self._process_ui_queue)

    def _handle_batch_done(self, summary: BatchSummary) -> None:
        self.is_converting = False
        self._update_controls_state()

        if summary.cancelled:
            self.current_file_label_var.set("Arquivo atual: conversão cancelada pelo usuário")
        else:
            self.current_progress_var.set(100.0)
            self.batch_progress_var.set(100.0)
            self.current_file_label_var.set("Arquivo atual: lote finalizado")

        savings_str = format_savings(summary.total_input_bytes, summary.total_output_bytes)
        self.summary_var.set(
            f"Concluídos: {summary.completed} | Pulados: {summary.skipped} | Erros: {summary.failed} | "
            f"Original: {format_size(summary.total_input_bytes)} | "
            f"Convertido: {format_size(summary.total_output_bytes)} | Economia: {savings_str}"
        )

        if summary.cancelled:
            messagebox.showinfo(
                "Conversão Cancelada",
                f"A conversão foi interrompida.\n"
                f"Concluídos antes do cancelamento: {summary.completed}\n"
                f"Espaço economizado até aqui: {savings_str}",
                parent=self.root,
            )
        elif summary.failed > 0:
            messagebox.showwarning(
                "Conversão Finalizada com Avisos",
                f"Conversão concluída em {summary.elapsed_seconds:.1f}s.\n\n"
                f"Convertidos: {summary.completed}\n"
                f"Pulados: {summary.skipped}\n"
                f"Erros: {summary.failed} (clique duas vezes nos itens em vermelho para ver detalhes)\n"
                f"Economia total: {savings_str}",
                parent=self.root,
            )
        else:
            messagebox.showinfo(
                "Conversão Concluída",
                f"Lote concluído em {summary.elapsed_seconds:.1f}s!\n\n"
                f"Vídeos convertidos: {summary.completed}\n"
                f"Pulados: {summary.skipped}\n"
                f"Tamanho original: {format_size(summary.total_input_bytes)}\n"
                f"Tamanho final: {format_size(summary.total_output_bytes)}\n"
                f"Economia total: {savings_str}",
                parent=self.root,
            )

    def _on_tree_double_click(self, _event: object = None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row_id = selection[0]
        try:
            idx = self.tree_item_ids.index(row_id)
        except ValueError:
            return
        item = self.items[idx]
        lines = [
            f"Origem: {item.source_path}",
            f"Duração: {format_duration(item.duration_seconds)}",
            f"Tamanho original: {format_size(item.size_bytes)}",
            f"Status: {item.status}",
        ]
        if item.output_path:
            lines.append(f"Destino MP4: {item.output_path}")
        if item.output_size_bytes > 0:
            lines.append(f"Tamanho final: {format_size(item.output_size_bytes)}")
            lines.append(f"Economia: {format_savings(item.size_bytes, item.output_size_bytes)}")
        if item.error_message:
            lines.append(f"\nDetalhes do erro:\n{item.error_message}")
        messagebox.showinfo("Detalhes do Vídeo", "\n".join(lines), parent=self.root)

    def _update_controls_state(self) -> None:
        busy = self.is_converting or self.is_scanning or self.is_downloading
        state_idle = "disabled" if busy else "normal"
        combo_state = "disabled" if busy else "readonly"

        self.yt_url_entry.configure(state=state_idle)
        self.btn_yt_download.configure(state=state_idle)
        self.input_entry.configure(state=state_idle)
        self.output_entry.configure(state=state_idle)
        self.btn_browse_input.configure(state=state_idle)
        self.btn_browse_output.configure(state=state_idle)
        self.btn_reload.configure(state=state_idle)
        self.profile_combo.configure(state=combo_state)
        self.resolution_combo.configure(state=combo_state)
        self.chk_recursive.configure(state=state_idle)
        self.chk_skip.configure(state=state_idle)
        self.chk_prevent_larger.configure(state=state_idle)

        if self.is_converting or self.is_downloading:
            self.btn_start.configure(state="disabled")
            self.btn_cancel.configure(state="normal")
        else:
            start_state = "normal" if (self.items and not self.is_scanning and self.ffmpeg_path) else "disabled"
            self.btn_start.configure(state=start_state)
            self.btn_cancel.configure(state="disabled")

    def _on_close(self) -> None:
        if self.is_converting or self.is_downloading:
            confirm = messagebox.askyesno(
                "Operação em Andamento",
                "Há um processo em andamento. Deseja cancelar e fechar o aplicativo?",
                parent=self.root,
            )
            if not confirm:
                return
            self.cancel_event.set()
        self.root.destroy()


def run_self_test() -> int:
    """Instancia a interface, valida componentes principais e encerra com código 0."""
    _enable_dpi_awareness()
    root = tk.Tk()
    app = VideoConverterApp(root)
    root.update_idletasks()
    root.update()

    assert app.ffmpeg_path is not None and app.ffmpeg_path.is_file(), "FFmpeg não encontrado"
    assert len(app.profile_combo["values"]) == len(PROFILES), "Quantidade de perfis divergente"
    assert len(app.resolution_combo["values"]) == len(RESOLUTION_OPTIONS), "Resoluções divergentes"
    assert app.skip_existing_var.get() is True
    assert app.prevent_larger_var.get() is True
    assert app.yt_url_entry is not None and app.btn_yt_download is not None

    root.destroy()
    print("SELF_TEST_OK")
    return 0


def main() -> int:
    """Ponto de entrada da aplicação."""
    if "--self-test" in sys.argv:
        return run_self_test()

    _enable_dpi_awareness()
    root = tk.Tk()
    VideoConverterApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
