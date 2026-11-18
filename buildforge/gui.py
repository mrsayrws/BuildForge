from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, __version__
from .detect import KIND_DESCRIPTIONS, Project, detect_project
from .diagnostics import Problem, counts, parse_log
from .runner import BuildRunner, Plan, default_jobs, make_plan
from .store import Store
from .toolchains import ToolStatus, missing_for_project, scan

BG = "#0a0e0c"
CARD = "#0f1512"
CARD2 = "#141d18"
LINE = "#1e2d26"
TXT = "#d6e5da"
DIM = "#7b9b8a"
GREEN = "#3dff8f"
RED = "#ff5470"
AMBER = "#ffc857"
BLUE = "#5cc8ff"

ERRORISH = re.compile(r"\b(error|fatal)\b", re.IGNORECASE)
WARNISH = re.compile(r"\bwarning\b", re.IGNORECASE)
MAX_LOG_LINES = 30000


class App(tk.Tk):
    def __init__(self, store: Store | None = None):
        super().__init__()
        self.store = store or Store()
        self.queue: queue.Queue = queue.Queue()
        self.project: Project | None = None
        self.plan: Plan | None = None
        self.runner: BuildRunner | None = None
        self.running = False
        self.raw_lines: list[str] = []
        self.problems: list[Problem] = []
        self.tools: list[ToolStatus] = []
        self.tools_scanned = False
        self.build_seconds = 0.0

        self.title(f"{APP_NAME} {__version__} — universal build console")
        self.geometry(self.store.data.get("window") or "1180x760")
        self.minsize(980, 620)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._init_style()
        self._build_ui()
        self._load_projects()
        self.after(60, self._drain)
        self.after(200, self._scan_tools_async)
        self._update_actions()

    # ------------------------------------------------------------------ style

    def _init_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TXT, fieldbackground=CARD,
                        bordercolor=LINE, lightcolor=LINE, darkcolor=LINE,
                        focuscolor=BG, font=("Segoe UI", 9))
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Tool.TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TXT)
        style.configure("Card.TLabel", background=CARD, foreground=TXT)
        style.configure("Dim.TLabel", background=BG, foreground=DIM)
        style.configure("CardDim.TLabel", background=CARD, foreground=DIM)
        style.configure("H1.TLabel", background=BG, foreground=TXT,
                        font=("Segoe UI Semibold", 14))
        style.configure("Badge.TLabel", background=CARD2, foreground=GREEN,
                        font=("Consolas", 9), padding=(8, 3))
        style.configure("TButton", background=CARD2, foreground=TXT, borderwidth=0,
                        padding=(12, 6), focusthickness=0)
        style.map("TButton",
                  background=[("active", LINE), ("disabled", CARD)],
                  foreground=[("disabled", "#4a5f55")])
        style.configure("Accent.TButton", background=GREEN, foreground="#04120a",
                        font=("Segoe UI Semibold", 10), padding=(20, 8))
        style.map("Accent.TButton",
                  background=[("active", "#5dffa3"), ("disabled", "#24402f")],
                  foreground=[("disabled", "#5c7a68")])
        style.configure("Danger.TButton", background="#2a1219", foreground=RED,
                        padding=(16, 8))
        style.map("Danger.TButton",
                  background=[("active", "#3d1823"), ("disabled", CARD)],
                  foreground=[("disabled", "#5a3a44")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG, foreground=DIM,
                        padding=(16, 8), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", CARD)],
                  foreground=[("selected", GREEN)])
        style.configure("Treeview", background=CARD, fieldbackground=CARD,
                        foreground=TXT, rowheight=24, borderwidth=0,
                        font=("Consolas", 9))
        style.map("Treeview",
                  background=[("selected", "#1b3527")],
                  foreground=[("selected", GREEN)])
        style.configure("Treeview.Heading", background=CARD2, foreground=DIM,
                        borderwidth=0, font=("Segoe UI Semibold", 8))
        style.map("Treeview.Heading", background=[("active", LINE)])
        style.configure("TCombobox", fieldbackground=CARD2, background=CARD2,
                        foreground=TXT, arrowcolor=DIM, padding=(8, 5))
        style.map("TCombobox",
                  fieldbackground=[("readonly", CARD2)],
                  foreground=[("readonly", TXT)])
        style.configure("TSpinbox", fieldbackground=CARD2, background=CARD2,
                        foreground=TXT, arrowcolor=DIM, padding=(6, 5))
        style.configure("TCheckbutton", background=BG, foreground=TXT)
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("Slim.Horizontal.TProgressbar", background=GREEN,
                        troughcolor=CARD2, borderwidth=0)
        self.option_add("*TCombobox*Listbox.background", CARD2)
        self.option_add("*TCombobox*Listbox.foreground", TXT)
        self.option_add("*TCombobox*Listbox.selectBackground", "#1b3527")
        self.option_add("*TCombobox*Listbox.selectForeground", GREEN)

    # --------------------------------------------------------------------- ui

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=CARD, height=62)
        header.pack(side="top", fill="x")
        header.pack_propagate(False)
        tk.Frame(self, bg=LINE, height=1).pack(side="top", fill="x")

        brand = tk.Frame(header, bg=CARD)
        brand.pack(side="left", padx=(18, 8))
        tk.Label(brand, text="BUILD", font=("Consolas", 15, "bold"),
                 fg=GREEN, bg=CARD).pack(side="left")
        tk.Label(brand, text="FORGE", font=("Consolas", 15, "bold"),
                 fg=TXT, bg=CARD).pack(side="left")
        tk.Label(brand, text=f"v{__version__}", font=("Consolas", 8),
                 fg=DIM, bg=CARD).pack(side="left", anchor="s", padx=(8, 0), pady=(0, 3))

        self.path_var = tk.StringVar()
        self.path_box = tk.Entry(header, textvariable=self.path_var, bg=CARD2,
                                 fg=TXT, insertbackground=GREEN, relief="flat",
                                 font=("Consolas", 9))
        self.path_box.pack(side="left", fill="x", expand=True, padx=(10, 6), ipady=7)
        self.path_box.bind("<Return>", lambda _e: self._open_typed_path())

        ttk.Button(header, text="Add folder…", command=self._add_project).pack(
            side="left", padx=(0, 6))
        ttk.Button(header, text="Rename", command=self._rename_project).pack(
            side="left", padx=(0, 6))
        ttk.Button(header, text="Settings", command=self._open_settings).pack(
            side="left", padx=(0, 14))

        status = tk.Frame(self, bg=CARD, height=28)
        status.pack(side="bottom", fill="x")
        status.pack_propagate(False)
        tk.Frame(self, bg=LINE, height=1).pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(status, textvariable=self.status_var, font=("Consolas", 9),
                 fg=DIM, bg=CARD).pack(side="left", padx=14)
        self.stats_var = tk.StringVar(value="")
        tk.Label(status, textvariable=self.stats_var, font=("Consolas", 9),
                 fg=DIM, bg=CARD).pack(side="right", padx=14)

        body = tk.Frame(self, bg=BG)
        body.pack(side="top", fill="both", expand=True)

        side = tk.Frame(body, bg=BG, width=236)
        side.pack(side="left", fill="y", padx=(14, 0), pady=12)
        side.pack_propagate(False)
        tk.Label(side, text="PROJECTS", font=("Segoe UI Semibold", 8),
                 fg=DIM, bg=BG).pack(anchor="w", pady=(0, 6))
        list_wrap = tk.Frame(side, bg=CARD, highlightthickness=1,
                             highlightbackground=LINE)
        list_wrap.pack(fill="both", expand=True)
        self.project_list = tk.Listbox(
            list_wrap, bg=CARD, fg=TXT, selectbackground="#1b3527",
            selectforeground=GREEN, activestyle="none", relief="flat",
            highlightthickness=0, font=("Consolas", 9), borderwidth=0)
        self.project_list.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        bar = tk.Scrollbar(list_wrap, command=self.project_list.yview,
                           bg=CARD, troughcolor=CARD, activebackground=LINE,
                           relief="flat", borderwidth=0)
        bar.pack(side="right", fill="y")
        self.project_list.configure(yscrollcommand=bar.set)
        self.project_list.bind("<<ListboxSelect>>", self._on_select_project)
        self.project_list.bind("<Delete>", lambda _e: self._remove_project())

        side_actions = tk.Frame(side, bg=BG)
        side_actions.pack(fill="x", pady=(8, 0))
        ttk.Button(side_actions, text="+ Add", command=self._add_project).pack(
            side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(side_actions, text="− Remove", command=self._remove_project).pack(
            side="left", fill="x", expand=True, padx=(4, 0))

        tk.Label(side, text="Tip: double-click a problem to jump\n"
                            "to the exact line in VS Code.",
                 font=("Segoe UI", 8), fg=DIM, bg=BG, justify="left").pack(
            anchor="w", pady=(10, 0))

        main = tk.Frame(body, bg=BG)
        main.pack(side="left", fill="both", expand=True, padx=14, pady=12)

        info = tk.Frame(main, bg=BG)
        info.pack(fill="x")
        title_row = tk.Frame(info, bg=BG)
        title_row.pack(fill="x")
        self.project_title = tk.Label(title_row, text="No project selected",
                                      font=("Segoe UI Semibold", 14), fg=TXT, bg=BG)
        self.project_title.pack(side="left")
        self.kind_badge = tk.Label(title_row, text="", font=("Consolas", 9),
                                   fg=GREEN, bg=CARD2, padx=8, pady=3)
        self.kind_badge.pack(side="left", padx=(10, 0))
        self.project_path = tk.Label(info, text="Add a project folder to begin.",
                                     font=("Consolas", 8), fg=DIM, bg=BG)
        self.project_path.pack(anchor="w", pady=(2, 0))
        self.kind_desc = tk.Label(info, text="", font=("Segoe UI", 8), fg=DIM, bg=BG)
        self.kind_desc.pack(anchor="w")

        actions = tk.Frame(main, bg=BG)
        actions.pack(fill="x", pady=(10, 10))
        self.release_var = tk.BooleanVar(value=bool(self.store.data.get("release", True)))
        self.config_var = tk.StringVar(value="Release" if self.release_var.get() else "Debug")
        self.config_box = ttk.Combobox(actions, textvariable=self.config_var, width=9,
                                       state="readonly", values=["Release", "Debug"])
        self.config_box.pack(side="left")
        self.config_box.bind("<<ComboboxSelected>>", self._on_config_change)

        tk.Label(actions, text="jobs", font=("Segoe UI", 8), fg=DIM, bg=BG).pack(
            side="left", padx=(14, 4))
        self.jobs_var = tk.StringVar(value=str(self.store.data.get("jobs") or default_jobs()))
        self.jobs_box = ttk.Spinbox(actions, from_=1, to=64, width=4,
                                    textvariable=self.jobs_var, command=self._save_jobs)
        self.jobs_box.pack(side="left")

        self.clean_var = tk.BooleanVar(value=bool(self.store.data.get("clean", False)))
        ttk.Checkbutton(actions, text="clean first", variable=self.clean_var,
                        command=lambda: self.store.set("clean", self.clean_var.get())
                        ).pack(side="left", padx=(14, 0))

        self.stop_btn = ttk.Button(actions, text="STOP", style="Danger.TButton",
                                   command=self._stop_build, state="disabled")
        self.stop_btn.pack(side="right")
        self.build_btn = ttk.Button(actions, text="BUILD", style="Accent.TButton",
                                    command=self._start_build)
        self.build_btn.pack(side="right", padx=(0, 8))

        self.progress = ttk.Progressbar(main, mode="indeterminate",
                                        style="Slim.Horizontal.TProgressbar")

        self.tabs = ttk.Notebook(main)
        self.tabs.pack(fill="both", expand=True)
        self._build_log_tab()
        self._build_problems_tab()
        self._build_tools_tab()

    def _build_log_tab(self) -> None:
        frame = tk.Frame(self.tabs, bg=CARD)
        self.tabs.add(frame, text="Build")
        toolbar = tk.Frame(frame, bg=CARD)
        toolbar.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(toolbar, text="Live output", font=("Segoe UI Semibold", 8),
                 fg=DIM, bg=CARD).pack(side="left")
        ttk.Button(toolbar, text="Clear", command=self._clear_log).pack(side="right")
        ttk.Button(toolbar, text="Copy log",
                   command=self._copy_log).pack(side="right", padx=(0, 6))

        wrap = tk.Frame(frame, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log_text = tk.Text(wrap, bg="#080b0a", fg=TXT, insertbackground=GREEN,
                                relief="flat", font=("Consolas", 9), wrap="none",
                                borderwidth=0, padx=10, pady=8,
                                selectbackground="#1b3527")
        self.log_text.pack(side="left", fill="both", expand=True)
        yscroll = tk.Scrollbar(wrap, command=self.log_text.yview, bg=CARD,
                               troughcolor=CARD, activebackground=LINE,
                               relief="flat", borderwidth=0)
        yscroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=yscroll.set)
        self.log_text.tag_configure("dim", foreground=DIM)
        self.log_text.tag_configure("err", foreground=RED)
        self.log_text.tag_configure("warn", foreground=AMBER)
        self.log_text.tag_configure("ok", foreground=GREEN)
        self.log_text.tag_configure("step", foreground=BLUE,
                                    font=("Consolas", 9, "bold"))
        self.log_text.tag_configure("head", foreground=GREEN,
                                    font=("Consolas", 9, "bold"))
        self.log_text.configure(state="disabled")

    def _build_problems_tab(self) -> None:
        frame = tk.Frame(self.tabs, bg=CARD)
        self.tabs.add(frame, text="Problems 0")
        self.problems_tab = frame
        toolbar = tk.Frame(frame, bg=CARD)
        toolbar.pack(fill="x", padx=10, pady=(8, 4))
        self.problems_head = tk.Label(toolbar, text="No build yet.",
                                      font=("Segoe UI", 8), fg=DIM, bg=CARD)
        self.problems_head.pack(side="left")
        ttk.Button(toolbar, text="Open at line",
                   command=self._open_selected_problem).pack(side="right")
        ttk.Button(toolbar, text="Analyze log",
                   command=self._analyze_log).pack(side="right", padx=(0, 6))

        paned = tk.PanedWindow(frame, orient="vertical", bg=CARD, sashwidth=6,
                               sashrelief="flat", borderwidth=0)
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        top = tk.Frame(paned, bg=CARD)
        self.problem_tree = ttk.Treeview(
            top, columns=("sev", "code", "where", "msg"), show="headings",
            selectmode="browse")
        self.problem_tree.heading("sev", text="SEV")
        self.problem_tree.heading("code", text="CODE")
        self.problem_tree.heading("where", text="WHERE")
        self.problem_tree.heading("msg", text="MESSAGE")
        self.problem_tree.column("sev", width=80, stretch=False)
        self.problem_tree.column("code", width=96, stretch=False)
        self.problem_tree.column("where", width=270, stretch=False)
        self.problem_tree.column("msg", width=460, stretch=True)
        self.problem_tree.tag_configure("error", foreground=RED)
        self.problem_tree.tag_configure("warning", foreground=AMBER)
        self.problem_tree.tag_configure("note", foreground=DIM)
        ysb = ttk.Scrollbar(top, orient="vertical", command=self.problem_tree.yview)
        self.problem_tree.configure(yscrollcommand=ysb.set)
        self.problem_tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.problem_tree.bind("<<TreeviewSelect>>", self._show_problem)
        self.problem_tree.bind("<Double-1>", lambda _e: self._open_selected_problem())
        paned.add(top, minsize=140, stretch="always")

        detail = tk.Frame(paned, bg="#080b0a")
        self.detail_text = tk.Text(detail, bg="#080b0a", fg=TXT, relief="flat",
                                   font=("Consolas", 9), wrap="word", borderwidth=0,
                                   padx=12, pady=10, state="disabled",
                                   selectbackground="#1b3527")
        dsb = ttk.Scrollbar(detail, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=dsb.set)
        self.detail_text.pack(side="left", fill="both", expand=True)
        dsb.pack(side="right", fill="y")
        self.detail_text.tag_configure("label", foreground=GREEN,
                                       font=("Consolas", 9, "bold"))
        self.detail_text.tag_configure("dim", foreground=DIM)
        paned.add(detail, minsize=120, stretch="always")

    def _build_tools_tab(self) -> None:
        frame = tk.Frame(self.tabs, bg=CARD)
        self.tabs.add(frame, text="Toolchains")
        toolbar = tk.Frame(frame, bg=CARD)
        toolbar.pack(fill="x", padx=10, pady=(8, 4))
        self.tools_head = tk.Label(toolbar, text="Scanning toolchains…",
                                   font=("Segoe UI", 8), fg=DIM, bg=CARD)
        self.tools_head.pack(side="left")
        ttk.Button(toolbar, text="Rescan",
                   command=self._scan_tools_async).pack(side="right")
        ttk.Button(toolbar, text="Copy install command",
                   command=self._copy_install).pack(side="right", padx=(0, 6))

        top = tk.Frame(frame, bg=CARD)
        top.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.tool_tree = ttk.Treeview(
            top, columns=("status", "tool", "group", "version", "path"),
            show="headings", selectmode="browse")
        self.tool_tree.heading("status", text="")
        self.tool_tree.heading("tool", text="TOOL")
        self.tool_tree.heading("group", text="GROUP")
        self.tool_tree.heading("version", text="VERSION")
        self.tool_tree.heading("path", text="PATH")
        self.tool_tree.column("status", width=28, stretch=False)
        self.tool_tree.column("tool", width=110, stretch=False)
        self.tool_tree.column("group", width=110, stretch=False)
        self.tool_tree.column("version", width=320, stretch=False)
        self.tool_tree.column("path", width=380, stretch=True)
        self.tool_tree.tag_configure("ok", foreground=TXT)
        self.tool_tree.tag_configure("miss", foreground=DIM)
        ysb = ttk.Scrollbar(top, orient="vertical", command=self.tool_tree.yview)
        self.tool_tree.configure(yscrollcommand=ysb.set)
        self.tool_tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tool_tree.bind("<Double-1>", lambda _e: self._copy_install())

        self.install_hint = tk.Label(frame, text="", font=("Consolas", 8), fg=DIM,
                                     bg=CARD, anchor="w", justify="left")
        self.install_hint.pack(fill="x", padx=12, pady=(0, 10))
        self.tool_tree.bind("<<TreeviewSelect>>", self._show_install_hint)

    # --------------------------------------------------------------- projects

    def _load_projects(self) -> None:
        self.project_list.delete(0, "end")
        for path in self.store.projects:
            self.project_list.insert("end", Path(path).name or path)
        last = self.store.data.get("last") or ""
        if last and last in self.store.projects:
            index = self.store.projects.index(last)
            self.project_list.selection_set(index)
            self.project_list.see(index)
            self._select_path(last)
        elif not self.store.projects:
            self._set_project(None)

    def _on_select_project(self, _event=None) -> None:
        selection = self.project_list.curselection()
        if not selection:
            return
        path = self.store.projects[selection[0]]
        self.store.set("last", path)
        self._select_path(path)

    def _select_path(self, path: str) -> None:
        self.path_var.set(path)
        self._set_project_by_path(path)

    def _open_typed_path(self) -> None:
        raw = self.path_var.get().strip().strip('"')
        if not raw:
            return
        if not Path(raw).is_dir():
            messagebox.showerror(APP_NAME, f"Folder not found:\n{raw}", parent=self)
            return
        self._set_project_by_path(raw)
        self.store.add_project(raw)
        self._load_projects()
        self._select_path(str(Path(raw).resolve()))

    def _add_project(self) -> None:
        folder = filedialog.askdirectory(title="Select a project folder", parent=self)
        if folder:
            self.path_var.set(folder)
            self._open_typed_path()

    def _rename_project(self) -> None:
        if not self.project:
            return
        current = self.project.name
        dialog = tk.Toplevel(self)
        dialog.title("Rename project")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("420x150")
        tk.Label(dialog, text="Display name", font=("Segoe UI", 9), fg=DIM,
                 bg=BG).pack(anchor="w", padx=16, pady=(14, 4))
        var = tk.StringVar(value=current)
        entry = tk.Entry(dialog, textvariable=var, bg=CARD2, fg=TXT,
                         insertbackground=GREEN, relief="flat", font=("Consolas", 10))
        entry.pack(fill="x", padx=16, ipady=6)
        entry.focus_set()
        entry.select_range(0, "end")

        def save() -> None:
            name = var.get().strip()
            if name:
                labels = dict(self.store.data.get("labels") or {})
                labels[str(self.project.root)] = name
                self.store.set("labels", labels)
                self._load_projects()
                self._refresh_header()
            dialog.destroy()

        ttk.Button(dialog, text="Save", style="Accent.TButton",
                   command=save).pack(pady=14)
        entry.bind("<Return>", lambda _e: save())

    def _remove_project(self) -> None:
        selection = self.project_list.curselection()
        if not selection:
            return
        path = self.store.projects[selection[0]]
        if not messagebox.askokcancel(
                APP_NAME, f"Remove from the list?\n\n{path}\n\n"
                          "Files on disk are not touched.", parent=self):
            return
        self.store.remove_project(path)
        self._load_projects()

    # ------------------------------------------------------------------ build

    def _custom_for(self, root: Path) -> str:
        return str((self.store.data.get("custom") or {}).get(str(root), ""))

    def _set_project_by_path(self, path: str) -> None:
        try:
            project = detect_project(path)
        except (OSError, NotADirectoryError) as exc:
            messagebox.showerror(APP_NAME, f"Cannot open folder:\n{exc}", parent=self)
            return
        selected = str(Path(path).resolve())
        self._set_project(project)
        if self.store.data.get("last") != selected:
            self.store.set("last", selected)

    def _set_project(self, project: Project | None) -> None:
        previous = self.project.root if self.project else None
        changed = previous != (project.root if project else None)
        self.project = project
        if changed:
            self.raw_lines = []
            self._clear_log()
            self._clear_problems()
            self.status_var.set("Ready" if project else "No project selected")
        self._refresh_header()
        self._refresh_plan()
        self._update_actions()

    def _display_name(self, project: Project) -> str:
        labels = self.store.data.get("labels") or {}
        return str(labels.get(str(project.root)) or project.name)

    def _refresh_header(self) -> None:
        project = self.project
        if not project:
            self.project_title.configure(text="No project selected")
            self.kind_badge.configure(text="")
            self.project_path.configure(text="Add a project folder to begin.")
            self.kind_desc.configure(text="")
            return
        self.project_title.configure(text=self._display_name(project))
        self.kind_badge.configure(text=f" {project.kind} ")
        self.project_path.configure(text=str(project.root))
        desc = KIND_DESCRIPTIONS.get(project.kind, "")
        if project.kind == "esp-idf":
            desc += f" · target {project.meta.get('target') or 'esp32'}"
        if project.meta.get("via"):
            desc += f" · detected inside {project.meta['via']}"
        self.kind_desc.configure(text=desc)

    def _refresh_plan(self) -> None:
        if not self.project:
            self.plan = None
            self._update_actions()
            return
        self.plan = make_plan(
            self.project,
            release=self.release_var.get(),
            jobs=self._jobs(),
            clean=self.clean_var.get(),
            custom=self._custom_for(self.project.root),
        )
        self._update_actions()
        if self.tools_scanned:
            self._check_required()

    def _jobs(self) -> int:
        try:
            return max(1, min(int(self.jobs_var.get()), 64))
        except ValueError:
            return default_jobs()

    def _save_jobs(self) -> None:
        self.store.set("jobs", self._jobs())
        self._refresh_plan()

    def _on_config_change(self, _event=None) -> None:
        release = self.config_var.get() == "Release"
        self.release_var.set(release)
        self.store.set("release", release)
        self._refresh_plan()

    def _update_actions(self) -> None:
        state = "normal" if (self.project and not self.running) else "disabled"
        self.build_btn.configure(state=state)
        self.stop_btn.configure(state="normal" if self.running else "disabled")

    def _start_build(self) -> None:
        if self.running or not self.project:
            return
        self._refresh_plan()
        plan = self.plan
        if not plan or plan.empty:
            self._explain_empty_plan(plan)
            return

        self._clear_log()
        self._clear_problems()
        self.running = True
        self.build_seconds = 0.0
        self.raw_lines = []
        missing = (missing_for_project(self.project, self.tools)
                   if self.tools_scanned else [])
        if missing:
            self._clear_problems()
            self._append(f"missing toolchain: {', '.join(missing)}", "err")
            if self.project.kind == "esp-idf":
                self._append("ESP-IDF detected: install it with "
                             "'winget install --id Espressif.EIM-CLI', run 'eim install', "
                             "then reopen BuildForge so idf.py is on PATH.", "err")
            else:
                self._append("Open the Toolchains tab and install the missing tool, "
                             "then press Rescan.", "err")
            self.status_var.set("Missing toolchain: " + ", ".join(missing))
            self.tabs.select(2)
            self._focus_tool(missing)
            self.running = False
            self._update_actions()
            return
        self._update_actions()
        self.status_var.set(f"Building {self._display_name(self.project)}…")
        self.stats_var.set("")
        self.progress.pack(fill="x", pady=(0, 8))
        self.progress.start(14)
        self.tabs.select(0)

        self._append(f"project   {self.project.root}", "dim")
        self._append(f"system    {self.project.kind} · {plan.notes}", "dim")
        self._append("", None)

        timeout = int(self.store.data.get("timeout") or 0)
        self.runner = BuildRunner(self.queue.put, timeout_seconds=timeout)
        runner = self.runner

        def work() -> None:
            runner.run(plan)

        threading.Thread(target=work, daemon=True).start()

    def _explain_empty_plan(self, plan: Plan | None) -> None:
        project = self.project
        if project is None:
            return
        reason = (plan.notes if plan else "") or "No build plan."
        self._clear_log()
        self._append(f"project   {project.root}", "dim")
        self._append(f"detected  {project.kind} ({project.label})", "dim")
        self._append(f"cannot build: {reason}", "err")
        self.tabs.select(0)
        self.status_var.set("Nothing to build — see the Build tab")
        if project.kind == "esp-idf":
            self.status_var.set("ESP-IDF detected — idf.py is missing")
            tip = ("ESP-IDF firmware detected.\n\n"
                   "idf.py was not found. Install the ESP-IDF toolchain:\n"
                   "  winget install --id Espressif.EIM-CLI\n"
                   "  eim install\n\n"
                   "Then reopen BuildForge (or launch it from the ESP-IDF command "
                   "prompt) and press BUILD again.")
        elif project.kind == "arduino":
            tip = ("Arduino sketch detected.\n\n"
                   "No board FQBN is known. Add sketch.yaml with default_fqbn, or "
                   "set a custom command:\n"
                   "  arduino-cli compile --fqbn <vendor:arch:board> .")
        else:
            tip = ("BuildForge could not find a build system in this folder.\n\n"
                   "Open Settings and set a custom build command, or select the "
                   "folder that contains the project manifest.")
        self._append(tip, "warn")
        messagebox.showinfo(APP_NAME, tip, parent=self)

    def _stop_build(self) -> None:
        if self.runner and self.running:
            self.status_var.set("Stopping…")
            self.runner.cancel()

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _copy_log(self) -> None:
        text = self.log_text.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set(f"Copied {len(text.splitlines())} log lines")

    def _append(self, text: str, tag: str | None) -> None:
        self.log_text.configure(state="normal")
        if tag is None:
            if ERRORISH.search(text):
                tag = "err"
            elif WARNISH.search(text):
                tag = "warn"
        self.log_text.insert("end", text + "\n", tag or ())
        if int(self.log_text.index("end-1c").split(".")[0]) > MAX_LOG_LINES:
            self.log_text.delete("1.0", "4000.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _drain(self) -> None:
        try:
            while True:
                event = self.queue.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.after(60, self._drain)

    def _handle_event(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "line":
            text = event.get("text", "")
            tag = event.get("tag")
            self._append(text, tag)
            if tag != "dim" and not text.startswith("$ "):
                self.raw_lines.append(text)
        elif kind == "step":
            index = event.get("index", 0)
            total = event.get("total", 0)
            self._append("", None)
            self._append(f"[{index}/{total}] {event.get('label', '')}", "step")
            self.status_var.set(f"Step {index}/{total}: {event.get('label', '')}")
        elif kind == "tools":
            self._apply_tools(event.get("tools", []))
        elif kind == "done":
            self._finish_build(bool(event.get("ok")), float(event.get("seconds", 0.0)),
                              bool(event.get("cancelled")), int(event.get("code", 0)))

    def _finish_build(self, ok: bool, seconds: float, cancelled: bool, code: int) -> None:
        self.running = False
        self.build_seconds = seconds
        self.progress.stop()
        self.progress.pack_forget()
        self._update_actions()

        if code == -1:
            self.status_var.set("Build could not start")
        elif cancelled:
            self.status_var.set(f"Stopped after {seconds:.1f}s")
        elif ok:
            self.status_var.set(f"Build succeeded in {seconds:.1f}s")
        else:
            self.status_var.set(f"Build failed in {seconds:.1f}s (exit {code})")
        self._append("", None)
        self._append(self.status_var.get().upper(), "ok" if ok else "err")

        self._analyze_silent()
        if self.project:
            self.store.record_build(str(self.project.root), self.project.kind,
                                    ok, seconds)
        self._update_stats()
        if self.problems and not ok:
            self.tabs.select(1)

    # --------------------------------------------------------------- problems

    def _clear_problems(self) -> None:
        self.problem_tree.delete(*self.problem_tree.get_children())
        self.problems = []
        self.problems_head.configure(text="No build yet.")
        self.tabs.tab(1, text="Problems 0")
        self._set_detail("")

    def _analyze_log(self) -> None:
        self.raw_lines = self.log_text.get("1.0", "end-1c").splitlines()
        self._analyze_silent()
        self._update_stats()
        if self.problems:
            self.tabs.select(1)

    def _analyze_silent(self) -> None:
        root = str(self.project.root) if self.project else ""
        self.problems = parse_log("\n".join(self.raw_lines))
        self.problem_tree.delete(*self.problem_tree.get_children())
        for problem in self.problems:
            where = problem.location or "—"
            self.problem_tree.insert(
                "", "end",
                values=(problem.severity, problem.code or "—", where, problem.message),
                tags=(problem.severity,))
        total = counts(self.problems)
        if self.problems:
            self.problems_head.configure(
                text=f"{total['errors']} error(s) · {total['warnings']} warning(s) "
                     f"· double-click to open the source line")
        elif self.raw_lines:
            self.problems_head.configure(text="No structured problems found in the log.")
        self.tabs.tab(1, text=f"Problems {len(self.problems)}")
        self._set_detail("")
        if self.problems:
            first = self.problem_tree.get_children()[0]
            self.problem_tree.selection_set(first)
            self.problem_tree.focus(first)
            self._show_problem()

    def _selected_problem(self) -> Problem | None:
        selection = self.problem_tree.selection()
        if not selection:
            return None
        index = self.problem_tree.index(selection[0])
        if 0 <= index < len(self.problems):
            return self.problems[index]
        return None

    def _show_problem(self, _event=None) -> None:
        problem = self._selected_problem()
        if not problem:
            self._set_detail("")
            return
        parts = [
            ("WHERE   ", problem.location or "no location"),
            ("CODE    ", problem.code or "—"),
            ("SEVERITY", problem.severity),
            ("MESSAGE ", problem.message),
        ]
        detail = "".join(f"{label} {value}\n" for label, value in parts)
        if problem.explanation:
            detail += f"\nWHY\n  {problem.explanation}\n"
        if problem.fix:
            detail += f"\nFIX\n  {problem.fix}\n"
        if problem.raw:
            detail += f"\nRAW\n  {problem.raw}\n"
        self._set_detail(detail)

    def _set_detail(self, text: str) -> None:
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        if text:
            for line in text.splitlines(keepends=True):
                label = line[:8].strip().upper() in {"WHERE", "CODE", "SEVERITY",
                                                     "MESSAGE", "WHY", "FIX", "RAW"}
                self.detail_text.insert("end", line, "label" if label else ())
        self.detail_text.configure(state="disabled")

    def _open_selected_problem(self) -> None:
        problem = self._selected_problem()
        if not problem or not problem.file:
            return
        path = Path(problem.file)
        if not path.is_absolute() and self.project:
            path = self.project.root / problem.file
        self._open_editor(path, problem.line)

    def _open_editor(self, path: Path, line: int = 0) -> None:
        code = shutil.which("code") or shutil.which("code.cmd")
        try:
            if code:
                args = [code]
                if line:
                    args += ["-g", f"{path}:{line}"]
                else:
                    args.append(str(path))
                subprocess.Popen(args, creationflags=0x08000000 if os.name == "nt" else 0)
            else:
                os.startfile(str(path))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Cannot open {path}:\n{exc}", parent=self)

    def _update_stats(self) -> None:
        if self.project and self.raw_lines:
            total = counts(self.problems)
            secs = f"{self.build_seconds:.1f}s" if self.build_seconds else "—"
            self.stats_var.set(f"{self.project.kind} · {secs} · "
                               f"{total['errors']} errors · {total['warnings']} warnings")
        elif self.project:
            self.stats_var.set(self.project.kind)

    # -------------------------------------------------------------- toolchains

    def _scan_tools_async(self) -> None:
        self.tools_scanned = False
        self.tools_head.configure(text="Scanning toolchains…")
        self.status_var.set("Scanning installed toolchains…")

        def work() -> None:
            found = scan()
            self.queue.put({"type": "tools", "tools": found})

        threading.Thread(target=work, daemon=True).start()

    def _apply_tools(self, tools: list[ToolStatus]) -> None:
        self.tools = tools
        self.tools_scanned = True
        self.tool_tree.delete(*self.tool_tree.get_children())
        found = 0
        for tool in tools:
            found += 1 if tool.found else 0
            self.tool_tree.insert(
                "", "end",
                values=("●" if tool.found else "○", tool.name, tool.group,
                        tool.version or tool.description,
                        tool.path or "not found"),
                tags=("ok" if tool.found else "miss",))
        self.tools_head.configure(text=f"{found} of {len(tools)} tools found · "
                                       "missing tools show the install command below")
        self._update_actions()
        self._check_required()
        self._update_stats()

    def _focus_tool(self, names: list[str]) -> None:
        for index, tool in enumerate(self.tools):
            if tool.name in names:
                item = self.tool_tree.get_children()[index]
                self.tool_tree.selection_set(item)
                self.tool_tree.focus(item)
                self.tool_tree.see(item)
                self._show_install_hint()
                return

    def _check_required(self) -> None:
        if not self.project or not self.tools_scanned:
            return
        missing = missing_for_project(self.project, self.tools)
        if missing and not self.running:
            self.status_var.set("Missing for this project: " + ", ".join(missing)
                                + " — open the Toolchains tab")
        elif not self.running:
            self.status_var.set("Ready")

    def _show_install_hint(self, _event=None) -> None:
        selection = self.tool_tree.selection()
        if not selection:
            return
        index = self.tool_tree.index(selection[0])
        if 0 <= index < len(self.tools):
            tool = self.tools[index]
            if tool.found:
                self.install_hint.configure(text=f"{tool.name} · {tool.path}")
            else:
                self.install_hint.configure(
                    text=f"{tool.name} missing · {tool.install}   (double-click the row to copy)")

    def _copy_install(self) -> None:
        selection = self.tool_tree.selection()
        if not selection:
            return
        index = self.tool_tree.index(selection[0])
        if 0 <= index < len(self.tools) and not self.tools[index].found:
            command = self.tools[index].install
            self.clipboard_clear()
            self.clipboard_append(command)
            self.install_hint.configure(text=f"Copied: {command}")

    # ---------------------------------------------------------------- settings

    def _open_settings(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Settings")
        dialog.configure(bg=BG)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)

        frame = tk.Frame(dialog, bg=BG)
        frame.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(frame, text="Build settings", font=("Segoe UI Semibold", 12),
                 fg=TXT, bg=BG).grid(row=0, column=0, columnspan=2, sticky="w",
                                     pady=(0, 12))

        tk.Label(frame, text="Parallel jobs", fg=DIM, bg=BG).grid(
            row=1, column=0, sticky="w", pady=4)
        jobs_var = tk.StringVar(value=str(self._jobs()))
        ttk.Spinbox(frame, from_=1, to=64, width=8, textvariable=jobs_var).grid(
            row=1, column=1, sticky="w", pady=4)

        tk.Label(frame, text="Timeout per step (s, 0 = none)", fg=DIM, bg=BG).grid(
            row=2, column=0, sticky="w", pady=4)
        timeout_var = tk.StringVar(value=str(self.store.data.get("timeout") or 0))
        ttk.Spinbox(frame, from_=0, to=7200, increment=30, width=8,
                    textvariable=timeout_var).grid(row=2, column=1, sticky="w", pady=4)

        tk.Label(frame, text="Custom command (unknown project type)", fg=DIM,
                 bg=BG).grid(row=3, column=0, sticky="w", pady=(10, 4))
        custom_var = tk.StringVar(
            value=self._custom_for(self.project.root) if self.project else "")
        custom_entry = tk.Entry(frame, textvariable=custom_var, width=46, bg=CARD2,
                                fg=TXT, insertbackground=GREEN, relief="flat",
                                font=("Consolas", 9))
        custom_entry.grid(row=4, column=0, columnspan=2, sticky="we", ipady=5)

        tk.Label(frame, text="Example:  make -j8   ·   python -m pytest   ·   gradlew.bat build",
                 font=("Segoe UI", 8), fg=DIM, bg=BG).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))

        def save() -> None:
            try:
                self.store.set("jobs", max(1, min(int(jobs_var.get()), 64)))
                self.store.set("timeout", max(0, int(timeout_var.get())))
            except ValueError:
                messagebox.showerror(APP_NAME, "Jobs and timeout must be numbers.",
                                     parent=dialog)
                return
            if self.project:
                custom = dict(self.store.data.get("custom") or {})
                value = custom_var.get().strip()
                if value:
                    custom[str(self.project.root)] = value
                else:
                    custom.pop(str(self.project.root), None)
                self.store.set("custom", custom)
            self.jobs_var.set(str(self.store.data.get("jobs") or default_jobs()))
            dialog.destroy()
            self._refresh_plan()

        buttons = tk.Frame(frame, bg=BG)
        buttons.grid(row=6, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(
            side="left", padx=(0, 8))
        ttk.Button(buttons, text="Save", style="Accent.TButton",
                   command=save).pack(side="left")

    # ------------------------------------------------------------------- close

    def _on_close(self) -> None:
        if self.running and self.runner:
            if not messagebox.askokcancel(APP_NAME, "A build is running. Stop and quit?",
                                          parent=self):
                return
            self.runner.cancel()
        try:
            self.store.set("window", self.geometry())
            self.store.set("release", self.release_var.get())
            self.store.set("clean", self.clean_var.get())
            self.store.set("jobs", self._jobs())
        finally:
            self.destroy()


def run() -> None:
    App().mainloop()


if __name__ == "__main__":
    run()
