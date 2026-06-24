from __future__ import annotations

import csv
import json
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import queue
import random
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
from dataclasses import dataclass
from tkinter import font as tkfont
from pathlib import Path
from typing import Any, Callable
from .brain_nodes import BrainGraph, BrainGraphBuilder, BrainNode
from .commands import CommandContext, CommandRouter
from .config import Settings
from .build_agent import BuildAgent, BuildAgentResult
from .dev_tools import (
    basic_model_benchmark,
    build_agent_instruction_from_error,
    create_safe_mode_files,
    dependency_doctor,
    load_plugins,
    save_plugins,
    smart_error_explain,
    source_cleaner_preview,
    source_cleaner_run,
)
from .tools_service import (
    ConsentDiagnosticServer,
    get_public_ip,
    normalize_username_list,
    read_diagnostic_records,
    test_telegram_token,
    validate_url,
    ghost_track_service,
)

from .telegram_settings import (
    TelegramRuntimeConfig,
    apply_telegram_runtime_config,
    load_telegram_runtime_config,
    parse_owner_ids,
    parse_owner_usernames,
    save_telegram_runtime_config,
)
from .llm import SYSTEM_PROMPT
from .llm_models import (
    LLMRuntimeConfig,
    LMStudioModelManager,
    ModelCandidate,
    apply_config as apply_llm_config,
    load_saved_config as load_llm_saved_config,
    save_config as save_llm_config,
)
from .utils import split_telegram
from .worldclass import (
    EvidenceVault,
    ReleaseManager,
    SelfTestLab,
    WorkflowTemplates,
    delete_source_rule,
    list_scheduled_jobs,
    project_memory_text,
    schedule_job,
    source_rules_text,
    summarize_knowledge_timeline,
    upsert_project_memory,
    upsert_source_rule,
)
from .personality import (
    ALL_SLIDERS,
    AUTONOMY_RESEARCH,
    BEHAVIOR_STYLE,
    COMMUNICATION_STYLE,
    CORE_TRAITS,
    DEFAULT_TOGGLES,
    LANGUAGE_STYLE_OPTIONS,
    MEMORY_BEHAVIOR,
    PRESETS,
    REPLY_RULES,
    SAFETY_PRIVACY,
    SPEECH_TONE,
    TONE_OPTIONS,
    PersonalityProfile,
    load_personality,
    prompt_preview,
    save_personality,
)


@dataclass(frozen=True)
class Palette:
    bg: str = "#05070d"
    sidebar: str = "#080b13"
    panel: str = "#0b0f1a"
    panel_2: str = "#101522"
    bubble_ai: str = "#111827"
    bubble_user: str = "#22183a"
    bubble_user_border: str = "#6e42d7"
    text: str = "#f4f1ff"
    muted: str = "#9b9baa"
    muted_2: str = "#696a78"
    purple: str = "#9b5cff"
    purple_dark: str = "#3b1b70"
    purple_soft: str = "#2a1948"
    gold: str = "#f4d27a"
    cyan: str = "#74e6ff"
    blue: str = "#6aa8ff"
    green: str = "#65d890"
    orange: str = "#ffb86c"
    border: str = "#222838"
    danger: str = "#ff6b7a"
    success: str = "#65d890"


P = Palette()


NODE_COLORS = {
    "core": P.gold,
    "topic": P.purple,
    "chunk": P.blue,
    "keyword": P.cyan,
    "memory": P.green,
    "entity": P.orange,
    "conversation": "#d58cff",
    "conversation_term": "#aab3ff",
}


class MonacoGUI:
    """Desktop GUI for M0N4C0-AI.

    Tkinter-only so it runs on Windows with Python 3.11 without extra heavy GUI
    frameworks. The chat, learning, memory and web research still go through the
    same CommandRouter; this is the polished app layer on top.
    """

    def __init__(self, settings: Settings, router: CommandRouter, telegram_controller: Any | None = None, safe_mode: bool = False):
        self.settings = settings
        self.router = router
        self.ctx = CommandContext(
            platform="gui",
            chat_id="gui:local",
            user_key="gui:owner",
            username="owner",
            display_name="Owner",
        )
        self.pending_queue: "queue.Queue[tuple[str, str, tk.Widget]]" = queue.Queue()
        self.activity_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.busy = False
        self.current_view = "chat"
        self.safe_mode = safe_mode

        self.personality_profile = load_personality(settings)
        self.personality_panel: tk.Frame | None = None
        self.personality_vars: dict[str, tk.DoubleVar] = {}
        self.personality_value_labels: dict[str, tk.Label] = {}
        self.personality_toggle_vars: dict[str, tk.BooleanVar] = {}
        self.personality_tone_var: tk.StringVar | None = None
        self.personality_language_var: tk.StringVar | None = None
        self.personality_preset_var: tk.StringVar | None = None

        self.llm_manager = LMStudioModelManager(settings)
        self.llm_config = load_llm_saved_config(settings)
        self.llm_panel: tk.Frame | None = None
        self.llm_models: list[ModelCandidate] = []
        self.llm_selected_id: str | None = self.llm_config.model_id
        self.llm_coding_selected_id: str | None = self.llm_config.coding_model_id or self.llm_config.model_id
        self.llm_model_rows: dict[str, tk.Frame] = {}
        self.llm_model_list_inner: tk.Frame | None = None
        self.llm_search_var: tk.StringVar | None = None
        self.llm_filter_var: tk.StringVar | None = None
        self.llm_base_url_var: tk.StringVar | None = None
        self.llm_temperature_var: tk.DoubleVar | None = None
        self.llm_max_tokens_var: tk.IntVar | None = None
        self.llm_context_var: tk.IntVar | None = None
        self.llm_top_p_var: tk.DoubleVar | None = None
        self.llm_repeat_penalty_var: tk.DoubleVar | None = None
        self.llm_top_k_var: tk.IntVar | None = None
        self.llm_min_p_var: tk.DoubleVar | None = None
        self.llm_programming_router_var: tk.BooleanVar | None = None
        self.llm_single_model_var: tk.BooleanVar | None = None
        self.llm_system_prompt_text: tk.Text | None = None
        self.llm_system_prompt_apply_job: str | None = None
        self.llm_param_value_labels: dict[str, tk.Label] = {}

        self.research_panel: tk.Frame | None = None
        self.research_topic_var: tk.StringVar | None = None
        self.research_mode_var: tk.StringVar | None = None
        self.research_rounds_var: tk.IntVar | None = None
        self.research_start_year_var: tk.StringVar | None = None
        self.research_end_year_var: tk.StringVar | None = None
        self.research_priority_var: tk.IntVar | None = None
        self.research_jobs_text: tk.Text | None = None
        self.research_events_text: tk.Text | None = None
        self.research_worker_process: subprocess.Popen | None = None

        self.database_panel: tk.Frame | None = None
        self.db_table_list: tk.Listbox | None = None
        self.db_table_names: list[str] = []
        self.db_current_table: str | None = None
        self.db_offset = 0
        self.db_limit_var: tk.IntVar | None = None
        self.db_search_var: tk.StringVar | None = None
        self.db_preview_text: tk.Text | None = None
        self.db_schema_text: tk.Text | None = None
        self.db_sql_input: tk.Text | None = None
        self.db_sql_output: tk.Text | None = None
        self.db_write_enabled_var: tk.BooleanVar | None = None

        self.telegram_panel: tk.Frame | None = None
        self.telegram_controller = telegram_controller
        self.telegram_config = load_telegram_runtime_config(settings)
        self.telegram_enabled_var: tk.BooleanVar | None = None
        self.telegram_auto_start_var: tk.BooleanVar | None = None
        self.telegram_allow_all_var: tk.BooleanVar | None = None
        self.telegram_token_var: tk.StringVar | None = None
        self.telegram_owner_ids_var: tk.StringVar | None = None
        self.telegram_owner_usernames_var: tk.StringVar | None = None
        self.telegram_status_text: tk.Text | None = None
        self.telegram_logs_text: tk.Text | None = None

        self.chat_model_role_var: tk.StringVar | None = None
        self.research_source_var: tk.StringVar | None = None
        self.research_workers_var: tk.IntVar | None = None
        self.research_low_llm_var: tk.BooleanVar | None = None
        self.research_depth_var: tk.IntVar | None = None
        self.research_max_pages_var: tk.IntVar | None = None
        self.research_max_files_var: tk.IntVar | None = None
        self.research_source_list_text: tk.Text | None = None
        self.research_source_delete_var: tk.StringVar | None = None
        self.mission_panel: tk.Frame | None = None
        self.mission_goal_var: tk.StringVar | None = None
        self.mission_mode_var: tk.StringVar | None = None
        self.mission_workers_var: tk.IntVar | None = None
        self.mission_plan_text: tk.Text | None = None
        self.mission_status_text: tk.Text | None = None
        self.idle_panel: tk.Frame | None = None
        self.idle_topic_var: tk.StringVar | None = None
        self.idle_enabled_var: tk.BooleanVar | None = None
        self.idle_seconds_var: tk.IntVar | None = None
        self.idle_topics_text: tk.Text | None = None
        self.idle_wikipedia_var: tk.BooleanVar | None = None
        self.idle_worker_process: subprocess.Popen | None = None
        self.performance_panel: tk.Frame | None = None
        self.performance_text: tk.Text | None = None
        self.performance_preset_var: tk.StringVar | None = None
        self.performance_cache_mb_var: tk.IntVar | None = None
        self.performance_mmap_mb_var: tk.IntVar | None = None
        self.performance_auto_backup_var: tk.BooleanVar | None = None
        self.performance_wal_var: tk.BooleanVar | None = None
        self.memory_panel: tk.Frame | None = None
        self.memory_search_var: tk.StringVar | None = None
        self.memory_text: tk.Text | None = None
        self.logs_panel: tk.Frame | None = None
        self.logs_text: tk.Text | None = None
        self.live_feed_panel: tk.Frame | None = None
        self.live_feed_text: tk.Text | None = None
        self.image_panel: tk.Frame | None = None
        self.trading_panel: tk.Frame | None = None

        self.tools_panel: tk.Frame | None = None
        self.tools_url_var: tk.StringVar | None = None
        self.tools_username_var: tk.StringVar | None = None
        self.tools_diag_port_var: tk.IntVar | None = None
        self.tools_output_text: tk.Text | None = None
        self.consent_diag_server: ConsentDiagnosticServer | None = None

        self.build_agent_panel: tk.Frame | None = None
        self.build_agent_source_var: tk.StringVar | None = None
        self.build_agent_instruction_text: tk.Text | None = None
        self.build_agent_targets_text: tk.Text | None = None
        self.build_agent_output_text: tk.Text | None = None
        self.build_agent_changed_text: tk.Text | None = None
        self.build_agent_last_result: BuildAgentResult | None = None
        self.build_agent_preview_process: subprocess.Popen | None = None
        self.build_agent_diff_text: tk.Text | None = None
        self.dependency_panel: tk.Frame | None = None
        self.dependency_text: tk.Text | None = None
        self.benchmark_panel: tk.Frame | None = None
        self.benchmark_text: tk.Text | None = None
        self.error_panel: tk.Frame | None = None
        self.error_input_text: tk.Text | None = None
        self.error_output_text: tk.Text | None = None
        self.plugin_panel: tk.Frame | None = None
        self.plugin_vars: dict[str, tk.BooleanVar] = {}
        self.worldclass_panel: tk.Frame | None = None
        self.worldclass_text: tk.Text | None = None
        self.source_rule_pattern_var: tk.StringVar | None = None
        self.source_rule_action_var: tk.StringVar | None = None
        self.project_key_var: tk.StringVar | None = None
        self.project_memory_key_var: tk.StringVar | None = None
        self.project_memory_value_var: tk.StringVar | None = None
        self.scheduler_title_var: tk.StringVar | None = None
        self.scheduler_type_var: tk.StringVar | None = None
        self.scheduler_cadence_var: tk.StringVar | None = None

        self.brain_builder = BrainGraphBuilder(router.db)
        self.brain_graph: BrainGraph | None = None
        self.brain_positions: dict[str, tuple[float, float]] = {}
        self.brain_node_items: dict[str, list[int]] = {}
        self.brain_edge_items: list[tuple[int, str, str]] = []
        self.brain_selected_node: str | None = None
        self.brain_hover_node: str | None = None
        self.brain_drag_node: str | None = None
        self.brain_drag_offset: tuple[float, float] = (0.0, 0.0)
        self.brain_scale = 1.0
        self.brain_pan_active = False
        self.brain_pan_last: tuple[int, int] | None = None
        self.brain_panel: tk.Frame | None = None

        self.root = tk.Tk()
        self.root.title("M0N4C0 — Private Intelligence Suite" + (" [SAFE MODE]" if self.safe_mode else ""))
        self.root.geometry("1500x900")
        self.root.minsize(1120, 720)
        self.root.configure(bg=P.bg)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Escape>", lambda _event: self._show_chat_view() if self.current_view != "chat" else None)
        self.root.bind("<Control-k>", lambda _event: self._open_command_center())
        self.root.bind("<Control-K>", lambda _event: self._open_command_center())

        self.font_title = tkfont.Font(family="Segoe UI", size=30, weight="bold")
        self.font_heading = tkfont.Font(family="Segoe UI", size=20, weight="bold")
        self.font_body = tkfont.Font(family="Segoe UI", size=12)
        self.font_body_bold = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.font_small = tkfont.Font(family="Segoe UI", size=10)
        self.font_code = tkfont.Font(family="Consolas", size=11)
        self._apply_brand_icon()

        self._build_layout()
        self._add_assistant_message(
            ("SAFE MODE actief. Gebruik Chat, Logs, Tools, Dependency Doctor, Plugin Manager en Build Agent om te repareren." if self.safe_mode else
            "M0N4C0 online. Typ gewoon wat je wil vragen. Commands mogen nog steeds, "
            "maar zijn optioneel. Voorbeeld: ‘Leer elke Pokémon vanaf het jaar 2000 tot en met 2026’.")
        )
        if not self.safe_mode:
            self.root.after(650, self._telegram_autostart_if_enabled)
        self._poll_queue()

    def _apply_brand_icon(self) -> None:
        """Load the local M0N4C0 logo/icon when present, but never crash if missing."""
        self.brand_icon_photo = None
        try:
            ico = self.settings.root / "assets" / "m0n4c0_icon.ico"
            png = self.settings.root / "assets" / "m0n4c0_icon.png"
            if sys.platform.startswith("win") and ico.exists():
                self.root.iconbitmap(str(ico))
            if png.exists():
                self.brand_icon_photo = tk.PhotoImage(file=str(png))
                self.root.iconphoto(True, self.brand_icon_photo)
        except Exception:
            # Branding should never block the GUI from booting.
            pass

    def run(self) -> None:
        self.root.mainloop()

    # ---------- layout ----------
    def _build_layout(self) -> None:
        shell = tk.Frame(self.root, bg=P.bg, padx=18, pady=18)
        shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(0, minsize=360, weight=0)
        shell.grid_columnconfigure(1, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        self.sidebar = tk.Frame(shell, bg=P.sidebar, highlightbackground=P.border, highlightthickness=1)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        self.main_panel = tk.Frame(shell, bg=P.bg, highlightbackground=P.border, highlightthickness=1)
        self.main_panel.grid(row=0, column=1, sticky="nsew", padx=(18, 0))
        self.main_panel.grid_rowconfigure(1, weight=1)
        self.main_panel.grid_columnconfigure(0, weight=1)

        self._build_sidebar()
        self._build_header()
        self._build_chat()
        self._build_input()

    def _build_sidebar(self) -> None:
        top = tk.Frame(self.sidebar, bg=P.sidebar, padx=26, pady=22)
        top.pack(fill="x")

        logo_path = self.settings.root / "assets" / "m0n4c0_logo.png"
        self.brand_logo_photo = None
        if logo_path.exists():
            try:
                self.brand_logo_photo = tk.PhotoImage(file=str(logo_path))
                tk.Label(top, image=self.brand_logo_photo, bg=P.sidebar).pack(anchor="center", pady=(0, 8))
            except tk.TclError:
                tk.Label(top, text="♛", bg=P.sidebar, fg=P.gold, font=("Segoe UI Symbol", 42, "bold")).pack(anchor="center")
        else:
            tk.Label(top, text="♛", bg=P.sidebar, fg=P.gold, font=("Segoe UI Symbol", 42, "bold")).pack(anchor="center")
        # Logo already carries the M0N4C0 wordmark, so avoid duplicate branding.
        if self.brand_logo_photo is None:
            title = tk.Label(top, text="M0N4C0", bg=P.sidebar, fg=P.gold, font=self.font_title)
            title.pack(anchor="center", pady=(0, 2))
        subtitle = tk.Label(top, text="private intelligence suite", bg=P.sidebar, fg=P.muted, font=("Segoe UI", 12))
        subtitle.pack(anchor="center")

        scroll_shell = tk.Frame(self.sidebar, bg=P.sidebar)
        scroll_shell.pack(fill="both", expand=True, padx=0, pady=(0, 8))
        scroll_shell.grid_columnconfigure(0, weight=1)
        scroll_shell.grid_rowconfigure(0, weight=1)
        self.sidebar_canvas = tk.Canvas(scroll_shell, bg=P.sidebar, bd=0, highlightthickness=0)
        self.sidebar_canvas.grid(row=0, column=0, sticky="nsew")
        self.sidebar_scrollbar = tk.Scrollbar(scroll_shell, orient="vertical", command=self.sidebar_canvas.yview)
        self.sidebar_scrollbar.grid(row=0, column=1, sticky="ns")
        self.sidebar_canvas.configure(yscrollcommand=self.sidebar_scrollbar.set)
        self.sidebar_inner = tk.Frame(self.sidebar_canvas, bg=P.sidebar)
        self.sidebar_window = self.sidebar_canvas.create_window((0, 0), window=self.sidebar_inner, anchor="nw")
        self.sidebar_inner.bind("<Configure>", lambda _e: self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all")))
        self.sidebar_canvas.bind("<Configure>", lambda e: self.sidebar_canvas.itemconfig(self.sidebar_window, width=e.width))
        self._bind_mousewheel_to_canvas(self.sidebar_canvas)

        # Keep the live feed directly visible before the menu. If the window is
        # short, the whole sidebar scrolls instead of hiding important modules.
        self._build_activity_console(self.sidebar_inner)

        menu = tk.Frame(self.sidebar_inner, bg=P.sidebar, padx=24, pady=8)
        menu.pack(fill="x")
        groups: list[tuple[str, list[tuple[str, str, str, Callable[[], None]]]]] = [
            ("CORE", [
                ("⌁", "Live Feed", "Runtime activity stream", self._show_live_feed_page),
                ("◈", "LLM Models", "Model control + prompts", self._show_llm_models),
                ("♙", "Personality", "Customize your AI", self._show_personality),
                ("☍", "Brain Nodes", "Knowledge network", self._show_brain_nodes),
            ]),
            ("DATA + RESEARCH", [
                ("▣", "Local Database", "Manage local data", self._show_database_manager),
                ("⌁", "Research", "External learning queue", self._show_research),
                ("♜", "Mission Control", "Autopilot planner", self._show_mission_control),
                ("☼", "Idle Learning", "Autonomous when idle", self._show_idle_learning),
                ("▤", "Memory", "Facts + knowledge", self._show_memory_manager),
            ]),
            ("TOOLS", [
                ("✣", "Tools", "Diagnostics + utilities", self._show_tools_page),
                ("◆", "Worldclass Lab", "Truth, search + automation", self._show_worldclass_lab),
                ("⚒", "Build Agent", "Patch source safely", self._show_build_agent),
                ("☑", "Dependency Doctor", "Install checks", self._show_dependency_doctor),
                ("◌", "Model Benchmark", "Compare local models", self._show_model_benchmark_page),
                ("⚠", "Error Explainer", "Explain + fix errors", self._show_error_explainer),
                ("▦", "Plugin Manager", "Enable modules", self._show_plugin_manager),
                ("✈", "Telegram", "Bot bridge", self._show_telegram_manager),
                ("⚡", "Performance", "Optimize + health", self._show_performance_center),
                ("▧", "Logs", "Errors + events", self._show_logs_page),
                ("✦", "Image generation", "ComfyUI module soon", self._show_image_generation),
                ("↗", "Trading Dashboard", "Market intelligence", self._show_trading_dashboard),
            ]),
        ]
        if self.safe_mode:
            groups = [("SAFE REPAIR", [
                ("⌁", "Live Feed", "Runtime activity stream", self._show_live_feed_page),
                ("▧", "Logs", "Errors + events", self._show_logs_page),
                ("✣", "Tools", "Diagnostics + utilities", self._show_tools_page),
                ("◆", "Worldclass Lab", "Truth, search + automation", self._show_worldclass_lab),
                ("☑", "Dependency Doctor", "Install checks", self._show_dependency_doctor),
                ("⚠", "Error Explainer", "Explain + fix errors", self._show_error_explainer),
                ("▦", "Plugin Manager", "Enable modules", self._show_plugin_manager),
                ("⚒", "Build Agent", "Patch source safely", self._show_build_agent),
                ("▣", "Local Database", "Manage local data", self._show_database_manager),
            ])]
        plugin_flags = load_plugins(self.settings.root)
        plugin_map = {
            "Telegram": "Telegram",
            "Research": "Research",
            "Idle Learning": "Idle Learning",
            "Build Agent": "Build Agent",
            "Tools": "Tools",
            "Worldclass Lab": "Worldclass Lab",
            "Trading Dashboard": "Trading Dashboard",
            "Image generation": "Image Generation",
        }
        for group, buttons in groups:
            tk.Label(menu, text=group, bg=P.sidebar, fg=P.gold, font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x", pady=(12, 4))
            for icon, label, sub, action in buttons:
                plugin_name = plugin_map.get(label)
                enabled = True if plugin_name is None else bool(plugin_flags.get(plugin_name, True))
                if not enabled and label not in {"Plugin Manager", "Dependency Doctor", "Logs", "Live Feed"}:
                    disabled_action = lambda label=label: messagebox.showinfo("M0N4C0 Plugin Manager", f"{label} staat uit in Plugin Manager.")
                    self._sidebar_button(menu, icon, label, "Disabled by Plugin Manager", disabled_action).pack(fill="x", pady=5)
                else:
                    self._sidebar_button(menu, icon, label, sub, action).pack(fill="x", pady=5)

        footer = tk.Frame(self.sidebar_inner, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        footer.pack(fill="x", padx=24, pady=(14, 14))
        left = tk.Label(footer, text="◆", bg=P.panel_2, fg=P.purple, font=("Segoe UI Symbol", 24, "bold"))
        left.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 14))
        tk.Label(footer, text="PRIVATE BUILD", bg=P.panel_2, fg=P.text, font=self.font_body_bold).grid(row=0, column=1, sticky="w")
        tk.Label(
            footer,
            text="M0N4C0 local suite.\nNo database included in exported builds.",
            bg=P.panel_2,
            fg=P.muted,
            justify="left",
            font=self.font_small,
        ).grid(row=1, column=1, sticky="w", pady=(5, 0))

        bottom = tk.Frame(self.sidebar, bg=P.sidebar, padx=28, pady=12)
        bottom.pack(fill="x")
        self.status_dot = tk.Label(bottom, text="●", bg=P.sidebar, fg=P.success, font=("Segoe UI", 12, "bold"))
        self.status_dot.pack(side="left")
        self.status_text = tk.Label(bottom, text=" Local GUI ready", bg=P.sidebar, fg=P.muted, font=self.font_small)
        self.status_text.pack(side="left")
        gear = tk.Label(bottom, text="⚙", bg=P.sidebar, fg=P.muted_2, font=("Segoe UI Symbol", 16))
        gear.pack(side="right")

    def _build_activity_console(self, parent: tk.Widget | None = None) -> None:
        """Left sidebar live activity console.

        This replaces the empty visual block with a tiny terminal that shows what
        M0N4C0 is doing: incoming prompt, intent detection, web search queries,
        fetched pages, chunk writes, summaries, DB writes and errors. It is fed
        through a queue so worker threads never touch Tk widgets directly.
        """
        target = parent or self.sidebar
        card = tk.Frame(
            target,
            bg="#050812",
            padx=12,
            pady=10,
            highlightbackground=P.border,
            highlightthickness=1,
        )
        card.pack(fill="x", padx=26, pady=(12, 18))
        head = tk.Frame(card, bg="#050812")
        head.pack(fill="x", pady=(0, 6))
        tk.Label(head, text="LIVE CORE", bg="#050812", fg=P.gold, font=("Consolas", 9, "bold")).pack(side="left")
        self.activity_state = tk.Label(head, text="● idle", bg="#050812", fg=P.success, font=("Consolas", 8))
        self.activity_state.pack(side="right")

        text_frame = tk.Frame(card, bg="#050812")
        text_frame.pack(fill="both")
        text_frame.grid_columnconfigure(0, weight=1)
        self.activity_console = tk.Text(
            text_frame,
            height=9,
            bg="#03050b",
            fg="#cfd7ff",
            insertbackground=P.text,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            wrap="word",
            font=("Consolas", 8),
            padx=8,
            pady=7,
            cursor="arrow",
        )
        self.activity_console.grid(row=0, column=0, sticky="ew")
        self.activity_console.configure(state="disabled")
        self.activity_console.tag_configure("INFO", foreground="#cfd7ff")
        self.activity_console.tag_configure("OK", foreground=P.green)
        self.activity_console.tag_configure("WARN", foreground=P.orange)
        self.activity_console.tag_configure("ERR", foreground=P.danger)
        self.activity_console.tag_configure("STEP", foreground=P.purple)
        self._append_activity_line("INFO", "M0N4C0 GUI booted. Activity stream ready.")

    def _emit_activity(self, message: str, level: str = "INFO") -> None:
        self.activity_queue.put((level.upper(), message))

    def _append_activity_line(self, level: str, message: str) -> None:
        widget = getattr(self, "activity_console", None)
        if widget is None:
            return
        try:
            from datetime import datetime
            stamp = datetime.now().strftime("%H:%M:%S")
            clean = " ".join(str(message).split())
            if len(clean) > 260:
                clean = clean[:257] + "..."
            widget.configure(state="normal")
            widget.insert("end", f"[{stamp}] {level:<4} {clean}\n", level if level in {"INFO", "OK", "WARN", "ERR", "STEP"} else "INFO")
            # Keep it lightweight for long sessions.
            lines = int(widget.index("end-1c").split(".")[0])
            if lines > 220:
                widget.delete("1.0", f"{lines - 180}.0")
            widget.see("end")
            widget.configure(state="disabled")
            state = getattr(self, "activity_state", None)
            if state is not None:
                if level == "ERR":
                    state.configure(text="● error", fg=P.danger)
                elif level in {"STEP", "INFO"}:
                    state.configure(text="● working", fg=P.purple)
                else:
                    state.configure(text="● synced", fg=P.success)
        except tk.TclError:
            pass

    def _sidebar_button(self, parent: tk.Widget, icon: str, label: str, subtitle: str, action: Callable[[], None]) -> tk.Frame:
        box = tk.Frame(parent, bg=P.panel_2, padx=13, pady=9, highlightbackground=P.border, highlightthickness=1, cursor="hand2")
        icon_label = tk.Label(box, text=icon, bg=P.panel_2, fg=P.purple, font=("Segoe UI Symbol", 20, "bold"))
        icon_label.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 13))
        name = tk.Label(box, text=label, bg=P.panel_2, fg=P.text, font=("Segoe UI", 11, "bold"))
        name.grid(row=0, column=1, sticky="w")
        sub = tk.Label(box, text=subtitle, bg=P.panel_2, fg=P.muted, font=("Segoe UI", 9))
        sub.grid(row=1, column=1, sticky="w", pady=(2, 0))
        arrow = tk.Label(box, text="›", bg=P.panel_2, fg=P.muted, font=("Segoe UI", 18))
        arrow.grid(row=0, column=2, rowspan=2, sticky="e")
        box.grid_columnconfigure(1, weight=1)

        def on_enter(_: object) -> None:
            for w in (box, icon_label, name, sub, arrow):
                w.configure(bg="#151b2a")
            box.configure(highlightbackground=P.purple)

        def on_leave(_: object) -> None:
            for w in (box, icon_label, name, sub, arrow):
                w.configure(bg=P.panel_2)
            box.configure(highlightbackground=P.border)

        for w in (box, icon_label, name, sub, arrow):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", lambda _event, action=action: action())
        return box

    def _build_header(self) -> None:
        self.header = tk.Frame(self.main_panel, bg=P.bg, padx=34, pady=28)
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.grid_columnconfigure(1, weight=1)

        avatar = tk.Label(self.header, text="♛", bg=P.bg, fg=P.gold, font=("Segoe UI Symbol", 32, "bold"), width=3)
        avatar.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 18))
        tk.Label(self.header, text="M0N4C0 V0.0 BETA", bg=P.bg, fg=P.text, font=self.font_heading).grid(row=0, column=1, sticky="w")
        tk.Label(self.header, text="Local, uncensored AI.", bg=P.bg, fg=P.muted, font=("Segoe UI", 12)).grid(row=1, column=1, sticky="w", pady=(4, 0))

        self.health_button = tk.Button(
            self.header,
            text="Status",
            command=lambda: self._send_quick("/status"),
            bg=P.panel_2,
            fg=P.text,
            activebackground=P.purple_dark,
            activeforeground=P.text,
            relief="flat",
            padx=18,
            pady=9,
            cursor="hand2",
        )
        self.health_button.grid(row=0, column=2, rowspan=2, sticky="e")

    def _build_chat(self) -> None:
        self.chat_holder = tk.Frame(self.main_panel, bg=P.bg, padx=28)
        self.chat_holder.grid(row=1, column=0, sticky="nsew")
        self.chat_holder.grid_rowconfigure(0, weight=1)
        self.chat_holder.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self.chat_holder, bg=P.bg, bd=0, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = tk.Scrollbar(self.chat_holder, orient="vertical", command=self.canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.messages = tk.Frame(self.canvas, bg=P.bg)
        self.messages_id = self.canvas.create_window((0, 0), window=self.messages, anchor="nw")
        self.messages.bind("<Configure>", self._on_messages_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _build_input(self) -> None:
        # Tkinter widget options accept a single screen distance for pady/padx.
        # Tuple padding belongs on grid/pack, otherwise Windows raises:
        # _tkinter.TclError: bad screen distance "12 24".
        self.input_footer = tk.Frame(self.main_panel, bg=P.bg, padx=28)
        self.input_footer.grid(row=2, column=0, sticky="ew", pady=(12, 24))
        self.input_footer.grid_columnconfigure(0, weight=1)

        input_box = tk.Frame(self.input_footer, bg=P.panel, padx=14, pady=12, highlightbackground=P.border, highlightthickness=1)
        input_box.grid(row=0, column=0, sticky="ew")
        input_box.grid_columnconfigure(0, weight=1)

        role_bar = tk.Frame(input_box, bg=P.panel)
        role_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        role_bar.grid_columnconfigure(2, weight=1)
        tk.Label(role_bar, text="Model", bg=P.panel, fg=P.muted, font=self.font_small).grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.chat_model_role_var = tk.StringVar(value="Auto")
        role_menu = tk.OptionMenu(role_bar, self.chat_model_role_var, "Auto", "Chat", "Code", "Research", "Telegram", "Image", "Trading")
        self._style_option_menu(role_menu)
        role_menu.grid(row=0, column=1, sticky="w")
        tk.Label(role_bar, text="Kies per bericht tegen welk model je praat. Auto routeert zelf.", bg=P.panel, fg=P.muted_2, font=self.font_small).grid(row=0, column=2, sticky="w", padx=(12, 0))

        self.input = tk.Text(
            input_box,
            height=3,
            wrap="word",
            bg=P.panel,
            fg=P.text,
            insertbackground=P.text,
            relief="flat",
            borderwidth=0,
            font=self.font_body,
            padx=10,
            pady=8,
        )
        self.input.grid(row=1, column=0, sticky="ew")
        self.input.focus_set()
        self.input.bind("<Return>", self._enter_send)
        self.input.bind("<Shift-Return>", lambda _event: None)

        self.send_button = tk.Button(
            input_box,
            text="➤",
            command=self._send_current,
            bg=P.purple_dark,
            fg=P.text,
            activebackground=P.purple,
            activeforeground=P.text,
            relief="flat",
            font=("Segoe UI Symbol", 18, "bold"),
            width=4,
            height=2,
            cursor="hand2",
        )
        self.send_button.grid(row=1, column=1, sticky="e", padx=(12, 0))

    # ---------- personality page ----------
    def _show_personality(self) -> None:
        self.current_view = "personality"
        self.header.grid_remove()
        self.chat_holder.grid_remove()
        self.input_footer.grid_remove()
        self._hide_extra_panels()
        if self.brain_panel is not None:
            self.brain_panel.grid_remove()
        if self.llm_panel is not None:
            self.llm_panel.grid_remove()
        if self.research_panel is not None:
            self.research_panel.grid_remove()
        if self.personality_panel is None:
            self._build_personality_panel()
        assert self.personality_panel is not None
        self.personality_panel.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self._sync_personality_controls_from_profile()
        self._refresh_personality_preview()
        self._set_status("Personality editor online", P.purple)

    def _build_personality_panel(self) -> None:
        self.personality_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.personality_panel.grid_columnconfigure(0, weight=1)
        self.personality_panel.grid_rowconfigure(2, weight=1)

        top = tk.Frame(self.personality_panel, bg=P.bg)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        tk.Label(top, text="♙", bg=P.bg, fg=P.purple, font=("Segoe UI Symbol", 38, "bold"), width=3).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))
        tk.Label(top, text="PERSONALITY", bg=P.bg, fg=P.text, font=("Segoe UI", 24, "bold")).grid(row=0, column=1, sticky="w")
        tk.Label(top, text="Shape the personality, behavior and communication style of M0N4C0.", bg=P.bg, fg=P.muted, font=("Segoe UI", 11)).grid(row=1, column=1, sticky="w", pady=(4, 0))

        action_bar = tk.Frame(top, bg=P.bg)
        action_bar.grid(row=0, column=2, rowspan=2, sticky="e")
        self._back_to_chat_button(action_bar).pack(side="left", padx=(0, 10))
        self._personality_action_button(action_bar, "Import Profile", self._import_personality_profile).pack(side="left", padx=(0, 10))
        self._personality_action_button(action_bar, "Export Profile", self._export_personality_profile).pack(side="left", padx=(0, 10))
        self._personality_action_button(action_bar, "Reset to Default", self._reset_personality_profile).pack(side="left", padx=(0, 10))
        self._personality_action_button(action_bar, "Save Changes", self._save_personality_profile, primary=True).pack(side="left")

        tabs = tk.Frame(self.personality_panel, bg=P.bg, pady=12)
        tabs.grid(row=1, column=0, sticky="ew")
        for i, (icon, label) in enumerate([
            ("▣", "Overview"), ("▤", "Core Traits"), ("⚙", "Behavior"), ("✦", "Reply Rules"), ("✈", "Telegram"), ("⌁", "Speech & Tone"), ("∞", "Memory & Learning"), ("◎", "Advanced")
        ]):
            fg = P.purple if i == 0 else P.muted
            tk.Label(tabs, text=f"{icon}  {label}", bg=P.bg, fg=fg, font=("Segoe UI", 10, "bold" if i == 0 else "normal"), padx=16, pady=8).pack(side="left")

        canvas_wrap = tk.Frame(self.personality_panel, bg=P.bg, highlightbackground=P.border, highlightthickness=1)
        canvas_wrap.grid(row=2, column=0, sticky="nsew")
        canvas_wrap.grid_columnconfigure(0, weight=1)
        canvas_wrap.grid_rowconfigure(0, weight=1)

        self.personality_canvas = tk.Canvas(canvas_wrap, bg=P.bg, highlightthickness=0, bd=0)
        self.personality_canvas.grid(row=0, column=0, sticky="nsew")
        self.personality_scroll = tk.Scrollbar(canvas_wrap, orient="vertical", command=self.personality_canvas.yview)
        self.personality_scroll.grid(row=0, column=1, sticky="ns")
        self.personality_canvas.configure(yscrollcommand=self.personality_scroll.set)
        self.personality_canvas.bind("<MouseWheel>", self._personality_mousewheel)

        content = tk.Frame(self.personality_canvas, bg=P.bg, padx=18, pady=18)
        self.personality_canvas_id = self.personality_canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _event: self.personality_canvas.configure(scrollregion=self.personality_canvas.bbox("all")))
        self.personality_canvas.bind("<Configure>", lambda event: self.personality_canvas.itemconfig(self.personality_canvas_id, width=event.width))
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)
        content.grid_columnconfigure(2, weight=1)

        # Control variables.
        self.personality_vars = {spec.key: tk.DoubleVar(value=self.personality_profile.sliders.get(spec.key, spec.default)) for spec in ALL_SLIDERS}
        self.personality_toggle_vars = {key: tk.BooleanVar(value=self.personality_profile.toggles.get(key, default)) for key, default in DEFAULT_TOGGLES.items()}
        self.personality_tone_var = tk.StringVar(value=self.personality_profile.tone)
        self.personality_language_var = tk.StringVar(value=self.personality_profile.language_style)
        self.personality_preset_var = tk.StringVar(value="Balanced (Recommended)")

        core = self._personality_card(content, "CORE TRAITS", 0, 0)
        for row, spec in enumerate(CORE_TRAITS):
            self._personality_slider(core, spec, row)
        preset_frame = tk.Frame(core, bg=P.panel_2)
        preset_frame.grid(row=len(CORE_TRAITS) * 3 + 1, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        preset_frame.grid_columnconfigure(0, weight=1)
        tk.Label(preset_frame, text="Trait Presets", bg=P.panel_2, fg=P.text, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        preset_menu = tk.OptionMenu(preset_frame, self.personality_preset_var, *PRESETS.keys())
        self._style_option_menu(preset_menu)
        preset_menu.grid(row=1, column=0, sticky="ew")
        self._personality_action_button(preset_frame, "Apply Preset", self._apply_personality_preset, primary=True).grid(row=1, column=1, sticky="e", padx=(10, 0))

        reply = self._personality_card(content, "REPLY RULES / WHEN TO TALK", 0, 1)
        for row, spec in enumerate(REPLY_RULES):
            self._personality_slider(reply, spec, row)

        speech = self._personality_card(content, "SPEECH & TONE", 0, 2)
        tk.Label(speech, text="Tone", bg=P.panel_2, fg=P.text, font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky="w", pady=(4, 6))
        tone_menu = tk.OptionMenu(speech, self.personality_tone_var, *TONE_OPTIONS, command=lambda _v: self._refresh_personality_preview())
        self._style_option_menu(tone_menu)
        tone_menu.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=(2, 8))
        tk.Label(speech, text="Language Style", bg=P.panel_2, fg=P.text, font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w", pady=(4, 6))
        lang_menu = tk.OptionMenu(speech, self.personality_language_var, *LANGUAGE_STYLE_OPTIONS, command=lambda _v: self._refresh_personality_preview())
        self._style_option_menu(lang_menu)
        lang_menu.grid(row=2, column=1, sticky="ew", padx=(12, 0), pady=(2, 8))
        speech.grid_columnconfigure(1, weight=1)
        for row, spec in enumerate(SPEECH_TONE, start=3):
            self._personality_slider(speech, spec, row)

        behavior = self._personality_card(content, "BEHAVIOR STYLE", 1, 0)
        for row, spec in enumerate(BEHAVIOR_STYLE):
            self._personality_slider(behavior, spec, row)

        autonomy = self._personality_card(content, "AUTONOMY / RESEARCH", 1, 1)
        for row, spec in enumerate(AUTONOMY_RESEARCH):
            self._personality_slider(autonomy, spec, row)

        memory_sliders = self._personality_card(content, "MEMORY BEHAVIOR", 1, 2)
        for row, spec in enumerate(MEMORY_BEHAVIOR):
            self._personality_slider(memory_sliders, spec, row)

        communication = self._personality_card(content, "COMMUNICATION STYLE", 2, 0)
        for row, spec in enumerate(COMMUNICATION_STYLE):
            self._personality_slider(communication, spec, row)

        safety = self._personality_card(content, "SAFETY / PRIVACY", 2, 1)
        for row, spec in enumerate(SAFETY_PRIVACY):
            self._personality_slider(safety, spec, row)

        toggles_card = self._personality_card(content, "ALL SWITCHES", 2, 2)
        toggle_labels = {
            "long_term_memory": ("Long Term Memory", "Remember important facts"),
            "learn_from_conversations": ("Learn From Conversations", "Improve by learning from our talks"),
            "adapt_personality_over_time": ("Adapt Personality Over Time", "Evolve based on interactions"),
            "context_awareness": ("Context Awareness", "Keep track of context changes"),
            "auto_research_learning_requests": ("Auto Research Learning Requests", "'Leer/onderzoek...' starts expert learning automatically"),
            "auto_web_search_fresh_topics": ("Auto Web Search Fresh Topics", "Use web for time-sensitive/new info"),
            "auto_update_brain_nodes": ("Auto Update Brain Nodes", "Refresh visible brain after learning"),
            "use_local_db_first": ("Use Local DB First", "Prefer local knowledge before generic answers"),
            "save_failed_prompts": ("Save Failed Prompts", "Store failures for self-improvement"),
            "respond_to_gui": ("Respond To GUI", "Always answer direct GUI chat"),
            "respond_to_telegram_dm": ("Respond To Telegram DM", "Reply in private Telegram chats"),
            "respond_in_groups": ("Respond In Groups", "Allow group chat replies"),
            "require_mention_in_groups": ("Require Mention In Groups", "Only answer if @mentioned/replied/commanded"),
            "answer_when_mentioned": ("Answer When Mentioned", "@mentions override quiet mode"),
            "answer_replies_to_bot": ("Answer Replies To Bot", "Replies to bot override quiet mode"),
            "ignore_low_value_chatter": ("Ignore Low-value Chatter", "Skip noise like 'lol', 'haha', one-word spam"),
            "split_long_telegram_messages": ("Split Long Telegram Messages", "Automatically send huge answers in multiple safe parts"),
            "number_split_telegram_messages": ("Number Split Messages", "Add [1/3], [2/3] labels to long replies"),
            "allow_proactive_suggestions": ("Allow Proactive Suggestions", "Suggest next steps when useful"),
            "allow_followup_questions": ("Allow Follow-up Questions", "Ask clarifying questions when needed"),
            "allow_playful_roasts": ("Allow Playful Roasts", "Only when roast mode/command is used"),
            "allow_street_slang": ("Allow Straattaal", "Use casual slang when style asks for it"),
            "technical_status": ("Technical Status", "Show useful local/tech status"),
            "show_activity_console": ("Show Activity Console", "Live sidebar terminal stays visible"),
            "privacy_mode": ("Privacy Mode", "Treat local data as private"),
            "log_private_messages": ("Log Private Messages", "Store conversations in SQLite"),
            "safe_mode_for_high_risk": ("High-risk Safe Mode", "Extra caution for medical/legal/financial/safety topics"),
        }
        for row, key in enumerate(DEFAULT_TOGGLES.keys()):
            label, desc = toggle_labels.get(key, (key.replace("_", " ").title(), ""))
            self._personality_toggle(toggles_card, key, label, desc, row)

        prompt_card = self._personality_card(content, "SYSTEM PROMPT PREVIEW", 3, 0, colspan=2)
        prompt_card.grid_columnconfigure(0, weight=1)
        tk.Label(prompt_card, text="Everything above is translated into this local system prompt + behavior policy.", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=0, column=0, sticky="w")
        self.personality_prompt_text = tk.Text(
            prompt_card,
            height=12,
            bg="#050812",
            fg="#95f08f",
            insertbackground=P.text,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            wrap="word",
            font=("Consolas", 10),
            padx=12,
            pady=10,
            cursor="arrow",
        )
        self.personality_prompt_text.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.personality_prompt_text.configure(state="disabled")
        self._personality_action_button(prompt_card, "Regenerate Prompt", self._refresh_personality_preview, primary=True).grid(row=2, column=0, sticky="w", pady=(10, 0))

        right_stack = tk.Frame(content, bg=P.bg)
        right_stack.grid(row=3, column=2, sticky="nsew", padx=8, pady=8)
        right_stack.grid_columnconfigure(0, weight=1)

        summary = tk.Frame(right_stack, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        summary.grid_columnconfigure(0, weight=1)
        tk.Label(summary, text="PERSONALITY SUMMARY", bg=P.panel_2, fg=P.text, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.personality_summary_label = tk.Label(summary, text="", bg=P.panel_2, fg=P.text, justify="left", anchor="nw", wraplength=380, font=("Consolas", 10))
        self.personality_summary_label.grid(row=1, column=0, sticky="ew")
        self.personality_meter = tk.Canvas(summary, height=42, bg=P.panel_2, highlightthickness=0, bd=0)
        self.personality_meter.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        quick = tk.Frame(right_stack, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        quick.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        quick.grid_columnconfigure(0, weight=1)
        quick.grid_columnconfigure(1, weight=1)
        tk.Label(quick, text="QUICK ACTIONS", bg=P.panel_2, fg=P.text, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        actions = [
            ("⭐ More Creative", lambda: self._nudge_personality({"creativity": 0.8, "curiosity": 0.5, "storytelling": 0.5})),
            ("🏢 More Formal", lambda: self._nudge_personality({"formality": 0.9, "sarcasm_wit": -0.4, "emoji_use": -0.4, "street_slang": -0.8})),
            ("⚡ More Direct", lambda: self._nudge_personality({"directness": 0.9, "response_length": -0.6, "decision_style": 0.5})),
            ("❤️ More Empathetic", lambda: self._nudge_personality({"empathy": 0.9, "warmth": 0.7, "patience": 0.4})),
            ("📊 More Analytical", lambda: self._nudge_personality({"analytical_depth": 0.9, "intelligence": 0.4, "examples": 0.4})),
            ("🔕 Quieter Groups", lambda: self._nudge_personality({"telegram_group_reply_frequency": -1.5, "silence_threshold": 1.0, "low_value_filter": 1.0, "interruptiveness": -0.8})),
            ("📣 More Active", lambda: self._nudge_personality({"response_frequency": 1.0, "telegram_group_reply_frequency": 1.4, "interruptiveness": 0.8, "silence_threshold": -0.8})),
            ("🧠 Research Beast", lambda: self._nudge_personality({"research_autonomy": 1.0, "learning_depth": 1.0, "auto_web_check": 1.0, "source_strictness": 0.7, "fact_checking": 0.7})),
            ("⟳ Reset Sliders", self._reset_personality_profile),
        ]
        for idx, (label, command) in enumerate(actions):
            self._personality_action_button(quick, label, command).grid(row=1 + idx // 2, column=idx % 2, sticky="ew", padx=6, pady=6)

        footer = tk.Frame(content, bg=P.panel, padx=16, pady=10, highlightbackground=P.border, highlightthickness=1)
        footer.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        footer.grid_columnconfigure(4, weight=1)
        self.personality_strength_chip = tk.Label(footer, text="", bg=P.panel, fg=P.text, font=self.font_small)
        self.personality_strength_chip.grid(row=0, column=0, sticky="w", padx=(0, 24))
        self.personality_adapt_chip = tk.Label(footer, text="", bg=P.panel, fg=P.text, font=self.font_small)
        self.personality_adapt_chip.grid(row=0, column=1, sticky="w", padx=(0, 24))
        self.personality_memory_chip = tk.Label(footer, text="", bg=P.panel, fg=P.text, font=self.font_small)
        self.personality_memory_chip.grid(row=0, column=2, sticky="w", padx=(0, 24))
        self.personality_reply_chip = tk.Label(footer, text="", bg=P.panel, fg=P.text, font=self.font_small)
        self.personality_reply_chip.grid(row=0, column=3, sticky="w", padx=(0, 24))
        self.personality_saved_chip = tk.Label(footer, text="", bg=P.panel, fg=P.muted, font=self.font_small)
        self.personality_saved_chip.grid(row=0, column=5, sticky="e")

        self._refresh_personality_preview()

    def _personality_action_button(self, parent: tk.Widget, text: str, command: Callable[[], None], primary: bool = False) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=P.purple_dark if primary else P.panel_2,
            fg=P.text,
            activebackground=P.purple if primary else P.purple_dark,
            activeforeground=P.text,
            relief="flat",
            padx=16,
            pady=8,
            cursor="hand2",
            font=("Segoe UI", 10, "bold" if primary else "normal"),
        )

    def _personality_card(self, parent: tk.Widget, title: str, row: int, column: int, colspan: int = 1) -> tk.Frame:
        card = tk.Frame(parent, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        card.grid(row=row, column=column, columnspan=colspan, sticky="nsew", padx=8, pady=8)
        card.grid_columnconfigure(0, weight=1)
        tk.Label(card, text=title, bg=P.panel_2, fg=P.text, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        return card

    def _personality_slider(self, parent: tk.Widget, spec: Any, row: int) -> None:
        grid_row = row * 3 + 1
        label = tk.Label(parent, text=spec.label, bg=P.panel_2, fg=P.text, font=("Segoe UI", 10, "bold"), anchor="w")
        label.grid(row=grid_row, column=0, sticky="w", pady=(3, 1))
        desc = tk.Label(parent, text=spec.description, bg=P.panel_2, fg=P.muted, font=("Segoe UI", 8), anchor="w")
        desc.grid(row=grid_row + 1, column=0, sticky="w", pady=(0, 4))
        var = self.personality_vars[spec.key]
        value_label = tk.Label(parent, text=f"{var.get():.1f}", bg=P.panel, fg=P.text, font=("Consolas", 10), width=4, padx=6, pady=4)
        value_label.grid(row=grid_row, column=2, rowspan=2, sticky="e", padx=(10, 0))
        self.personality_value_labels[spec.key] = value_label
        scale = tk.Scale(
            parent,
            from_=0,
            to=10,
            resolution=0.1,
            orient="horizontal",
            showvalue=0,
            variable=var,
            command=lambda _v, key=spec.key: self._on_personality_slider_changed(key),
            bg=P.panel_2,
            fg=P.text,
            troughcolor="#313849",
            activebackground=P.purple,
            highlightthickness=0,
            bd=0,
            sliderrelief="flat",
            length=175,
        )
        scale.grid(row=grid_row, column=1, rowspan=2, sticky="ew", padx=(12, 0))
        parent.grid_columnconfigure(1, weight=1)
        # Small axis labels under the slider.
        axis = tk.Frame(parent, bg=P.panel_2)
        axis.grid(row=grid_row + 2, column=1, sticky="ew", padx=(12, 0), pady=(0, 6))
        axis.grid_columnconfigure(1, weight=1)
        tk.Label(axis, text=spec.low_label, bg=P.panel_2, fg=P.muted_2, font=("Segoe UI", 7)).grid(row=0, column=0, sticky="w")
        tk.Label(axis, text=spec.high_label, bg=P.panel_2, fg=P.muted_2, font=("Segoe UI", 7)).grid(row=0, column=2, sticky="e")

    def _personality_toggle(self, parent: tk.Widget, key: str, label: str, desc: str, row: int) -> None:
        var = self.personality_toggle_vars[key]
        frame = tk.Frame(parent, bg=P.panel_2)
        frame.grid(row=row + 1, column=0, sticky="ew", pady=7)
        frame.grid_columnconfigure(0, weight=1)
        tk.Label(frame, text=label, bg=P.panel_2, fg=P.text, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(frame, text=desc, bg=P.panel_2, fg=P.muted, font=("Segoe UI", 8)).grid(row=1, column=0, sticky="w", pady=(2, 0))
        btn = tk.Checkbutton(
            frame,
            variable=var,
            command=self._refresh_personality_preview,
            text="ON",
            onvalue=True,
            offvalue=False,
            bg=P.panel_2,
            fg=P.text,
            activebackground=P.panel_2,
            activeforeground=P.text,
            selectcolor=P.purple_dark,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        btn.grid(row=0, column=1, rowspan=2, sticky="e")

    def _bind_mousewheel_to_canvas(self, canvas: tk.Canvas) -> None:
        def _wheel(event: tk.Event) -> None:
            try:
                delta = getattr(event, "delta", 0)
                if delta:
                    canvas.yview_scroll(int(-1 * (delta / 120)), "units")
            except tk.TclError:
                pass
        def _linux_up(_event: tk.Event) -> None:
            try: canvas.yview_scroll(-3, "units")
            except tk.TclError: pass
        def _linux_down(_event: tk.Event) -> None:
            try: canvas.yview_scroll(3, "units")
            except tk.TclError: pass
        canvas.bind("<MouseWheel>", _wheel)
        canvas.bind("<Button-4>", _linux_up)
        canvas.bind("<Button-5>", _linux_down)

    def _copy_activity_to_widget(self, widget: tk.Text | None) -> None:
        if widget is None or not hasattr(self, "activity_console"):
            return
        try:
            data = self.activity_console.get("1.0", "end").strip()
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", data or "Live feed is ready. New runtime events will appear in the sidebar and here.")
            widget.configure(state="disabled")
        except tk.TclError:
            pass

    def _style_option_menu(self, menu: tk.OptionMenu) -> None:
        menu.configure(bg=P.panel, fg=P.text, activebackground=P.purple_dark, activeforeground=P.text, relief="flat", highlightthickness=1, highlightbackground=P.border, bd=0, padx=10, pady=6, cursor="hand2")
        try:
            menu["menu"].configure(bg=P.panel, fg=P.text, activebackground=P.purple_dark, activeforeground=P.text, relief="flat")
        except tk.TclError:
            pass

    def _back_to_chat_button(self, parent: tk.Widget, text: str = "← Back to chat") -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=self._show_chat_view,
            bg=P.panel_2,
            fg=P.text,
            activebackground=P.purple_dark,
            activeforeground=P.text,
            relief="flat",
            padx=14,
            pady=8,
            cursor="hand2",
            font=("Segoe UI", 10, "bold"),
        )


    def _hide_extra_panels(self) -> None:
        for attr in ("personality_panel", "llm_panel", "research_panel", "mission_panel", "brain_panel", "database_panel", "telegram_panel", "idle_panel", "performance_panel", "memory_panel", "logs_panel", "image_panel", "trading_panel", "live_feed_panel", "tools_panel", "worldclass_panel", "build_agent_panel", "dependency_panel", "benchmark_panel", "error_panel", "plugin_panel"):
            panel = getattr(self, attr, None)
            if panel is not None:
                try:
                    panel.grid_remove()
                except tk.TclError:
                    pass

    def _on_personality_slider_changed(self, key: str) -> None:
        var = self.personality_vars.get(key)
        label = self.personality_value_labels.get(key)
        if var is not None and label is not None:
            label.configure(text=f"{var.get():.1f}")
        self._refresh_personality_preview()

    def _sync_profile_from_personality_controls(self) -> PersonalityProfile:
        profile = PersonalityProfile.default()
        profile.sliders = {spec.key: round(float(self.personality_vars[spec.key].get()), 2) for spec in ALL_SLIDERS if spec.key in self.personality_vars}
        profile.toggles = {key: bool(var.get()) for key, var in self.personality_toggle_vars.items()}
        profile.tone = self.personality_tone_var.get() if self.personality_tone_var is not None else profile.tone
        profile.language_style = self.personality_language_var.get() if self.personality_language_var is not None else profile.language_style
        self.personality_profile = profile
        return profile

    def _sync_personality_controls_from_profile(self) -> None:
        if not self.personality_vars:
            return
        for spec in ALL_SLIDERS:
            if spec.key in self.personality_vars:
                self.personality_vars[spec.key].set(self.personality_profile.sliders.get(spec.key, spec.default))
                if spec.key in self.personality_value_labels:
                    self.personality_value_labels[spec.key].configure(text=f"{self.personality_vars[spec.key].get():.1f}")
        for key, default in DEFAULT_TOGGLES.items():
            if key in self.personality_toggle_vars:
                self.personality_toggle_vars[key].set(self.personality_profile.toggles.get(key, default))
        if self.personality_tone_var is not None:
            self.personality_tone_var.set(self.personality_profile.tone)
        if self.personality_language_var is not None:
            self.personality_language_var.set(self.personality_profile.language_style)

    def _refresh_personality_preview(self) -> None:
        if not self.personality_vars:
            return
        profile = self._sync_profile_from_personality_controls()
        if hasattr(self, "personality_summary_label"):
            self.personality_summary_label.configure(text=profile.summary())
        if hasattr(self, "personality_prompt_text"):
            self.personality_prompt_text.configure(state="normal")
            self.personality_prompt_text.delete("1.0", "end")
            self.personality_prompt_text.insert("1.0", prompt_preview(profile))
            self.personality_prompt_text.configure(state="disabled")
        if hasattr(self, "personality_strength_chip"):
            self.personality_strength_chip.configure(text=f"☢ Personality Strength  {profile.strength_percent()}%")
            self.personality_adapt_chip.configure(text=f"♙ Adaptability  {'High' if profile.toggles.get('adapt_personality_over_time') else 'Manual'}")
            self.personality_memory_chip.configure(text=f"▣ Memory Integration  {'Active' if profile.toggles.get('long_term_memory') else 'Off'}")
            if hasattr(self, "personality_reply_chip"):
                group_freq = profile.sliders.get('telegram_group_reply_frequency', 0.0)
                self.personality_reply_chip.configure(text=f"✈ Group Replies  {group_freq:.1f}/10")
            self.personality_saved_chip.configure(text=f"Last Saved: {profile.updated_at[:19].replace('T', ' ')}")
        self._draw_personality_meter(profile)

    def _draw_personality_meter(self, profile: PersonalityProfile) -> None:
        meter = getattr(self, "personality_meter", None)
        if meter is None:
            return
        meter.delete("all")
        width = max(260, meter.winfo_width() or 360)
        height = 42
        strength = profile.strength_percent() / 100
        meter.create_rectangle(0, 16, width, 28, fill="#111827", outline="")
        meter.create_rectangle(0, 16, width * strength, 28, fill=P.purple_dark, outline="")
        # Tiny waveform-style personality fingerprint.
        points = []
        vals = [profile.sliders.get(spec.key, 5.0) for spec in ALL_SLIDERS[:14]]
        for i, val in enumerate(vals):
            x = 6 + i * max(12, (width - 12) / max(1, len(vals) - 1))
            y = 35 - (val / 10) * 22
            points.append((x, y))
        for i in range(len(points) - 1):
            meter.create_line(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1], fill=P.purple, width=2, smooth=True)

    def _save_personality_profile(self) -> None:
        profile = self._sync_profile_from_personality_controls()
        try:
            save_personality(self.settings, profile)
            self._refresh_personality_preview()
            self._set_status("Personality saved", P.success)
            self._emit_activity("Personality profile saved to data/personality_profile.json", "OK")
            messagebox.showinfo("M0N4C0 Personality", "Personality opgeslagen. Nieuwe chat-antwoorden gebruiken deze stijl meteen.")
        except Exception as exc:
            self._set_status("Personality save error", P.danger)
            self._emit_activity(f"Personality save error: {type(exc).__name__}: {exc}", "ERR")
            messagebox.showerror("M0N4C0 Personality", f"Opslaan lukte niet:\n{type(exc).__name__}: {exc}")

    def _reset_personality_profile(self) -> None:
        self.personality_profile = PersonalityProfile.default()
        self._sync_personality_controls_from_profile()
        self._refresh_personality_preview()
        self._set_status("Personality reset to defaults", P.gold)
        self._emit_activity("Personality controls reset to default values. Click Save Changes to persist.", "WARN")

    def _apply_personality_preset(self) -> None:
        name = self.personality_preset_var.get() if self.personality_preset_var is not None else "Balanced (Recommended)"
        self.personality_profile.apply_preset(name)
        self._sync_personality_controls_from_profile()
        self._refresh_personality_preview()
        self._set_status(f"Preset applied: {name}", P.purple)
        self._emit_activity(f"Personality preset applied: {name}. Click Save Changes to persist.", "STEP")

    def _nudge_personality(self, deltas: dict[str, float]) -> None:
        for key, delta in deltas.items():
            var = self.personality_vars.get(key)
            if var is not None:
                var.set(max(0.0, min(10.0, float(var.get()) + float(delta))))
                label = self.personality_value_labels.get(key)
                if label is not None:
                    label.configure(text=f"{var.get():.1f}")
        self._refresh_personality_preview()

    def _export_personality_profile(self) -> None:
        profile = self._sync_profile_from_personality_controls()
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export M0N4C0 Personality Profile",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="m0n4c0_personality_profile.json",
        )
        if not path:
            return
        try:
            import json
            from pathlib import Path
            Path(path).write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
            self._emit_activity(f"Personality profile exported: {path}", "OK")
            messagebox.showinfo("M0N4C0 Personality", "Profile geëxporteerd.")
        except Exception as exc:
            messagebox.showerror("M0N4C0 Personality", f"Export fout:\n{type(exc).__name__}: {exc}")

    def _import_personality_profile(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Import M0N4C0 Personality Profile",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            import json
            from pathlib import Path
            self.personality_profile = PersonalityProfile.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
            self._sync_personality_controls_from_profile()
            self._refresh_personality_preview()
            self._emit_activity(f"Personality profile imported: {path}. Click Save Changes to persist.", "OK")
            messagebox.showinfo("M0N4C0 Personality", "Profile geïmporteerd. Klik Save Changes om hem vast op te slaan.")
        except Exception as exc:
            messagebox.showerror("M0N4C0 Personality", f"Import fout:\n{type(exc).__name__}: {exc}")

    def _personality_mousewheel(self, event: tk.Event) -> str:
        if self.current_view != "personality":
            return ""
        try:
            self.personality_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except tk.TclError:
            pass
        return "break"

    # ---------- LLM models page ----------
    def _show_llm_models(self) -> None:
        self.current_view = "llm_models"
        self.header.grid_remove()
        self.chat_holder.grid_remove()
        self.input_footer.grid_remove()
        self._hide_extra_panels()
        if self.personality_panel is not None:
            self.personality_panel.grid_remove()
        if self.brain_panel is not None:
            self.brain_panel.grid_remove()
        if self.research_panel is not None:
            self.research_panel.grid_remove()
        if self.llm_panel is None:
            self._build_llm_models_panel()
        assert self.llm_panel is not None
        self.llm_panel.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self._set_status("LLM Models online", P.purple)
        self._llm_refresh_models()

    def _build_llm_models_panel(self) -> None:
        self.llm_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.llm_panel.grid_columnconfigure(0, weight=1)
        self.llm_panel.grid_rowconfigure(1, weight=1)

        self.llm_search_var = tk.StringVar(value="")
        self.llm_filter_var = tk.StringVar(value="All Types")
        self.llm_base_url_var = tk.StringVar(value=self.llm_config.base_url)
        self.llm_temperature_var = tk.DoubleVar(value=self.llm_config.temperature)
        self.llm_max_tokens_var = tk.IntVar(value=self.llm_config.max_tokens)
        self.llm_context_var = tk.IntVar(value=self.llm_config.context_chars)
        self.llm_top_p_var = tk.DoubleVar(value=self.llm_config.top_p)
        self.llm_repeat_penalty_var = tk.DoubleVar(value=self.llm_config.repeat_penalty)
        self.llm_top_k_var = tk.IntVar(value=self.llm_config.top_k)
        self.llm_min_p_var = tk.DoubleVar(value=self.llm_config.min_p)
        self.llm_programming_router_var = tk.BooleanVar(value=self.llm_config.programming_router_enabled)
        self.llm_single_model_var = tk.BooleanVar(value=str(getattr(self.llm_config, "model_mode", "split")) == "single")

        top = tk.Frame(self.llm_panel, bg=P.bg)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        tk.Label(top, text="◈", bg=P.bg, fg=P.purple, font=("Segoe UI Symbol", 38, "bold"), width=3).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))
        tk.Label(top, text="LLM MODELS", bg=P.bg, fg=P.text, font=("Segoe UI", 24, "bold")).grid(row=0, column=1, sticky="w")
        tk.Label(top, text="Manage and select your downloaded LM Studio models.", bg=P.bg, fg=P.muted, font=("Segoe UI", 11)).grid(row=1, column=1, sticky="w", pady=(4, 0))
        action_bar = tk.Frame(top, bg=P.bg)
        action_bar.grid(row=0, column=2, rowspan=2, sticky="e")
        self._back_to_chat_button(action_bar).pack(side="left", padx=(0, 10))
        self._llm_button(action_bar, "⟳ Refresh Models", self._llm_refresh_models).pack(side="left", padx=(0, 10))
        self._llm_button(action_bar, "↗ Open LM Studio", self._llm_open_lm_studio).pack(side="left", padx=(0, 10))
        self._llm_button(action_bar, "▣ Save Settings", self._llm_save_settings, primary=True).pack(side="left")

        scroll_shell = tk.Frame(self.llm_panel, bg=P.bg)
        scroll_shell.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        scroll_shell.grid_columnconfigure(0, weight=1)
        scroll_shell.grid_rowconfigure(0, weight=1)
        self.llm_page_canvas = tk.Canvas(scroll_shell, bg=P.bg, bd=0, highlightthickness=0)
        self.llm_page_canvas.grid(row=0, column=0, sticky="nsew")
        self.llm_page_scrollbar = tk.Scrollbar(scroll_shell, orient="vertical", command=self.llm_page_canvas.yview)
        self.llm_page_scrollbar.grid(row=0, column=1, sticky="ns")
        self.llm_page_canvas.configure(yscrollcommand=self.llm_page_scrollbar.set)
        self.llm_scroll_inner = tk.Frame(self.llm_page_canvas, bg=P.bg)
        self.llm_scroll_window = self.llm_page_canvas.create_window((0, 0), window=self.llm_scroll_inner, anchor="nw")
        self.llm_scroll_inner.bind("<Configure>", lambda _e: self.llm_page_canvas.configure(scrollregion=self.llm_page_canvas.bbox("all")))
        self.llm_page_canvas.bind("<Configure>", lambda e: self.llm_page_canvas.itemconfig(self.llm_scroll_window, width=e.width))
        self._bind_mousewheel_to_canvas(self.llm_page_canvas)

        body = tk.Frame(self.llm_scroll_inner, bg=P.bg)
        body.grid(row=0, column=0, sticky="nsew")
        self.llm_scroll_inner.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(0, minsize=520, weight=1)
        body.grid_columnconfigure(1, minsize=560, weight=1)
        body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)
        head = tk.Frame(left, bg=P.panel_2)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        head.grid_columnconfigure(0, weight=1)
        tk.Label(head, text="AVAILABLE MODELS", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        self.llm_found_badge = tk.Label(head, text="0 found", bg=P.purple_dark, fg=P.text, font=("Segoe UI", 9, "bold"), padx=9, pady=4)
        self.llm_found_badge.grid(row=0, column=1, sticky="e")

        list_shell = tk.Frame(left, bg=P.panel, highlightbackground=P.border, highlightthickness=1)
        list_shell.grid(row=1, column=0, sticky="nsew")
        list_shell.grid_columnconfigure(0, weight=1)
        list_shell.grid_rowconfigure(0, weight=1)
        self.llm_list_canvas = tk.Canvas(list_shell, bg=P.panel, bd=0, highlightthickness=0)
        self.llm_list_canvas.grid(row=0, column=0, sticky="nsew")
        self.llm_list_scroll = tk.Scrollbar(list_shell, orient="vertical", command=self.llm_list_canvas.yview)
        self.llm_list_scroll.grid(row=0, column=1, sticky="ns")
        self.llm_list_canvas.configure(yscrollcommand=self.llm_list_scroll.set)
        self.llm_model_list_inner = tk.Frame(self.llm_list_canvas, bg=P.panel)
        self.llm_list_window = self.llm_list_canvas.create_window((0, 0), window=self.llm_model_list_inner, anchor="nw")
        self.llm_model_list_inner.bind("<Configure>", lambda _e: self.llm_list_canvas.configure(scrollregion=self.llm_list_canvas.bbox("all")))
        self.llm_list_canvas.bind("<Configure>", lambda e: self.llm_list_canvas.itemconfig(self.llm_list_window, width=e.width))

        filters = tk.Frame(left, bg=P.panel_2)
        filters.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        filters.grid_columnconfigure(0, weight=1)
        search = tk.Entry(filters, textvariable=self.llm_search_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", font=self.font_body, highlightbackground=P.border, highlightthickness=1)
        search.grid(row=0, column=0, sticky="ew", ipady=8, padx=(0, 10))
        search.insert(0, "")
        search.bind("<KeyRelease>", lambda _event: self._llm_render_model_list())
        filter_menu = tk.OptionMenu(filters, self.llm_filter_var, "All Types", "Instruct", "Vision", "Embedding", "Loaded/Served", "Base/Local", command=lambda _v: self._llm_render_model_list())
        self._style_option_menu(filter_menu)
        filter_menu.grid(row=0, column=1, sticky="e")

        right = tk.Frame(body, bg=P.bg)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)
        right.grid_rowconfigure(2, weight=1)

        details = tk.Frame(right, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        details.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        details.grid_columnconfigure(1, weight=1)
        tk.Label(details, text="ACTIVE MODEL DETAILS", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self.llm_detail_title = tk.Label(details, text=self.llm_config.model_id or "No model selected", bg=P.panel_2, fg=P.text, font=("Segoe UI", 14, "bold"), anchor="w", justify="left")
        self.llm_detail_title.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.llm_detail_sub = tk.Label(details, text="", bg=P.panel_2, fg=P.muted, font=self.font_small, anchor="w", justify="left")
        self.llm_detail_sub.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 10))
        self.llm_detail_grid = tk.Label(details, text="", bg=P.panel, fg=P.text, font=("Consolas", 10), justify="left", anchor="nw", padx=12, pady=10)
        self.llm_detail_grid.grid(row=3, column=0, columnspan=2, sticky="ew")
        action_line = tk.Frame(details, bg=P.panel_2)
        action_line.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        action_line.grid_columnconfigure(0, weight=1)
        self._llm_button(action_line, "Use as Chat + Save", self._llm_use_selected, primary=True).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._llm_button(action_line, "Use as Code + Save", self._llm_use_selected_as_coding, primary=True).grid(row=0, column=1, sticky="ew", padx=8)
        self._llm_button(action_line, "Use for ALL + Save", self._llm_use_selected_for_all, primary=True).grid(row=0, column=2, sticky="ew", padx=8)
        self._llm_button(action_line, "Test Selected", self._llm_test_model).grid(row=0, column=3, sticky="ew", padx=8)
        self._llm_button(action_line, "Model Info", self._llm_show_model_info).grid(row=0, column=4, sticky="ew", padx=(8, 0))

        params = tk.Frame(right, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        params.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        params.grid_columnconfigure(0, weight=1)
        params.grid_columnconfigure(1, weight=1)
        tk.Label(params, text="MODEL PARAMETERS", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self._llm_param_slider(params, "context", "Context Chars", self.llm_context_var, 1500, 200000, 500, 1, 0)
        self._llm_param_slider(params, "temperature", "Temperature", self.llm_temperature_var, 0.0, 2.0, 0.01, 2, 1)
        self._llm_param_slider(params, "top_p", "Top P", self.llm_top_p_var, 0.01, 1.0, 0.01, 3, 0)
        self._llm_param_slider(params, "max_tokens", "Max Tokens", self.llm_max_tokens_var, 64, 12000, 64, 4, 1)
        self._llm_param_slider(params, "repeat_penalty", "Repeat Penalty", self.llm_repeat_penalty_var, 0.8, 2.0, 0.01, 5, 0)
        self._llm_param_slider(params, "top_k", "Top K", self.llm_top_k_var, 0, 200, 1, 6, 1)
        self._llm_param_slider(params, "min_p", "Min P", self.llm_min_p_var, 0.0, 1.0, 0.01, 7, 0)
        self._llm_button(params, "Reset Parameters", self._llm_reset_parameters).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        system_card = tk.Frame(right, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        system_card.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        system_card.grid_columnconfigure(0, weight=1)
        system_card.grid_rowconfigure(2, weight=1)
        tk.Label(system_card, text="LIVE SYSTEM PROMPT", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(system_card, text="Wijzigingen worden live toegepast op de volgende chat/Telegram response. Geen restart nodig.", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=1, column=0, sticky="w", pady=(3, 8))
        self.llm_system_prompt_text = tk.Text(system_card, height=7, bg="#03050b", fg="#d9e0ff", insertbackground=P.text, relief="flat", wrap="word", font=("Consolas", 9), padx=10, pady=8)
        self.llm_system_prompt_text.grid(row=2, column=0, sticky="nsew")
        self.llm_system_prompt_text.insert("1.0", self.llm_config.system_prompt or SYSTEM_PROMPT)
        self.llm_system_prompt_text.bind("<KeyRelease>", self._llm_schedule_live_system_prompt_apply)
        prompt_buttons = tk.Frame(system_card, bg=P.panel_2)
        prompt_buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        prompt_buttons.grid_columnconfigure(0, weight=1)
        prompt_buttons.grid_columnconfigure(1, weight=1)
        prompt_buttons.grid_columnconfigure(2, weight=1)
        self._llm_button(prompt_buttons, "Apply Live + Save", self._llm_save_settings, primary=True).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._llm_button(prompt_buttons, "Open Big Editor", self._llm_open_system_prompt_editor).grid(row=0, column=1, sticky="ew", padx=6)
        self._llm_button(prompt_buttons, "Reset Prompt", self._llm_reset_system_prompt).grid(row=0, column=2, sticky="ew", padx=(6, 0))

        bottom = tk.Frame(self.llm_scroll_inner, bg=P.bg)
        bottom.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)
        bottom.grid_columnconfigure(2, weight=1)

        connection = tk.Frame(bottom, bg=P.panel_2, padx=16, pady=14, highlightbackground=P.border, highlightthickness=1)
        connection.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        connection.grid_columnconfigure(1, weight=1)
        tk.Label(connection, text="LM STUDIO CONNECTION", bg=P.panel_2, fg=P.text, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        tk.Label(connection, text="Base URL", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=1, column=0, sticky="w", pady=5)
        tk.Entry(connection, textvariable=self.llm_base_url_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", highlightbackground=P.border, highlightthickness=1).grid(row=1, column=1, sticky="ew", ipady=6, pady=5)
        self.llm_connection_status = tk.Label(connection, text="Not checked yet", bg=P.panel_2, fg=P.muted, justify="left", font=self.font_small)
        self.llm_connection_status.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 10))
        self._llm_button(connection, "Test Connection", self._llm_test_connection, primary=True).grid(row=3, column=0, columnspan=2, sticky="ew")

        config_card = tk.Frame(bottom, bg=P.panel_2, padx=16, pady=14, highlightbackground=P.border, highlightthickness=1)
        config_card.grid(row=0, column=1, sticky="nsew", padx=8)
        config_card.grid_columnconfigure(0, weight=1)
        tk.Label(config_card, text="CONFIG", bg=P.panel_2, fg=P.text, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.llm_active_chip = tk.Label(config_card, text="", bg=P.panel, fg=P.text, justify="left", anchor="nw", font=("Consolas", 10), padx=12, pady=10)
        self.llm_active_chip.grid(row=1, column=0, sticky="ew")
        single_toggle = tk.Checkbutton(
            config_card,
            text="Gebruik één model voor chat + code + tools",
            variable=self.llm_single_model_var,
            bg=P.panel_2, fg=P.text, activebackground=P.panel_2, activeforeground=P.text,
            selectcolor=P.purple_dark, relief="flat", font=self.font_small, cursor="hand2",
            command=self._llm_single_mode_changed,
        )
        single_toggle.grid(row=2, column=0, sticky="w", pady=(10, 0))
        router_toggle = tk.Checkbutton(
            config_card,
            text="Auto-route programming prompts to Coding Model",
            variable=self.llm_programming_router_var,
            bg=P.panel_2, fg=P.text, activebackground=P.panel_2, activeforeground=P.text,
            selectcolor=P.purple_dark, relief="flat", font=self.font_small, cursor="hand2",
        )
        router_toggle.grid(row=3, column=0, sticky="w", pady=(4, 0))
        btnrow = tk.Frame(config_card, bg=P.panel_2)
        btnrow.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        btnrow.grid_columnconfigure(0, weight=1)
        btnrow.grid_columnconfigure(1, weight=1)
        self._llm_button(btnrow, "Import", self._llm_import_config).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self._llm_button(btnrow, "Export", self._llm_export_config).grid(row=0, column=1, sticky="ew", padx=(5, 0))

        quick = tk.Frame(bottom, bg=P.panel_2, padx=16, pady=14, highlightbackground=P.border, highlightthickness=1)
        quick.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        quick.grid_columnconfigure(0, weight=1)
        quick.grid_columnconfigure(1, weight=1)
        tk.Label(quick, text="QUICK ACTIONS", bg=P.panel_2, fg=P.text, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        quick_actions = [
            ("Download Models", self._llm_open_lm_studio),
            ("Benchmark", self._llm_benchmark),
            ("Reset Defaults", self._llm_reset_defaults),
            ("View Logs", self._llm_view_logs),
        ]
        for idx, (label, cmd) in enumerate(quick_actions):
            self._llm_button(quick, label, cmd).grid(row=1 + idx // 2, column=idx % 2, sticky="ew", padx=5, pady=5)

        footer = tk.Frame(self.llm_panel, bg=P.panel, padx=14, pady=10, highlightbackground=P.border, highlightthickness=1)
        footer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        footer.grid_columnconfigure(4, weight=1)
        self.llm_footer_active = tk.Label(footer, text="", bg=P.panel, fg=P.text, font=self.font_small)
        self.llm_footer_active.grid(row=0, column=0, sticky="w", padx=(0, 24))
        self.llm_footer_backend = tk.Label(footer, text="Backend  LM Studio", bg=P.panel, fg=P.muted, font=self.font_small)
        self.llm_footer_backend.grid(row=0, column=1, sticky="w", padx=(0, 24))
        self.llm_footer_status = tk.Label(footer, text="Status  idle", bg=P.panel, fg=P.muted, font=self.font_small)
        self.llm_footer_status.grid(row=0, column=2, sticky="w", padx=(0, 24))
        self.llm_footer_saved = tk.Label(footer, text="", bg=P.panel, fg=P.muted, font=self.font_small)
        self.llm_footer_saved.grid(row=0, column=5, sticky="e")

        self._llm_refresh_detail()

    def _llm_button(self, parent: tk.Widget, text: str, command: Callable[[], None], primary: bool = False) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=P.purple_dark if primary else P.panel_2,
            fg=P.text,
            activebackground=P.purple if primary else P.purple_dark,
            activeforeground=P.text,
            relief="flat",
            padx=14,
            pady=8,
            cursor="hand2",
            font=("Segoe UI", 10, "bold" if primary else "normal"),
        )

    def _llm_param_slider(self, parent: tk.Widget, key: str, label: str, variable: tk.Variable, from_: float, to: float, resolution: float, row: int, column: int) -> None:
        card = tk.Frame(parent, bg=P.panel_2)
        card.grid(row=row, column=column, sticky="ew", padx=8, pady=5)
        card.grid_columnconfigure(1, weight=1)
        tk.Label(card, text=label, bg=P.panel_2, fg=P.text, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 10))
        value = tk.Label(card, text=str(variable.get()), bg=P.panel, fg=P.text, font=("Consolas", 10), width=8, padx=7, pady=4)
        value.grid(row=0, column=2, sticky="e", padx=(10, 0))
        self.llm_param_value_labels[key] = value
        scale = tk.Scale(
            card,
            from_=from_,
            to=to,
            resolution=resolution,
            orient="horizontal",
            showvalue=0,
            variable=variable,
            command=lambda _v, k=key: self._llm_param_changed(k),
            bg=P.panel_2,
            fg=P.text,
            troughcolor="#313849",
            activebackground=P.purple,
            highlightthickness=0,
            bd=0,
            sliderrelief="flat",
            length=175,
        )
        scale.grid(row=0, column=1, sticky="ew")

    def _llm_param_changed(self, key: str) -> None:
        mapping = {
            "context": self.llm_context_var,
            "temperature": self.llm_temperature_var,
            "top_p": self.llm_top_p_var,
            "max_tokens": self.llm_max_tokens_var,
            "repeat_penalty": self.llm_repeat_penalty_var,
            "top_k": self.llm_top_k_var,
            "min_p": self.llm_min_p_var,
        }
        var = mapping.get(key)
        label = self.llm_param_value_labels.get(key)
        if var is not None and label is not None:
            value = var.get()
            if isinstance(value, float):
                label.configure(text=f"{value:.2f}")
            else:
                label.configure(text=str(value))

    def _llm_config_from_controls(self) -> LLMRuntimeConfig:
        return LLMRuntimeConfig(
            base_url=(self.llm_base_url_var.get().strip() if self.llm_base_url_var else self.settings.lmstudio_base_url).rstrip("/"),
            model_id=self.llm_selected_id or self.settings.lmstudio_model,
            coding_base_url=(self.llm_base_url_var.get().strip() if self.llm_base_url_var else getattr(self.settings, "lmstudio_coding_base_url", self.settings.lmstudio_base_url)).rstrip("/"),
            coding_model_id=(self.llm_selected_id if (self.llm_single_model_var is not None and self.llm_single_model_var.get()) else (self.llm_coding_selected_id or getattr(self.settings, "lmstudio_coding_model", "") or self.llm_selected_id or self.settings.lmstudio_model)),
            research_base_url=(self.llm_base_url_var.get().strip() if self.llm_base_url_var else getattr(self.settings, "lmstudio_research_base_url", self.settings.lmstudio_base_url)).rstrip("/"),
            research_model_id=self.llm_selected_id or getattr(self.settings, "lmstudio_research_model", "") or self.settings.lmstudio_model,
            telegram_base_url=(self.llm_base_url_var.get().strip() if self.llm_base_url_var else getattr(self.settings, "lmstudio_telegram_base_url", self.settings.lmstudio_base_url)).rstrip("/"),
            telegram_model_id=self.llm_selected_id or getattr(self.settings, "lmstudio_telegram_model", "") or self.settings.lmstudio_model,
            image_base_url=(self.llm_base_url_var.get().strip() if self.llm_base_url_var else getattr(self.settings, "lmstudio_image_base_url", self.settings.lmstudio_base_url)).rstrip("/"),
            image_model_id=self.llm_selected_id or getattr(self.settings, "lmstudio_image_model", "") or self.settings.lmstudio_model,
            trading_base_url=(self.llm_base_url_var.get().strip() if self.llm_base_url_var else getattr(self.settings, "lmstudio_trading_base_url", self.settings.lmstudio_base_url)).rstrip("/"),
            trading_model_id=self.llm_selected_id or getattr(self.settings, "lmstudio_trading_model", "") or self.settings.lmstudio_model,
            model_mode="single" if (self.llm_single_model_var is not None and self.llm_single_model_var.get()) else "split",
            programming_router_enabled=bool(self.llm_programming_router_var.get() if self.llm_programming_router_var else getattr(self.settings, "llm_programming_router_enabled", True)),
            temperature=float(self.llm_temperature_var.get() if self.llm_temperature_var else self.settings.llm_temperature),
            max_tokens=int(self.llm_max_tokens_var.get() if self.llm_max_tokens_var else self.settings.llm_max_output_tokens),
            context_chars=int(self.llm_context_var.get() if self.llm_context_var else self.settings.llm_max_context_chars),
            top_p=float(self.llm_top_p_var.get() if self.llm_top_p_var else getattr(self.settings, "llm_top_p", 0.9)),
            repeat_penalty=float(self.llm_repeat_penalty_var.get() if self.llm_repeat_penalty_var else getattr(self.settings, "llm_repeat_penalty", 1.1)),
            top_k=int(self.llm_top_k_var.get() if self.llm_top_k_var else getattr(self.settings, "llm_top_k", 40)),
            min_p=float(self.llm_min_p_var.get() if self.llm_min_p_var else getattr(self.settings, "llm_min_p", 0.05)),
            system_prompt=(self.llm_system_prompt_text.get("1.0", "end").strip() if self.llm_system_prompt_text is not None else self.llm_config.system_prompt),
        )

    def _llm_single_mode_changed(self) -> None:
        if self.llm_single_model_var is not None and self.llm_single_model_var.get() and self.llm_selected_id:
            self.llm_coding_selected_id = self.llm_selected_id
        self._llm_refresh_detail()

    def _llm_use_selected_for_all(self) -> None:
        if self.llm_selected_id:
            self.llm_config.model_id = self.llm_selected_id
            self.llm_config.coding_model_id = self.llm_selected_id
            self.llm_config.research_model_id = self.llm_selected_id
            self.llm_config.telegram_model_id = self.llm_selected_id
            self.llm_config.image_model_id = self.llm_selected_id
            self.llm_config.trading_model_id = self.llm_selected_id
            self.llm_config.model_mode = "single"
            self.llm_coding_selected_id = self.llm_selected_id
            if self.llm_single_model_var is not None:
                self.llm_single_model_var.set(True)
        self._llm_save_settings()

    def _llm_refresh_models(self) -> None:
        if self.llm_panel is None:
            return
        self._emit_activity("Refreshing LM Studio model list via API + disk scan.", "STEP")
        self._llm_set_footer_status("refreshing")
        try:
            if self.llm_base_url_var is not None:
                self.settings.lmstudio_base_url = self.llm_base_url_var.get().strip().rstrip("/") or self.settings.lmstudio_base_url
            self.llm_models = self.llm_manager.discover_models()
            if self.llm_selected_id is None:
                self.llm_selected_id = self.settings.lmstudio_model
            self._llm_render_model_list()
            self._llm_refresh_detail()
            self._llm_set_footer_status(f"{len(self.llm_models)} model(s)")
            self._emit_activity(f"LM Studio refresh complete: {len(self.llm_models)} model(s) found.", "OK")
        except Exception as exc:
            self._llm_set_footer_status("refresh error", error=True)
            self._emit_activity(f"LLM model refresh failed: {type(exc).__name__}: {exc}", "ERR")
            messagebox.showerror("M0N4C0 LLM Models", f"Refresh fout:\n{type(exc).__name__}: {exc}")

    def _llm_render_model_list(self) -> None:
        if self.llm_model_list_inner is None:
            return
        for child in self.llm_model_list_inner.winfo_children():
            child.destroy()
        self.llm_model_rows.clear()
        query = (self.llm_search_var.get() if self.llm_search_var else "").strip().lower()
        filter_type = self.llm_filter_var.get() if self.llm_filter_var else "All Types"
        models = []
        for model in self.llm_models:
            hay = f"{model.id} {model.name} {model.family} {model.model_type} {model.quantization} {model.architecture}".lower()
            if query and query not in hay:
                continue
            if filter_type != "All Types" and filter_type.lower() not in model.model_type.lower():
                continue
            models.append(model)
        if hasattr(self, "llm_found_badge"):
            self.llm_found_badge.configure(text=f"{len(models)} found")
        if not models:
            tk.Label(
                self.llm_model_list_inner,
                text="No models found. Start LM Studio server or set LMSTUDIO_MODELS_DIR to your models folder.",
                bg=P.panel,
                fg=P.muted,
                justify="left",
                wraplength=470,
                font=self.font_small,
                padx=18,
                pady=20,
            ).pack(fill="x")
            return
        for model in models:
            self._llm_model_row(self.llm_model_list_inner, model).pack(fill="x", padx=10, pady=6)

    def _llm_model_row(self, parent: tk.Widget, model: ModelCandidate) -> tk.Frame:
        chat_active = model.id == self.settings.lmstudio_model or model.id == self.llm_selected_id
        code_active = model.id == getattr(self.settings, "lmstudio_coding_model", "") or model.id == self.llm_coding_selected_id
        active = chat_active or code_active
        row = tk.Frame(parent, bg="#151b2a" if active else P.panel_2, padx=12, pady=10, highlightbackground=P.purple if active else P.border, highlightthickness=1, cursor="hand2")
        row.grid_columnconfigure(1, weight=1)
        icon_text = "●" if model.loaded else "◆"
        icon_color = P.green if model.loaded else P.purple
        tk.Label(row, text=icon_text, bg=row["bg"], fg=icon_color, font=("Segoe UI Symbol", 22, "bold"), width=2).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 12))
        tk.Label(row, text=model.name, bg=row["bg"], fg=P.text, font=("Segoe UI", 11, "bold"), anchor="w").grid(row=0, column=1, sticky="ew")
        badges = []
        if chat_active:
            badges.append("CHAT")
        if code_active:
            badges.append("CODE")
        badge_text = ("  •  " + "/".join(badges)) if badges else ""
        sub = f"{model.short_id}  •  {model.model_type}  •  {model.source}{badge_text}"
        if model.quantization:
            sub += f"  •  {model.quantization}"
        tk.Label(row, text=sub, bg=row["bg"], fg=P.muted, font=("Segoe UI", 9), anchor="w").grid(row=1, column=1, sticky="ew", pady=(3, 0))
        tk.Label(row, text=model.size_label, bg=row["bg"], fg=P.muted, font=("Consolas", 9)).grid(row=0, column=2, rowspan=2, sticky="e", padx=(12, 12))
        btn = tk.Button(row, text="Selected" if model.id == self.llm_selected_id else ("Active" if active else "Select"), command=lambda mid=model.id: self._llm_select_model(mid), bg=P.purple_dark if active else P.panel, fg=P.text, activebackground=P.purple, activeforeground=P.text, relief="flat", padx=12, pady=6, cursor="hand2")
        btn.grid(row=0, column=3, rowspan=2, sticky="e")
        for child in row.winfo_children():
            child.bind("<Button-1>", lambda _event, mid=model.id: self._llm_select_model(mid))
        row.bind("<Button-1>", lambda _event, mid=model.id: self._llm_select_model(mid))
        self.llm_model_rows[model.id] = row
        return row

    def _llm_select_model(self, model_id: str) -> None:
        self.llm_selected_id = model_id
        self._llm_render_model_list()
        self._llm_refresh_detail()
        self._emit_activity(f"LLM model selected in GUI: {model_id}. Click Use Selected + Save to apply.", "STEP")

    def _llm_selected_model(self) -> ModelCandidate | None:
        for model in self.llm_models:
            if model.id == self.llm_selected_id:
                return model
        return None

    def _llm_refresh_detail(self) -> None:
        selected = self._llm_selected_model()
        model_id = self.llm_selected_id or self.settings.lmstudio_model
        if hasattr(self, "llm_detail_title"):
            self.llm_detail_title.configure(text=model_id or "No model selected")
        if hasattr(self, "llm_detail_sub"):
            if selected:
                self.llm_detail_sub.configure(text=f"{selected.family} • {selected.model_type} • {selected.source}")
            else:
                self.llm_detail_sub.configure(text="Saved model id. Start/refresh LM Studio to get live metadata.")
        if hasattr(self, "llm_detail_grid"):
            if selected:
                rows = [
                    f"Model ID       {selected.id}",
                    f"Name           {selected.name}",
                    f"Source         {selected.source}",
                    f"Size           {selected.size_label}",
                    f"Type           {selected.model_type}",
                    f"Family         {selected.family}",
                    f"Architecture   {selected.architecture or 'Unknown'}",
                    f"Quantization   {selected.quantization or 'Unknown'}",
                    f"Path           {selected.path or 'API only'}",
                ]
            else:
                rows = [
                    f"Model ID       {model_id}",
                    f"Base URL       {self.llm_config.base_url}",
                    "Status         metadata not loaded",
                ]
            self.llm_detail_grid.configure(text="\n".join(rows))
        if hasattr(self, "llm_active_chip"):
            prompt_len = len(str(getattr(self.settings, "llm_system_prompt", "") or "default"))
            self.llm_active_chip.configure(text=f"Mode\n{getattr(self.settings, 'llm_model_mode', 'split')}\n\nChat Model\n{self.settings.lmstudio_model}\n\nCoding Model\n{getattr(self.settings, 'lmstudio_coding_model', self.settings.lmstudio_model)}\n\nResearch Model\n{getattr(self.settings, 'lmstudio_research_model', self.settings.lmstudio_model)}\n\nRouter\n{'ON' if getattr(self.settings, 'llm_programming_router_enabled', True) else 'OFF'}\n\nSystem Prompt\n{prompt_len} chars")
        if hasattr(self, "llm_footer_active"):
            self.llm_footer_active.configure(text=f"Chat  {self.settings.lmstudio_model}  |  Code  {getattr(self.settings, 'lmstudio_coding_model', self.settings.lmstudio_model)}")
        if hasattr(self, "llm_footer_saved"):
            self.llm_footer_saved.configure(text=f"Last saved  {self.llm_config.updated_at or 'not saved'}")

    def _llm_set_footer_status(self, text: str, error: bool = False) -> None:
        if hasattr(self, "llm_footer_status"):
            self.llm_footer_status.configure(text=f"Status  {text}", fg=P.danger if error else P.muted)

    def _llm_save_settings(self) -> None:
        cfg = self._llm_config_from_controls()
        self.llm_config = cfg
        save_llm_config(self.settings, cfg)
        apply_llm_config(self.settings, self.router, cfg)
        self._llm_refresh_detail()
        self._llm_set_footer_status("saved")
        self._set_status("LLM settings saved", P.success)
        self._emit_activity(f"LLM config saved: chat={cfg.model_id}, code={cfg.coding_model_id}, base_url={cfg.base_url}", "OK")

    def _llm_schedule_live_system_prompt_apply(self, _event: object | None = None) -> None:
        if self.llm_system_prompt_apply_job is not None:
            try:
                self.root.after_cancel(self.llm_system_prompt_apply_job)
            except tk.TclError:
                pass
        self.llm_system_prompt_apply_job = self.root.after(700, self._llm_apply_live_system_prompt)

    def _llm_apply_live_system_prompt(self) -> None:
        self.llm_system_prompt_apply_job = None
        cfg = self._llm_config_from_controls()
        self.llm_config = cfg
        save_llm_config(self.settings, cfg)
        apply_llm_config(self.settings, self.router, cfg)
        self._llm_set_footer_status("system prompt live-applied")
        self._emit_activity("LLM system prompt live-updated without restart.", "OK")
        self._llm_refresh_detail()

    def _llm_open_system_prompt_editor(self) -> None:
        if self.llm_system_prompt_text is None:
            return
        win = tk.Toplevel(self.root)
        win.title("M0N4C0 — Live System Prompt Editor")
        win.geometry("980x720")
        win.configure(bg=P.bg)
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(1, weight=1)
        tk.Label(win, text="LIVE SYSTEM PROMPT", bg=P.bg, fg=P.gold, font=("Segoe UI", 20, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 4))
        tk.Label(win, text="Bewerk ruim en sla live op. De volgende response gebruikt direct deze prompt.", bg=P.bg, fg=P.muted, font=self.font_small).grid(row=0, column=0, sticky="sw", padx=18, pady=(0, 0))
        frame = tk.Frame(win, bg=P.panel, highlightbackground=P.border, highlightthickness=1)
        frame.grid(row=1, column=0, sticky="nsew", padx=18, pady=14)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        editor = tk.Text(frame, bg="#03050b", fg="#d9e0ff", insertbackground=P.text, relief="flat", wrap="word", font=("Consolas", 11), padx=12, pady=12)
        editor.grid(row=0, column=0, sticky="nsew")
        sb = tk.Scrollbar(frame, orient="vertical", command=editor.yview)
        sb.grid(row=0, column=1, sticky="ns")
        editor.configure(yscrollcommand=sb.set)
        editor.insert("1.0", self.llm_system_prompt_text.get("1.0", "end").strip())
        def apply_and_close(close: bool = False) -> None:
            if self.llm_system_prompt_text is not None:
                self.llm_system_prompt_text.delete("1.0", "end")
                self.llm_system_prompt_text.insert("1.0", editor.get("1.0", "end").strip())
                self._llm_apply_live_system_prompt()
            if close:
                win.destroy()
        actions = tk.Frame(win, bg=P.bg)
        actions.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))
        self._llm_button(actions, "Apply Live", lambda: apply_and_close(False), primary=True).pack(side="left", padx=(0, 8))
        self._llm_button(actions, "Apply + Close", lambda: apply_and_close(True), primary=True).pack(side="left", padx=(0, 8))
        self._llm_button(actions, "Close", win.destroy).pack(side="right")
        editor.focus_set()

    def _llm_reset_system_prompt(self) -> None:
        if self.llm_system_prompt_text is None:
            return
        self.llm_system_prompt_text.delete("1.0", "end")
        self.llm_system_prompt_text.insert("1.0", SYSTEM_PROMPT)
        self._llm_save_settings()
        self._emit_activity("LLM system prompt reset to built-in default.", "OK")

    def _llm_use_selected(self) -> None:
        if self.llm_selected_id:
            self.llm_config.model_id = self.llm_selected_id
        self._llm_save_settings()
        ok, msg = self.llm_manager.try_load_model(self.llm_config)
        self._llm_set_footer_status("chat load requested" if ok else "chat saved/manual load")
        self._emit_activity(msg, "OK" if ok else "WARN")
        if not ok:
            messagebox.showwarning("M0N4C0 LLM Models", msg)

    def _llm_use_selected_as_coding(self) -> None:
        if self.llm_selected_id:
            self.llm_coding_selected_id = self.llm_selected_id
        self._llm_save_settings()
        code_cfg = self._llm_config_from_controls()
        code_cfg.model_id = code_cfg.coding_model_id
        ok, msg = self.llm_manager.try_load_model(code_cfg)
        self._llm_set_footer_status("code load requested" if ok else "code saved/manual load")
        self._emit_activity(f"Coding model set: {self.llm_coding_selected_id}. {msg}", "OK" if ok else "WARN")
        if not ok:
            messagebox.showwarning("M0N4C0 Coding Model", msg)

    def _llm_test_connection(self) -> None:
        cfg = self._llm_config_from_controls()
        ok, msg = self.llm_manager.test_connection(cfg, run_chat_test=False)
        if hasattr(self, "llm_connection_status"):
            self.llm_connection_status.configure(text=msg, fg=P.green if ok else P.danger)
        self._llm_set_footer_status("connected" if ok else "connection failed", error=not ok)
        self._emit_activity(f"LM Studio connection test: {msg}", "OK" if ok else "ERR")

    def _llm_test_model(self) -> None:
        cfg = self._llm_config_from_controls()
        ok, msg = self.llm_manager.test_connection(cfg, run_chat_test=True)
        if hasattr(self, "llm_connection_status"):
            self.llm_connection_status.configure(text=msg, fg=P.green if ok else P.danger)
        self._llm_set_footer_status("chat test OK" if ok else "chat test failed", error=not ok)
        self._emit_activity(f"LLM chat test: {msg}", "OK" if ok else "ERR")
        messagebox.showinfo("M0N4C0 LLM Test" if ok else "M0N4C0 LLM Test Failed", msg)

    def _llm_benchmark(self) -> None:
        cfg = self._llm_config_from_controls()
        start = __import__("time").perf_counter()
        ok, msg = self.llm_manager.test_connection(cfg, run_chat_test=True)
        ms = int((__import__("time").perf_counter() - start) * 1000)
        result = f"{msg}\nTotal benchmark time: {ms} ms\nModel: {cfg.model_id}"
        self._emit_activity(f"Benchmark done: {result}", "OK" if ok else "ERR")
        messagebox.showinfo("M0N4C0 Model Benchmark", result)

    def _llm_show_model_info(self) -> None:
        selected = self._llm_selected_model()
        if not selected:
            messagebox.showinfo("M0N4C0 Model Info", f"Model ID: {self.llm_selected_id or self.settings.lmstudio_model}\nNo live metadata found yet.")
            return
        meta = selected.metadata or {}
        lines = [
            f"Name: {selected.name}",
            f"ID: {selected.id}",
            f"Source: {selected.source}",
            f"Type: {selected.model_type}",
            f"Family: {selected.family}",
            f"Size: {selected.size_label}",
            f"Quantization: {selected.quantization or 'Unknown'}",
            f"Architecture: {selected.architecture or 'Unknown'}",
            f"Path: {selected.path or 'API only'}",
            "",
            "Raw metadata:",
            str(meta)[:2500],
        ]
        messagebox.showinfo("M0N4C0 Model Info", "\n".join(lines))

    def _llm_reset_parameters(self) -> None:
        if self.llm_temperature_var: self.llm_temperature_var.set(0.45)
        if self.llm_max_tokens_var: self.llm_max_tokens_var.set(900)
        if self.llm_context_var: self.llm_context_var.set(18000)
        if self.llm_top_p_var: self.llm_top_p_var.set(0.90)
        if self.llm_repeat_penalty_var: self.llm_repeat_penalty_var.set(1.10)
        if self.llm_top_k_var: self.llm_top_k_var.set(40)
        if self.llm_min_p_var: self.llm_min_p_var.set(0.05)
        for key in list(self.llm_param_value_labels.keys()):
            self._llm_param_changed(key)
        self._emit_activity("LLM parameters reset to balanced defaults. Click Save Settings to persist.", "STEP")

    def _llm_reset_defaults(self) -> None:
        if self.llm_base_url_var: self.llm_base_url_var.set("http://localhost:1234/v1")
        self.llm_selected_id = "dolphin-3.0-llama-3.1-8b"
        self.llm_coding_selected_id = "dolphin-3.0-llama-3.1-8b"
        if self.llm_programming_router_var: self.llm_programming_router_var.set(True)
        if self.llm_system_prompt_text is not None:
            self.llm_system_prompt_text.delete("1.0", "end")
            self.llm_system_prompt_text.insert("1.0", SYSTEM_PROMPT)
        self._llm_reset_parameters()
        self._llm_refresh_detail()
        self._llm_render_model_list()

    def _llm_open_lm_studio(self) -> None:
        msg = self.llm_manager.open_lm_studio()
        self._emit_activity(msg, "STEP")

    def _llm_export_config(self) -> None:
        cfg = self._llm_config_from_controls()
        path = filedialog.asksaveasfilename(parent=self.root, title="Export M0N4C0 LLM Config", defaultextension=".json", filetypes=[("JSON files", "*.json"), ("All files", "*.*")], initialfile="m0n4c0_llm_config.json")
        if not path:
            return
        try:
            import json
            from pathlib import Path
            Path(path).write_text(json.dumps(cfg.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
            self._emit_activity(f"LLM config exported: {path}", "OK")
        except Exception as exc:
            messagebox.showerror("M0N4C0 LLM Config", f"Export fout:\n{type(exc).__name__}: {exc}")

    def _llm_import_config(self) -> None:
        path = filedialog.askopenfilename(parent=self.root, title="Import M0N4C0 LLM Config", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            import json
            from pathlib import Path
            imported = LLMRuntimeConfig.from_dict(json.loads(Path(path).read_text(encoding="utf-8")), self.llm_config)
            self.llm_config = imported
            self.llm_selected_id = imported.model_id
            self.llm_coding_selected_id = imported.coding_model_id or imported.model_id
            if self.llm_programming_router_var: self.llm_programming_router_var.set(imported.programming_router_enabled)
            if self.llm_base_url_var: self.llm_base_url_var.set(imported.base_url)
            if self.llm_temperature_var: self.llm_temperature_var.set(imported.temperature)
            if self.llm_max_tokens_var: self.llm_max_tokens_var.set(imported.max_tokens)
            if self.llm_context_var: self.llm_context_var.set(imported.context_chars)
            if self.llm_top_p_var: self.llm_top_p_var.set(imported.top_p)
            if self.llm_repeat_penalty_var: self.llm_repeat_penalty_var.set(imported.repeat_penalty)
            if self.llm_top_k_var: self.llm_top_k_var.set(imported.top_k)
            if self.llm_min_p_var: self.llm_min_p_var.set(imported.min_p)
            if self.llm_system_prompt_text is not None:
                self.llm_system_prompt_text.delete("1.0", "end")
                self.llm_system_prompt_text.insert("1.0", imported.system_prompt or SYSTEM_PROMPT)
            for key in list(self.llm_param_value_labels.keys()):
                self._llm_param_changed(key)
            self._llm_refresh_detail()
            self._llm_render_model_list()
            self._emit_activity(f"LLM config imported: {path}. Click Save Settings to persist.", "OK")
        except Exception as exc:
            messagebox.showerror("M0N4C0 LLM Config", f"Import fout:\n{type(exc).__name__}: {exc}")

    def _llm_view_logs(self) -> None:
        try:
            import os
            os.startfile(self.settings.logs_dir)  # type: ignore[attr-defined]
        except Exception as exc:
            self._emit_activity(f"Could not open logs folder: {type(exc).__name__}: {exc}", "WARN")
            messagebox.showinfo("M0N4C0 Logs", f"Logs folder:\n{self.settings.logs_dir}")


    # ---------- research queue page ----------
    def _show_research(self) -> None:
        self.current_view = "research"
        self.header.grid_remove()
        self.chat_holder.grid_remove()
        self.input_footer.grid_remove()
        self._hide_extra_panels()
        if self.personality_panel is not None:
            self.personality_panel.grid_remove()
        if self.llm_panel is not None:
            self.llm_panel.grid_remove()
        if self.brain_panel is not None:
            self.brain_panel.grid_remove()
        if self.research_panel is None:
            self._build_research_panel()
        assert self.research_panel is not None
        self.research_panel.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self._set_status("Research queue online", P.purple)
        self._refresh_research_jobs()

    def _build_research_panel(self) -> None:
        self.research_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.research_panel.grid_columnconfigure(0, weight=1)
        self.research_panel.grid_rowconfigure(5, weight=1)
        self.research_panel.grid_rowconfigure(7, weight=1)

        top = tk.Frame(self.research_panel, bg=P.bg)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        tk.Label(top, text="⌁", bg=P.bg, fg=P.purple, font=("Segoe UI Symbol", 38, "bold"), width=3).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))
        tk.Label(top, text="RESEARCH AGENTS", bg=P.bg, fg=P.text, font=("Segoe UI", 24, "bold")).grid(row=0, column=1, sticky="w")
        tk.Label(top, text="Bronnen, websites, e-books en onderwerp-research via losse CMD workers.", bg=P.bg, fg=P.muted, font=("Segoe UI", 11)).grid(row=1, column=1, sticky="w", pady=(4, 0))
        self._back_to_chat_button(top).grid(row=0, column=2, rowspan=2, sticky="e")

        form = tk.Frame(self.research_panel, bg=P.panel, padx=14, pady=12, highlightbackground=P.border, highlightthickness=1)
        form.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(5, weight=1)
        self.research_topic_var = tk.StringVar(value="")
        self.research_source_var = tk.StringVar(value="")
        self.research_mode_var = tk.StringVar(value="topic")
        self.research_rounds_var = tk.IntVar(value=max(1, min(6, self.settings.default_learn_rounds)))
        self.research_start_year_var = tk.StringVar(value="")
        self.research_end_year_var = tk.StringVar(value="")
        self.research_priority_var = tk.IntVar(value=6)
        self.research_workers_var = tk.IntVar(value=3)
        self.research_low_llm_var = tk.BooleanVar(value=False)
        self.research_depth_var = tk.IntVar(value=1)
        self.research_max_pages_var = tk.IntVar(value=20)
        self.research_max_files_var = tk.IntVar(value=20)

        tk.Label(form, text="Opdracht / onderwerp", bg=P.panel, fg=P.muted, font=self.font_small).grid(row=0, column=0, sticky="w", padx=(0, 10))
        topic_entry = tk.Entry(form, textvariable=self.research_topic_var, bg=P.panel_2, fg=P.text, insertbackground=P.text, relief="flat", font=self.font_body)
        topic_entry.grid(row=0, column=1, sticky="ew", padx=(0, 10), ipady=8)
        mode_menu = tk.OptionMenu(form, self.research_mode_var, "topic", "broad", "website", "ebooks", "documents", "wikipedia", "news", "competitor", "deep")
        self._style_option_menu(mode_menu)
        mode_menu.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        tk.Button(form, text="Queue Job", command=self._queue_research_job, bg=P.purple_dark, fg=P.text, relief="flat", font=self.font_body_bold, cursor="hand2").grid(row=0, column=3, sticky="e")

        tk.Label(form, text="Bron URL(s)", bg=P.panel, fg=P.muted, font=self.font_small).grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(10, 0))
        source_entry = tk.Entry(form, textvariable=self.research_source_var, bg=P.panel_2, fg=P.text, insertbackground=P.text, relief="flat", font=self.font_body)
        source_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 10), pady=(10, 0), ipady=8)
        tk.Button(form, text="Save Source", command=self._save_research_source_from_gui, bg=P.panel_2, fg=P.text, relief="flat", font=self.font_small, cursor="hand2").grid(row=1, column=3, sticky="e", pady=(10, 0))

        opts = tk.Frame(form, bg=P.panel)
        opts.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        for col in range(14):
            opts.grid_columnconfigure(col, weight=1)
        self._small_labeled_spin(opts, "Rondes", self.research_rounds_var, 1, self.settings.max_learn_rounds, 0)
        self._small_labeled_entry(opts, "Startjaar", self.research_start_year_var, 2)
        self._small_labeled_entry(opts, "Eindjaar", self.research_end_year_var, 4)
        self._small_labeled_spin(opts, "Prioriteit", self.research_priority_var, 0, 10, 6)
        self._small_labeled_spin(opts, "Depth", self.research_depth_var, 0, 4, 8)
        self._small_labeled_spin(opts, "Pages", self.research_max_pages_var, 1, 500, 10)
        self._small_labeled_spin(opts, "Files", self.research_max_files_var, 1, 500, 12)

        workerbar = tk.Frame(self.research_panel, bg=P.bg)
        workerbar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        tk.Button(workerbar, text="Refresh", command=self._refresh_research_jobs, bg=P.panel_2, fg=P.text, relief="flat", font=self.font_small, cursor="hand2").pack(side="left", padx=(0, 8))
        tk.Button(workerbar, text="Start Worker CMD", command=self._start_research_worker_process, bg=P.purple_dark, fg=P.text, relief="flat", font=self.font_small, cursor="hand2").pack(side="left", padx=(0, 8))
        tk.Button(workerbar, text="Retry Failed", command=self._retry_failed_research_jobs, bg=P.panel_2, fg=P.text, relief="flat", font=self.font_small, cursor="hand2").pack(side="left", padx=(0, 8))
        tk.Button(workerbar, text="Cancel Latest", command=self._cancel_latest_research_job, bg=P.panel_2, fg=P.danger, relief="flat", font=self.font_small, cursor="hand2").pack(side="left", padx=(0, 8))
        tk.Label(workerbar, text="Workers", bg=P.bg, fg=P.muted, font=self.font_small).pack(side="left", padx=(12, 4))
        tk.Spinbox(workerbar, from_=1, to=8, textvariable=self.research_workers_var, width=4, bg=P.panel_2, fg=P.text, insertbackground=P.text, relief="flat").pack(side="left")
        tk.Checkbutton(workerbar, text="Low LLM", variable=self.research_low_llm_var, bg=P.bg, fg=P.muted, selectcolor=P.panel_2, activebackground=P.bg, activeforeground=P.text, font=self.font_small).pack(side="left", padx=(12, 0))

        src_frame = tk.Frame(self.research_panel, bg=P.panel, padx=10, pady=8, highlightbackground=P.border, highlightthickness=1)
        src_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        src_frame.grid_columnconfigure(0, weight=1)
        src_head = tk.Frame(src_frame, bg=P.panel)
        src_head.grid(row=0, column=0, sticky="ew")
        src_head.grid_columnconfigure(0, weight=1)
        tk.Label(src_head, text="Saved Sources", bg=P.panel, fg=P.gold, font=self.font_small).grid(row=0, column=0, sticky="w")
        self.research_source_delete_var = tk.StringVar(value="")
        tk.Label(src_head, text="ID", bg=P.panel, fg=P.muted, font=self.font_small).grid(row=0, column=1, sticky="e", padx=(8, 4))
        tk.Entry(src_head, textvariable=self.research_source_delete_var, bg=P.panel_2, fg=P.text, insertbackground=P.text, relief="flat", width=7).grid(row=0, column=2, sticky="e")
        tk.Button(src_head, text="Remove Source", command=self._delete_research_source_from_gui, bg=P.panel_2, fg=P.danger, relief="flat", font=self.font_small, cursor="hand2").grid(row=0, column=3, sticky="e", padx=(8, 0))
        self.research_source_list_text = tk.Text(src_frame, height=4, bg=P.panel, fg=P.muted, relief="flat", font=("Consolas", 9), wrap="none")
        self.research_source_list_text.grid(row=1, column=0, sticky="ew")
        self.research_source_list_text.configure(state="disabled")

        tk.Label(self.research_panel, text="Jobs", bg=P.bg, fg=P.gold, font=self.font_body_bold).grid(row=4, column=0, sticky="nw")
        jobs_frame = tk.Frame(self.research_panel, bg=P.panel, highlightbackground=P.border, highlightthickness=1)
        jobs_frame.grid(row=5, column=0, sticky="nsew", pady=(4, 12))
        jobs_frame.grid_columnconfigure(0, weight=1)
        jobs_frame.grid_rowconfigure(0, weight=1)
        self.research_jobs_text = tk.Text(jobs_frame, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", wrap="none", font=("Consolas", 10), padx=12, pady=10)
        self.research_jobs_text.grid(row=0, column=0, sticky="nsew")
        jobs_scroll = tk.Scrollbar(jobs_frame, command=self.research_jobs_text.yview)
        jobs_scroll.grid(row=0, column=1, sticky="ns")
        self.research_jobs_text.configure(yscrollcommand=jobs_scroll.set, state="disabled")

        tk.Label(self.research_panel, text="Live Events", bg=P.bg, fg=P.gold, font=self.font_body_bold).grid(row=6, column=0, sticky="nw")
        events_frame = tk.Frame(self.research_panel, bg="#050812", highlightbackground=P.border, highlightthickness=1)
        events_frame.grid(row=7, column=0, sticky="nsew", pady=(4, 0))
        events_frame.grid_columnconfigure(0, weight=1)
        events_frame.grid_rowconfigure(0, weight=1)
        self.research_events_text = tk.Text(events_frame, bg="#03050b", fg="#cfd7ff", insertbackground=P.text, relief="flat", wrap="word", font=("Consolas", 9), padx=12, pady=10)
        self.research_events_text.grid(row=0, column=0, sticky="nsew")
        events_scroll = tk.Scrollbar(events_frame, command=self.research_events_text.yview)
        events_scroll.grid(row=0, column=1, sticky="ns")
        self.research_events_text.configure(yscrollcommand=events_scroll.set, state="disabled")

    def _small_labeled_entry(self, parent: tk.Frame, label: str, var: tk.StringVar, col: int) -> None:
        tk.Label(parent, text=label, bg=P.panel, fg=P.muted, font=self.font_small).grid(row=0, column=col, sticky="w", padx=(0, 6))
        tk.Entry(parent, textvariable=var, bg=P.panel_2, fg=P.text, insertbackground=P.text, relief="flat", width=8).grid(row=0, column=col + 1, sticky="ew", padx=(0, 12), ipady=5)

    def _small_labeled_spin(self, parent: tk.Frame, label: str, var: tk.IntVar, from_: int, to: int, col: int) -> None:
        tk.Label(parent, text=label, bg=P.panel, fg=P.muted, font=self.font_small).grid(row=0, column=col, sticky="w", padx=(0, 6))
        tk.Spinbox(parent, from_=from_, to=to, textvariable=var, bg=P.panel_2, fg=P.text, insertbackground=P.text, relief="flat", width=6).grid(row=0, column=col + 1, sticky="ew", padx=(0, 12), ipady=4)

    def _queue_research_job(self) -> None:
        topic = (self.research_topic_var.get() if self.research_topic_var else "").strip()
        source_raw = (self.research_source_var.get() if self.research_source_var else "").strip()
        source_urls = [u.strip() for u in re.split(r"[\n,; ]+", source_raw) if u.strip().startswith(("http://", "https://")) or "." in u.strip()]
        if not topic and source_urls:
            topic = source_urls[0]
        if not topic:
            messagebox.showinfo("M0N4C0 Research", "Vul eerst een onderwerp of bron-URL in.")
            return
        def parse_year(var: tk.StringVar | None) -> int | None:
            value = (var.get() if var else "").strip()
            if not value:
                return None
            try:
                return int(value)
            except Exception:
                return None
        start_year = parse_year(self.research_start_year_var)
        end_year = parse_year(self.research_end_year_var)
        mode = self.research_mode_var.get() if self.research_mode_var else "topic"
        if start_year or end_year:
            mode = "broad" if mode == "topic" else mode
        if source_urls and mode == "topic":
            mode = "website"
        rounds = int(self.research_rounds_var.get() if self.research_rounds_var else self.settings.default_learn_rounds)
        priority = int(self.research_priority_var.get() if self.research_priority_var else 6)
        max_depth = int(self.research_depth_var.get() if self.research_depth_var else 1)
        max_pages = int(self.research_max_pages_var.get() if self.research_max_pages_var else 20)
        max_files = int(self.research_max_files_var.get() if self.research_max_files_var else 20)
        job_id = self.router.db.enqueue_learning_job(
            topic,
            rounds,
            mode=mode,
            priority=priority,
            agent="gui_research",
            chat_id=self.ctx.chat_id,
            user_key=self.ctx.user_key,
            source="gui_research_tab",
            start_year=start_year,
            end_year=end_year,
            source_urls=source_urls,
            worker_profile="gui_selected",
            max_depth=max_depth,
            max_pages=max_pages,
            max_files=max_files,
            metadata={"source_urls": source_urls, "created_from": "research_gui", "max_depth": max_depth, "max_pages": max_pages, "max_files": max_files},
        )
        self._emit_activity(f"Research job queued from GUI: #{job_id} {topic} mode={mode}", "OK")
        self._refresh_research_jobs()

    def _refresh_research_jobs(self) -> None:
        rows = self.router.db.list_learning_jobs(limit=60)
        lines = []
        for r in rows:
            try:
                progress = json.loads(r["progress_json"] or "{}") if "progress_json" in r.keys() else {}
            except Exception:
                progress = {}
            phase = progress.get("phase", "-")
            pct = progress.get("percent", 0)
            worker = r["worker_id"] if "worker_id" in r.keys() else "-"
            mode = r["mode"] if "mode" in r.keys() else "topic"
            urls = ""
            try:
                url_list = json.loads(r["source_urls_json"] or "[]") if "source_urls_json" in r.keys() else []
                if url_list:
                    urls = f" | urls={len(url_list)}"
            except Exception:
                pass
            years = ""
            if "start_year" in r.keys() and (r["start_year"] or r["end_year"]):
                years = f" years={r['start_year']}-{r['end_year']}"
            lines.append(f"#{r['id']:>4} | {str(r['status'])[:10]:<10} | {pct:>3}% | {str(phase)[:18]:<18} | {r['rounds_done']}/{r['rounds_requested']} | prio={r['priority'] if 'priority' in r.keys() else '-'} | {str(mode)[:10]:<10} | {str(r['topic'])[:48]}{years}{urls} | {worker or '-'}")
        if not lines:
            lines = ["Nog geen research jobs. Queue hierboven een onderwerp/website/e-book bron of typ in chat: leer alles over <onderwerp>."]
        self._set_text_widget(self.research_jobs_text, "\n".join(lines))

        events = self.router.db.list_learning_events(limit=120)
        event_lines = []
        for e in reversed(events):
            event_lines.append(f"[{e['created_at']}] {str(e['level'])[:5]:<5} job={e['job_id'] or '-'} worker={e['worker_id'] or '-'} :: {e['message']}")
        self._set_text_widget(self.research_events_text, "\n".join(event_lines[-120:]) if event_lines else "Nog geen worker events.")

        try:
            sources = self.router.db.list_research_sources(limit=20)
            source_lines = [f"#{r['id']} {r['source_kind']} {'ON' if r['enabled'] else 'OFF'} | {r['name']} | {r['url']}" for r in sources[:20]]
            self._set_text_widget(self.research_source_list_text, "\n".join(source_lines) if source_lines else "Geen opgeslagen research sources.")
        except Exception as exc:
            self._set_text_widget(self.research_source_list_text, f"Sources laden mislukt: {type(exc).__name__}: {exc}")

    def _start_research_worker_process(self) -> None:
        if self.research_worker_process is not None and self.research_worker_process.poll() is None:
            messagebox.showinfo("M0N4C0 Research", "Er draait al een worker process vanuit deze GUI.")
            return
        app_root = self.settings.root
        agents = int(self.research_workers_var.get() if self.research_workers_var else 3)
        cmd = [sys.executable, str(app_root / "learning_worker.py"), "--agents", str(max(1, min(8, agents)))]
        if self.research_low_llm_var is not None and self.research_low_llm_var.get():
            cmd.append("--low-llm")
        try:
            if os.name == "nt":
                self.research_worker_process = subprocess.Popen(cmd, cwd=str(app_root), creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                self.research_worker_process = subprocess.Popen(cmd, cwd=str(app_root))
            self._emit_activity(f"External worker CMD started: {' '.join(cmd)}", "OK")
            messagebox.showinfo("M0N4C0 Research", f"Worker gestart met {agents} agent(s) in een apart process/CMD.")
        except Exception as exc:
            self._emit_activity(f"Could not start worker: {type(exc).__name__}: {exc}", "ERR")
            messagebox.showerror("M0N4C0 Research", f"Worker starten mislukt:\n{type(exc).__name__}: {exc}")

    def _save_research_source_from_gui(self) -> None:
        raw = (self.research_source_var.get() if self.research_source_var else "").strip()
        if not raw:
            messagebox.showinfo("M0N4C0 Research", "Vul eerst een URL in.")
            return
        urls = [u.strip() for u in re.split(r"[\n,; ]+", raw) if u.strip()]
        saved = 0
        for url in urls:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            kind = self.research_mode_var.get() if self.research_mode_var else "website"
            if kind not in {"website", "ebooks", "documents", "wikipedia", "news", "competitor", "deep"}:
                kind = "website"
            self.router.db.upsert_research_source(name=url, url=url, source_kind=kind, enabled=True)
            saved += 1
        self._emit_activity(f"Saved {saved} research source(s).", "OK")
        self._refresh_research_jobs()

    def _delete_research_source_from_gui(self) -> None:
        raw = (self.research_source_delete_var.get() if self.research_source_delete_var else "").strip()
        if not raw:
            messagebox.showinfo("M0N4C0 Research", "Vul het source ID in dat je wilt verwijderen. Je ziet het ID links in de Saved Sources lijst.")
            return
        try:
            source_id = int(raw.lstrip("#"))
        except Exception:
            messagebox.showerror("M0N4C0 Research", "Source ID moet een nummer zijn, bijvoorbeeld 12.")
            return
        if not messagebox.askyesno("M0N4C0 Research", f"Saved source #{source_id} verwijderen?"):
            return
        try:
            ok = self.router.db.delete_research_source(source_id)
            if ok:
                self._emit_activity(f"Research source #{source_id} removed.", "OK")
                if self.research_source_delete_var:
                    self.research_source_delete_var.set("")
            else:
                messagebox.showinfo("M0N4C0 Research", f"Geen saved source gevonden met ID #{source_id}.")
            self._refresh_research_jobs()
        except Exception as exc:
            messagebox.showerror("M0N4C0 Research", f"Verwijderen mislukt:\n{type(exc).__name__}: {exc}")

    def _retry_failed_research_jobs(self) -> None:
        retried = 0
        with self.router.db.connect() as conn:
            rows = conn.execute("SELECT id FROM learning_jobs WHERE status='failed' ORDER BY id DESC LIMIT 10").fetchall()
            now = __import__('monaco_ai.utils', fromlist=['utc_now']).utc_now()
            for row in rows:
                conn.execute("UPDATE learning_jobs SET status='queued', error=NULL, cancel_requested=0, updated_at=?, progress_json=? WHERE id=?", (now, json.dumps({"phase":"retry_queued","percent":0}), int(row['id'])))
                retried += 1
        self._emit_activity(f"Retry queued for {retried} failed job(s).", "OK")
        self._refresh_research_jobs()

    def _cancel_latest_research_job(self) -> None:
        rows = self.router.db.list_learning_jobs(limit=20)
        target = None
        for r in rows:
            if str(r["status"]) in {"running", "queued", "pending"}:
                target = int(r["id"])
                break
        if target is None:
            messagebox.showinfo("M0N4C0 Research", "Geen actieve/queued job gevonden.")
            return
        self.router.db.request_cancel_learning_job(target)
        self._emit_activity(f"Cancel requested for research job #{target}", "WARN")
        self._refresh_research_jobs()




    # ---------- local database manager ----------
    def _show_database_manager(self) -> None:
        self.current_view = "database"
        self.header.grid_remove()
        self.chat_holder.grid_remove()
        self.input_footer.grid_remove()
        self._hide_extra_panels()
        if self.database_panel is None:
            self._build_database_panel()
        assert self.database_panel is not None
        self.database_panel.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self._set_status("Database Manager online", P.purple)
        self._db_refresh_tables()

    def _build_database_panel(self) -> None:
        self.database_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.database_panel.grid_columnconfigure(0, weight=1)
        self.database_panel.grid_rowconfigure(2, weight=1)

        top = tk.Frame(self.database_panel, bg=P.bg)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        tk.Label(top, text="▣", bg=P.bg, fg=P.purple, font=("Segoe UI Symbol", 38, "bold"), width=3).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))
        tk.Label(top, text="LOCAL DATABASE", bg=P.bg, fg=P.text, font=("Segoe UI", 24, "bold")).grid(row=0, column=1, sticky="w")
        tk.Label(top, text="Browse, search, export and safely inspect your SQLite memory without deleting data.", bg=P.bg, fg=P.muted, font=("Segoe UI", 11)).grid(row=1, column=1, sticky="w", pady=(4, 0))
        actions = tk.Frame(top, bg=P.bg)
        actions.grid(row=0, column=2, rowspan=2, sticky="e")
        self._back_to_chat_button(actions).pack(side="left", padx=(0, 10))
        self._llm_button(actions, "⟳ Refresh", self._db_refresh_tables).pack(side="left", padx=(0, 10))
        self._llm_button(actions, "✓ Integrity", self._db_integrity_check).pack(side="left", padx=(0, 10))
        self._llm_button(actions, "⛨ Backup DB", self._db_backup_database, primary=True).pack(side="left", padx=(0, 10))
        self._llm_button(actions, "⚠ Lege Brein", self._wipe_brain_from_gui).pack(side="left")

        info = tk.Frame(self.database_panel, bg=P.panel, padx=14, pady=10, highlightbackground=P.border, highlightthickness=1)
        info.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        info.grid_columnconfigure(1, weight=1)
        tk.Label(info, text="Database path", bg=P.panel, fg=P.muted, font=self.font_small).grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.db_path_label = tk.Label(info, text=str(self.settings.db_path), bg=P.panel, fg=P.text, font=("Consolas", 9), anchor="w")
        self.db_path_label.grid(row=0, column=1, sticky="ew")
        self.db_size_label = tk.Label(info, text="", bg=P.panel, fg=P.gold, font=self.font_small)
        self.db_size_label.grid(row=0, column=2, sticky="e", padx=(18, 0))

        body = tk.Frame(self.database_panel, bg=P.bg)
        body.grid(row=2, column=0, sticky="nsew", pady=(16, 0))
        body.grid_columnconfigure(0, minsize=330, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=P.panel_2, padx=16, pady=16, highlightbackground=P.border, highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)
        tk.Label(left, text="TABLES / VIEWS", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        self.db_stats_label = tk.Label(left, text="Loading…", bg=P.panel_2, fg=P.muted, justify="left", anchor="w", font=self.font_small)
        self.db_stats_label.grid(row=1, column=0, sticky="ew", pady=(7, 12))
        list_shell = tk.Frame(left, bg=P.panel, highlightbackground=P.border, highlightthickness=1)
        list_shell.grid(row=2, column=0, sticky="nsew")
        list_shell.grid_columnconfigure(0, weight=1)
        list_shell.grid_rowconfigure(0, weight=1)
        self.db_table_list = tk.Listbox(
            list_shell, bg=P.panel, fg=P.text, selectbackground=P.purple_dark, selectforeground=P.text,
            relief="flat", highlightthickness=0, activestyle="none", font=("Consolas", 10)
        )
        self.db_table_list.grid(row=0, column=0, sticky="nsew")
        self.db_table_list.bind("<<ListboxSelect>>", self._db_on_table_select)
        tk.Scrollbar(list_shell, orient="vertical", command=self.db_table_list.yview).grid(row=0, column=1, sticky="ns")
        self.db_table_list.configure(yscrollcommand=lambda *args: None)
        left_actions = tk.Frame(left, bg=P.panel_2)
        left_actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        left_actions.grid_columnconfigure(0, weight=1)
        left_actions.grid_columnconfigure(1, weight=1)
        self._llm_button(left_actions, "Open Folder", self._db_open_folder).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self._llm_button(left_actions, "Rebuild FTS", self._db_rebuild_fts).grid(row=0, column=1, sticky="ew", padx=(5, 0))

        right = tk.Frame(body, bg=P.bg)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=2)
        right.grid_rowconfigure(2, weight=1)

        table_card = tk.Frame(right, bg=P.panel_2, padx=16, pady=14, highlightbackground=P.border, highlightthickness=1)
        table_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        table_card.grid_columnconfigure(1, weight=1)
        self.db_selected_label = tk.Label(table_card, text="Select a table", bg=P.panel_2, fg=P.text, font=("Segoe UI", 14, "bold"), anchor="w")
        self.db_selected_label.grid(row=0, column=0, columnspan=5, sticky="ew", pady=(0, 10))
        tk.Label(table_card, text="Search", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.db_search_var = tk.StringVar(value="")
        tk.Entry(table_card, textvariable=self.db_search_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", highlightbackground=P.border, highlightthickness=1).grid(row=1, column=1, sticky="ew", ipady=7, padx=(0, 8))
        self.db_limit_var = tk.IntVar(value=50)
        tk.OptionMenu(table_card, self.db_limit_var, 25, 50, 100, 200).grid(row=1, column=2, sticky="e", padx=(0, 8))
        self._llm_button(table_card, "Load", self._db_load_table_page, primary=True).grid(row=1, column=3, sticky="e", padx=(0, 8))
        self._llm_button(table_card, "Export", self._db_export_current_table).grid(row=1, column=4, sticky="e")
        page = tk.Frame(table_card, bg=P.panel_2)
        page.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(10, 0))
        self._llm_button(page, "‹ Previous", self._db_prev_page).pack(side="left", padx=(0, 8))
        self._llm_button(page, "Next ›", self._db_next_page).pack(side="left", padx=(0, 16))
        self.db_page_label = tk.Label(page, text="Offset 0", bg=P.panel_2, fg=P.muted, font=self.font_small)
        self.db_page_label.pack(side="left")

        preview_card = tk.Frame(right, bg=P.panel_2, padx=16, pady=14, highlightbackground=P.border, highlightthickness=1)
        preview_card.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        preview_card.grid_columnconfigure(0, weight=1)
        preview_card.grid_rowconfigure(1, weight=1)
        tk.Label(preview_card, text="DATA PREVIEW", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.db_preview_text = tk.Text(preview_card, bg="#03050b", fg="#d9e0ff", insertbackground=P.text, relief="flat", wrap="none", font=("Consolas", 9), padx=10, pady=8)
        self.db_preview_text.grid(row=1, column=0, sticky="nsew")
        self.db_preview_text.configure(state="disabled")

        bottom = tk.Frame(right, bg=P.bg)
        bottom.grid(row=2, column=0, sticky="nsew")
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)
        bottom.grid_rowconfigure(0, weight=1)

        schema_card = tk.Frame(bottom, bg=P.panel_2, padx=16, pady=14, highlightbackground=P.border, highlightthickness=1)
        schema_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        schema_card.grid_columnconfigure(0, weight=1)
        schema_card.grid_rowconfigure(1, weight=1)
        tk.Label(schema_card, text="SCHEMA / INDEXES", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.db_schema_text = tk.Text(schema_card, bg="#03050b", fg="#d9e0ff", relief="flat", wrap="word", font=("Consolas", 9), padx=10, pady=8)
        self.db_schema_text.grid(row=1, column=0, sticky="nsew")
        self.db_schema_text.configure(state="disabled")

        sql_card = tk.Frame(bottom, bg=P.panel_2, padx=16, pady=14, highlightbackground=P.border, highlightthickness=1)
        sql_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        sql_card.grid_columnconfigure(0, weight=1)
        sql_card.grid_rowconfigure(2, weight=1)
        tk.Label(sql_card, text="SAFE SQL CONSOLE", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.db_sql_input = tk.Text(sql_card, height=4, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", wrap="word", font=("Consolas", 9), padx=10, pady=8)
        self.db_sql_input.grid(row=1, column=0, sticky="ew")
        self.db_sql_input.insert("1.0", "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name;")
        self.db_sql_output = tk.Text(sql_card, bg="#03050b", fg="#d9e0ff", relief="flat", wrap="none", font=("Consolas", 9), padx=10, pady=8)
        self.db_sql_output.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        self.db_sql_output.configure(state="disabled")
        sql_actions = tk.Frame(sql_card, bg=P.panel_2)
        sql_actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.db_write_enabled_var = tk.BooleanVar(value=False)
        tk.Checkbutton(sql_actions, text="Allow non-destructive writes", variable=self.db_write_enabled_var, bg=P.panel_2, fg=P.text, activebackground=P.panel_2, activeforeground=P.text, selectcolor=P.purple_dark, relief="flat", font=self.font_small).pack(side="left")
        self._llm_button(sql_actions, "Execute", self._db_execute_sql, primary=True).pack(side="right")

    def _db_quote(self, name: str) -> str:
        return '"' + str(name).replace('"', '""') + '"'

    def _db_readonly_connect(self) -> sqlite3.Connection:
        uri = f"file:{self.settings.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _db_set_text(self, widget: tk.Text | None, text: str) -> None:
        if widget is None:
            return
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _db_format_rows(self, rows: list[sqlite3.Row], columns: list[str], max_cell: int = 64) -> str:
        if not columns:
            return "No columns."
        if not rows:
            return "No rows found."
        matrix = []
        for row in rows:
            vals = []
            for col in columns:
                val = row[col]
                if val is None:
                    text = "NULL"
                else:
                    text = str(val).replace("\n", "\\n")
                if len(text) > max_cell:
                    text = text[: max_cell - 1] + "…"
                vals.append(text)
            matrix.append(vals)
        widths = [min(max(len(str(col)), *(len(r[i]) for r in matrix)), max_cell) for i, col in enumerate(columns)]
        sep = "-+-".join("-" * w for w in widths)
        header = " | ".join(str(col)[:widths[i]].ljust(widths[i]) for i, col in enumerate(columns))
        body = [" | ".join(row[i][:widths[i]].ljust(widths[i]) for i in range(len(columns))) for row in matrix]
        return "\n".join([header, sep, *body])

    def _db_refresh_tables(self) -> None:
        try:
            size = self.settings.db_path.stat().st_size if self.settings.db_path.exists() else 0
            if hasattr(self, "db_size_label"):
                self.db_size_label.configure(text=f"{size / (1024*1024):.1f} MB")
            with self._db_readonly_connect() as conn:
                rows = conn.execute("SELECT name,type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
                stats = []
                names = []
                for row in rows:
                    name = str(row["name"])
                    names.append(name)
                    # Exact COUNT(*) on a multi-GB SQLite DB can freeze the GUI.
                    # Counts are now loaded lazily when opening a specific table.
                    stats.append((name, row["type"], "lazy"))
            self.db_table_names = names
            if self.db_table_list is not None:
                self.db_table_list.delete(0, "end")
                for name, typ, count in stats:
                    self.db_table_list.insert("end", f"{typ[:1].upper()}  {name}  ({count})")
            if self.db_stats_label is not None:
                self.db_stats_label.configure(text=f"{len(stats)} objects found\nFast mode: table counts load lazily. Read-only by default.")
            if stats and not self.db_current_table:
                self.db_current_table = stats[0][0]
                if self.db_table_list is not None:
                    self.db_table_list.selection_set(0)
                self.db_offset = 0
                self._db_load_table_page()
            self._emit_activity(f"Database manager refreshed: {len(stats)} objects.", "OK")
        except Exception as exc:
            self._db_set_text(self.db_preview_text, f"Database refresh error: {type(exc).__name__}: {exc}")
            self._emit_activity(f"Database refresh error: {type(exc).__name__}: {exc}", "ERR")

    def _db_on_table_select(self, _event: object | None = None) -> None:
        if self.db_table_list is None:
            return
        sel = self.db_table_list.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.db_table_names):
            return
        self.db_current_table = self.db_table_names[idx]
        self.db_offset = 0
        self._db_load_table_page()

    def _db_table_columns(self, conn: sqlite3.Connection, table: str) -> list[str]:
        return [str(r["name"]) for r in conn.execute(f"PRAGMA table_info({self._db_quote(table)})").fetchall()]

    def _db_load_table_page(self) -> None:
        table = self.db_current_table
        if not table:
            return
        try:
            limit = int(self.db_limit_var.get() if self.db_limit_var else 50)
            limit = max(1, min(500, limit))
            search = (self.db_search_var.get() if self.db_search_var else "").strip()
            with self._db_readonly_connect() as conn:
                columns = self._db_table_columns(conn, table)
                where = ""
                params: list[object] = []
                if search and columns:
                    where = " WHERE " + " OR ".join([f"CAST({self._db_quote(c)} AS TEXT) LIKE ?" for c in columns])
                    params.extend([f"%{search}%"] * len(columns))
                sql = f"SELECT * FROM {self._db_quote(table)}{where} LIMIT ? OFFSET ?"
                rows = conn.execute(sql, [*params, limit, self.db_offset]).fetchall()
                if search:
                    count_sql = f"SELECT COUNT(*) c FROM {self._db_quote(table)}{where}"
                    total_label = str(conn.execute(count_sql, params).fetchone()["c"])
                else:
                    # Keep huge tables snappy: do not force COUNT(*) on every page load.
                    total_label = "lazy"
                schema_rows = conn.execute(f"PRAGMA table_info({self._db_quote(table)})").fetchall()
                index_rows = conn.execute(f"PRAGMA index_list({self._db_quote(table)})").fetchall()
            if hasattr(self, "db_selected_label"):
                self.db_selected_label.configure(text=f"{table}  •  {total_label} rows")
            if hasattr(self, "db_page_label"):
                self.db_page_label.configure(text=f"Offset {self.db_offset} / {total_label}")
            self._db_set_text(self.db_preview_text, self._db_format_rows(rows, columns))
            schema_lines = ["Columns:"]
            for r in schema_rows:
                schema_lines.append(f"- {r['name']}  {r['type'] or 'ANY'}  notnull={r['notnull']}  pk={r['pk']}  default={r['dflt_value']}")
            schema_lines.append("\nIndexes:")
            for r in index_rows:
                schema_lines.append(f"- {r['name']}  unique={r['unique']}  origin={r['origin']}")
            self._db_set_text(self.db_schema_text, "\n".join(schema_lines))
            self._emit_activity(f"Loaded database table {table}: {len(rows)} row(s) shown.", "OK")
        except Exception as exc:
            self._db_set_text(self.db_preview_text, f"Load error: {type(exc).__name__}: {exc}")
            self._emit_activity(f"Database table load error: {type(exc).__name__}: {exc}", "ERR")

    def _db_next_page(self) -> None:
        limit = int(self.db_limit_var.get() if self.db_limit_var else 50)
        self.db_offset += max(1, limit)
        self._db_load_table_page()

    def _db_prev_page(self) -> None:
        limit = int(self.db_limit_var.get() if self.db_limit_var else 50)
        self.db_offset = max(0, self.db_offset - max(1, limit))
        self._db_load_table_page()

    def _db_execute_sql(self) -> None:
        sql = self.db_sql_input.get("1.0", "end").strip() if self.db_sql_input else ""
        if not sql:
            return
        lowered = re.sub(r"\s+", " ", sql.lower()).strip()
        destructive = re.search(r"\b(drop|delete|truncate|detach|attach)\b", lowered)
        write_enabled = bool(self.db_write_enabled_var.get() if self.db_write_enabled_var else False)
        read_only = lowered.startswith(("select", "with", "pragma", "explain"))
        if destructive:
            self._db_set_text(self.db_sql_output, "Blocked: destructive SQL is disabled in this manager to protect your database.")
            return
        if not read_only and not write_enabled:
            self._db_set_text(self.db_sql_output, "Blocked: read-only mode is active. Toggle 'Allow non-destructive writes' for INSERT/UPDATE/CREATE/ALTER.")
            return
        try:
            if read_only:
                with self._db_readonly_connect() as conn:
                    cur = conn.execute(sql)
                    rows = cur.fetchmany(200)
                    cols = [d[0] for d in (cur.description or [])]
                self._db_set_text(self.db_sql_output, self._db_format_rows(rows, cols) if rows else "Query OK. No rows returned.")
            else:
                backup_msg = self._db_backup_database(silent=True)
                with self.router.db.connect() as conn:
                    cur = conn.executescript(sql)
                self._db_set_text(self.db_sql_output, f"Write query executed. {backup_msg}\nRefresh tables to see changes.")
                self._db_refresh_tables()
            self._emit_activity("Database SQL console executed query.", "OK")
        except Exception as exc:
            self._db_set_text(self.db_sql_output, f"SQL error: {type(exc).__name__}: {exc}")
            self._emit_activity(f"Database SQL error: {type(exc).__name__}: {exc}", "ERR")

    def _db_integrity_check(self) -> None:
        try:
            with self._db_readonly_connect() as conn:
                quick = conn.execute("PRAGMA quick_check").fetchone()[0]
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            msg = f"quick_check: {quick}\nintegrity_check: {integrity}"
            self._db_set_text(self.db_sql_output, msg)
            messagebox.showinfo("M0N4C0 Database Integrity", msg)
        except Exception as exc:
            messagebox.showerror("M0N4C0 Database Integrity", f"Check fout:\n{type(exc).__name__}: {exc}")

    def _db_backup_database(self, silent: bool = False) -> str:
        try:
            src = self.settings.db_path
            stamp = time.strftime("%Y%m%d_%H%M%S")
            backup_dir = self.settings.data_dir / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            dst = backup_dir / f"{src.stem}_{stamp}{src.suffix}"
            shutil.copy2(src, dst)
            msg = f"Backup created: {dst}"
            self._emit_activity(msg, "OK")
            if not silent:
                messagebox.showinfo("M0N4C0 Database Backup", msg)
            return msg
        except Exception as exc:
            msg = f"Backup failed: {type(exc).__name__}: {exc}"
            self._emit_activity(msg, "ERR")
            if not silent:
                messagebox.showerror("M0N4C0 Database Backup", msg)
            return msg

    def _db_export_current_table(self) -> None:
        table = self.db_current_table
        if not table:
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="Export SQLite table", defaultextension=".csv", filetypes=[("CSV files", "*.csv"), ("JSON files", "*.json"), ("All files", "*.*")], initialfile=f"{table}.csv")
        if not path:
            return
        try:
            with self._db_readonly_connect() as conn:
                rows = conn.execute(f"SELECT * FROM {self._db_quote(table)}").fetchall()
                columns = self._db_table_columns(conn, table)
            if path.lower().endswith(".json"):
                Path(path).write_text(json.dumps([{c: row[c] for c in columns} for row in rows], ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(columns)
                    for row in rows:
                        writer.writerow([row[c] for c in columns])
            self._emit_activity(f"Exported table {table} to {path}", "OK")
            messagebox.showinfo("M0N4C0 Database Export", f"Export klaar:\n{path}")
        except Exception as exc:
            messagebox.showerror("M0N4C0 Database Export", f"Export fout:\n{type(exc).__name__}: {exc}")

    def _db_open_folder(self) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(self.settings.db_path.parent)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(self.settings.db_path.parent)])
            else:
                subprocess.Popen(["xdg-open", str(self.settings.db_path.parent)])
        except Exception as exc:
            messagebox.showinfo("M0N4C0 Database Folder", f"Folder:\n{self.settings.db_path.parent}\n\nOpen fout: {exc}")

    def _db_rebuild_fts(self) -> None:
        try:
            backup_msg = self._db_backup_database(silent=True)
            with self.router.db.connect() as conn:
                conn.execute("INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts) VALUES('rebuild')")
            self._emit_activity("FTS index rebuilt for knowledge_chunks.", "OK")
            messagebox.showinfo("M0N4C0 Database", f"FTS rebuilt.\n{backup_msg}")
        except Exception as exc:
            messagebox.showerror("M0N4C0 Database", f"FTS rebuild fout:\n{type(exc).__name__}: {exc}")

    # ---------- telegram manager ----------
    def _show_telegram_manager(self) -> None:
        self.current_view = "telegram"
        self.header.grid_remove()
        self.chat_holder.grid_remove()
        self.input_footer.grid_remove()
        self._hide_extra_panels()
        if self.telegram_panel is None:
            self._build_telegram_panel()
        assert self.telegram_panel is not None
        self.telegram_panel.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self._telegram_sync_controls()
        self._telegram_refresh_status()
        self._set_status("Telegram Manager online", P.purple)

    def _telegram_ensure_controller(self):
        if self.telegram_controller is None:
            from .telegram_bot import TelegramRuntimeController
            self.telegram_controller = TelegramRuntimeController(self.settings, self.router)
        return self.telegram_controller

    def _build_telegram_panel(self) -> None:
        self.telegram_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.telegram_panel.grid_columnconfigure(0, weight=1)
        self.telegram_panel.grid_rowconfigure(2, weight=1)

        top = tk.Frame(self.telegram_panel, bg=P.bg)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        tk.Label(top, text="✈", bg=P.bg, fg=P.purple, font=("Segoe UI Symbol", 38, "bold"), width=3).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))
        tk.Label(top, text="TELEGRAM", bg=P.bg, fg=P.text, font=("Segoe UI", 24, "bold")).grid(row=0, column=1, sticky="w")
        tk.Label(top, text="Manage the bot token, access rules and live polling without restarting the app.", bg=P.bg, fg=P.muted, font=("Segoe UI", 11)).grid(row=1, column=1, sticky="w", pady=(4, 0))
        actions = tk.Frame(top, bg=P.bg)
        actions.grid(row=0, column=2, rowspan=2, sticky="e")
        self._back_to_chat_button(actions).pack(side="left", padx=(0, 10))
        self._llm_button(actions, "▶ Start", self._telegram_start, primary=True).pack(side="left", padx=(0, 10))
        self._llm_button(actions, "■ Stop", self._telegram_stop).pack(side="left", padx=(0, 10))
        self._llm_button(actions, "↻ Restart", self._telegram_restart).pack(side="left")

        body = tk.Frame(self.telegram_panel, bg=P.bg)
        body.grid(row=2, column=0, sticky="nsew", pady=(16, 0))
        body.grid_columnconfigure(0, minsize=560, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        settings_card = tk.Frame(body, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        settings_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        settings_card.grid_columnconfigure(1, weight=1)
        tk.Label(settings_card, text="BOT SETTINGS", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
        self.telegram_enabled_var = tk.BooleanVar(value=self.telegram_config.enabled)
        self.telegram_auto_start_var = tk.BooleanVar(value=self.telegram_config.auto_start)
        self.telegram_allow_all_var = tk.BooleanVar(value=self.telegram_config.allow_all)
        self.telegram_token_var = tk.StringVar(value=self.telegram_config.token)
        self.telegram_owner_ids_var = tk.StringVar(value=", ".join(map(str, self.telegram_config.owner_ids or [])))
        self.telegram_owner_usernames_var = tk.StringVar(value=", ".join("@" + u for u in (self.telegram_config.owner_usernames or [])))

        tk.Label(settings_card, text="Bot Token", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=1, column=0, sticky="w", pady=7, padx=(0, 12))
        tk.Entry(settings_card, textvariable=self.telegram_token_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", highlightbackground=P.border, highlightthickness=1).grid(row=1, column=1, sticky="ew", ipady=7, pady=7)
        tk.Label(settings_card, text="Owner usernames", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=2, column=0, sticky="w", pady=7, padx=(0, 12))
        tk.Entry(settings_card, textvariable=self.telegram_owner_usernames_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", highlightbackground=P.border, highlightthickness=1).grid(row=2, column=1, sticky="ew", ipady=7, pady=7)
        tk.Label(settings_card, text="Legacy owner IDs", bg=P.panel_2, fg=P.muted_2, font=self.font_small).grid(row=3, column=0, sticky="w", pady=7, padx=(0, 12))
        tk.Entry(settings_card, textvariable=self.telegram_owner_ids_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", highlightbackground=P.border, highlightthickness=1).grid(row=3, column=1, sticky="ew", ipady=7, pady=7)

        toggles = tk.Frame(settings_card, bg=P.panel_2)
        toggles.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 10))
        for idx, (label, var) in enumerate([
            ("Enabled", self.telegram_enabled_var),
            ("Auto-start with GUI", self.telegram_auto_start_var),
            ("Allow all users", self.telegram_allow_all_var),
        ]):
            tk.Checkbutton(toggles, text=label, variable=var, bg=P.panel_2, fg=P.text, activebackground=P.panel_2, activeforeground=P.text, selectcolor=P.purple_dark, relief="flat", font=self.font_small, cursor="hand2").grid(row=0, column=idx, sticky="w", padx=(0, 18))

        tk.Label(settings_card, text="Tip: zet Allow all uit als alleen de ingevulde Telegram usernames mogen praten met de bot. Bijvoorbeeld: @monacoEUU.", bg=P.panel_2, fg=P.muted, font=self.font_small, wraplength=500, justify="left").grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 12))
        save_line = tk.Frame(settings_card, bg=P.panel_2)
        save_line.grid(row=6, column=0, columnspan=2, sticky="ew")
        save_line.grid_columnconfigure(0, weight=1)
        save_line.grid_columnconfigure(1, weight=1)
        self._llm_button(save_line, "Save & Apply", self._telegram_save_apply, primary=True).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._llm_button(save_line, "Test Token", self._telegram_test_token).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        log_card = tk.Frame(settings_card, bg=P.panel, padx=12, pady=10, highlightbackground=P.border, highlightthickness=1)
        log_card.grid(row=7, column=0, columnspan=2, sticky="nsew", pady=(16, 0))
        settings_card.grid_rowconfigure(7, weight=1)
        log_card.grid_columnconfigure(0, weight=1)
        log_card.grid_rowconfigure(1, weight=1)
        tk.Label(log_card, text="TELEGRAM ACTION LOG", bg=P.panel, fg=P.gold, font=("Consolas", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.telegram_logs_text = tk.Text(log_card, bg="#03050b", fg="#d9e0ff", relief="flat", wrap="word", font=("Consolas", 9), padx=8, pady=7)
        self.telegram_logs_text.grid(row=1, column=0, sticky="nsew")
        self.telegram_logs_text.configure(state="disabled")

        status_card = tk.Frame(body, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        status_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        status_card.grid_columnconfigure(0, weight=1)
        status_card.grid_rowconfigure(1, weight=1)
        tk.Label(status_card, text="LIVE STATUS", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 12))
        self.telegram_status_text = tk.Text(status_card, bg="#03050b", fg="#d9e0ff", relief="flat", wrap="word", font=("Consolas", 10), padx=12, pady=10)
        self.telegram_status_text.grid(row=1, column=0, sticky="nsew")
        self.telegram_status_text.configure(state="disabled")

    def _telegram_cfg_from_controls(self) -> TelegramRuntimeConfig:
        owner_ids = sorted(parse_owner_ids(self.telegram_owner_ids_var.get() if self.telegram_owner_ids_var else ""))
        owner_usernames = sorted(parse_owner_usernames(self.telegram_owner_usernames_var.get() if self.telegram_owner_usernames_var else ""))
        return TelegramRuntimeConfig(
            enabled=bool(self.telegram_enabled_var.get() if self.telegram_enabled_var else False),
            token=(self.telegram_token_var.get().strip() if self.telegram_token_var else ""),
            owner_ids=owner_ids,
            owner_usernames=owner_usernames,
            allow_all=bool(self.telegram_allow_all_var.get() if self.telegram_allow_all_var else True),
            auto_start=bool(self.telegram_auto_start_var.get() if self.telegram_auto_start_var else False),
        )

    def _telegram_sync_controls(self) -> None:
        self.telegram_config = load_telegram_runtime_config(self.settings)
        if self.telegram_enabled_var: self.telegram_enabled_var.set(self.telegram_config.enabled)
        if self.telegram_auto_start_var: self.telegram_auto_start_var.set(self.telegram_config.auto_start)
        if self.telegram_allow_all_var: self.telegram_allow_all_var.set(self.telegram_config.allow_all)
        if self.telegram_token_var and not self.telegram_token_var.get(): self.telegram_token_var.set(self.telegram_config.token)
        if self.telegram_owner_ids_var: self.telegram_owner_ids_var.set(", ".join(map(str, self.telegram_config.owner_ids or [])))
        if self.telegram_owner_usernames_var: self.telegram_owner_usernames_var.set(", ".join("@" + u for u in (self.telegram_config.owner_usernames or [])))

    def _telegram_log(self, message: str, level: str = "INFO") -> None:
        self._emit_activity(f"Telegram: {message}", level)
        if self.telegram_logs_text is None:
            return
        self.telegram_logs_text.configure(state="normal")
        self.telegram_logs_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {level.upper():<4} {message}\n")
        self.telegram_logs_text.see("end")
        self.telegram_logs_text.configure(state="disabled")

    def _telegram_save_apply(self) -> TelegramRuntimeConfig:
        cfg = self._telegram_cfg_from_controls()
        save_telegram_runtime_config(self.settings, cfg)
        apply_telegram_runtime_config(self.settings, cfg)
        self.telegram_config = cfg
        if self.telegram_controller is not None:
            self.telegram_controller.config = cfg
        self._telegram_log("Settings saved to data/telegram_settings.json", "OK")
        self._telegram_refresh_status()
        return cfg

    def _telegram_start(self) -> None:
        cfg = self._telegram_save_apply()
        controller = self._telegram_ensure_controller()
        ok, msg = controller.start(cfg)
        self._telegram_log(msg, "OK" if ok else "ERR")
        self._telegram_refresh_status()

    def _telegram_stop(self) -> None:
        controller = self._telegram_ensure_controller()
        ok, msg = controller.stop(wait=True)
        self._telegram_log(msg, "OK" if ok else "WARN")
        self._telegram_refresh_status()

    def _telegram_restart(self) -> None:
        cfg = self._telegram_save_apply()
        controller = self._telegram_ensure_controller()
        ok, msg = controller.restart(cfg)
        self._telegram_log(msg, "OK" if ok else "ERR")
        self._telegram_refresh_status()

    def _telegram_test_token(self) -> None:
        cfg = self._telegram_save_apply()
        token = cfg.token.strip()
        if not token:
            messagebox.showwarning("M0N4C0 Telegram", "Geen token ingevuld.")
            return
        try:
            import requests
            r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=12)
            if not r.ok:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            result = data.get("result", {}) if isinstance(data, dict) else {}
            msg = f"Token OK. Bot: @{result.get('username', 'unknown')} / {result.get('first_name', 'unknown')}"
            self._telegram_log(msg, "OK")
            messagebox.showinfo("M0N4C0 Telegram", msg)
        except Exception as exc:
            msg = f"Token test failed: {type(exc).__name__}: {exc}"
            self._telegram_log(msg, "ERR")
            messagebox.showerror("M0N4C0 Telegram", msg)

    def _telegram_refresh_status(self) -> None:
        cfg = self.telegram_config
        status = {
            "running": False,
            "enabled": cfg.enabled,
            "token": "set" if cfg.token else "missing",
            "allow_all": cfg.allow_all,
            "owner_ids": cfg.owner_ids or [],
            "owner_usernames": cfg.owner_usernames or [],
            "auto_start": cfg.auto_start,
            "uptime_seconds": 0,
            "last_error": "",
        }
        if self.telegram_controller is not None:
            try:
                status.update(self.telegram_controller.status())
            except Exception as exc:
                status["last_error"] = f"{type(exc).__name__}: {exc}"
        lines = [
            f"Running        {status['running']}",
            f"Enabled        {status['enabled']}",
            f"Token          {self.telegram_config.token or 'missing'}",
            f"Allow all      {status['allow_all']}",
            f"Owner names    {', '.join('@' + u for u in status.get('owner_usernames', [])) or '-'}",
            f"Legacy IDs     {', '.join(map(str, status['owner_ids'])) or '-'}",
            f"Auto start     {status['auto_start']}",
            f"Uptime         {status['uptime_seconds']} sec",
            f"Last error     {status['last_error'] or '-'}",
            "",
            "Runtime notes:",
            "- Start/Stop/Restart werkt live vanuit deze GUI.",
            "- Token wordt lokaal opgeslagen in data/telegram_settings.json.",
            "- Bestaande database-data wordt niet aangeraakt.",
        ]
        self._db_set_text(self.telegram_status_text, "\n".join(lines))

    def _telegram_autostart_if_enabled(self) -> None:
        try:
            cfg = load_telegram_runtime_config(self.settings)
            apply_telegram_runtime_config(self.settings, cfg)
            self.telegram_config = cfg
            if cfg.enabled and cfg.auto_start and cfg.token:
                controller = self._telegram_ensure_controller()
                ok, msg = controller.start(cfg)
                self._telegram_log(msg, "OK" if ok else "ERR")
        except Exception as exc:
            self._emit_activity(f"Telegram autostart skipped: {type(exc).__name__}: {exc}", "WARN")

    # ---------- brain nodes ----------
    def _show_live_feed_page(self) -> None:
        self._show_panel_base("live_feed_panel", self._build_live_feed_panel, "Live Feed visible")
        self._copy_activity_to_widget(self.live_feed_text)

    def _build_live_feed_panel(self) -> None:
        self.live_feed_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.live_feed_panel.grid_columnconfigure(0, weight=1)
        self.live_feed_panel.grid_rowconfigure(2, weight=1)
        self._build_simple_page_header(self.live_feed_panel, "⌁", "LIVE FEED", "Bekijk precies wat M0N4C0 doet zonder dat deze belangrijke feed buiten beeld verdwijnt.")
        bar = tk.Frame(self.live_feed_panel, bg=P.bg)
        bar.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        self._llm_button(bar, "Refresh Feed", lambda: self._copy_activity_to_widget(self.live_feed_text), primary=True).pack(side="left", padx=(0, 8))
        self._llm_button(bar, "Back to Chat", self._show_chat_view).pack(side="left")
        self.live_feed_text = tk.Text(self.live_feed_panel, bg="#03050b", fg="#d9e0ff", relief="flat", wrap="word", font=("Consolas", 10), padx=14, pady=12)
        self.live_feed_text.grid(row=2, column=0, sticky="nsew")
        self.live_feed_text.configure(state="disabled")

    def _future_button(self, label: str) -> None:
        self._show_chat_view()
        self._add_system_message(f"{label} staat klaar in het menu. Die knop bouwen we later functioneel uit.")

    def _set_text_widget(self, widget: tk.Text | None, text: str) -> None:
        self._db_set_text(widget, text)

    def _show_panel_base(self, attr: str, build: Callable[[], None], status: str = "Page ready") -> tk.Frame:
        self.current_view = attr.replace("_panel", "")
        self.header.grid_remove()
        self.chat_holder.grid_remove()
        self.input_footer.grid_remove()
        self._hide_extra_panels()
        if getattr(self, attr, None) is None:
            build()
        panel = getattr(self, attr)
        assert panel is not None
        panel.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self._set_status(status, P.purple)
        return panel

    def _build_simple_page_header(self, parent: tk.Frame, icon: str, title: str, subtitle: str) -> tk.Frame:
        top = tk.Frame(parent, bg=P.bg)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        tk.Label(top, text=icon, bg=P.bg, fg=P.purple, font=("Segoe UI Symbol", 36, "bold"), width=3).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))
        tk.Label(top, text=title, bg=P.bg, fg=P.text, font=("Segoe UI", 24, "bold")).grid(row=0, column=1, sticky="w")
        tk.Label(top, text=subtitle, bg=P.bg, fg=P.muted, font=("Segoe UI", 11)).grid(row=1, column=1, sticky="w", pady=(4, 0))
        self._back_to_chat_button(top).grid(row=0, column=2, rowspan=2, sticky="e")
        return top

    def _show_mission_control(self) -> None:
        self._show_panel_base("mission_panel", self._build_mission_control_panel, "Mission Control online")
        self._refresh_mission_status()

    def _build_mission_control_panel(self) -> None:
        self.mission_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.mission_panel.grid_columnconfigure(0, weight=1)
        self.mission_panel.grid_rowconfigure(3, weight=1)
        self._build_simple_page_header(self.mission_panel, "♜", "MISSION CONTROL", "Autopilot planner: doel erin, plan eruit, workers kiezen en research starten.")

        controls = tk.Frame(self.mission_panel, bg=P.panel, padx=16, pady=14, highlightbackground=P.border, highlightthickness=1)
        controls.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        controls.grid_columnconfigure(1, weight=1)
        self.mission_goal_var = tk.StringVar(value="")
        self.mission_mode_var = tk.StringVar(value="deep")
        self.mission_workers_var = tk.IntVar(value=3)
        tk.Label(controls, text="Groot doel", bg=P.panel, fg=P.muted, font=self.font_small).grid(row=0, column=0, sticky="w", padx=(0, 8))
        tk.Entry(controls, textvariable=self.mission_goal_var, bg=P.panel_2, fg=P.text, insertbackground=P.text, relief="flat", font=self.font_body).grid(row=0, column=1, sticky="ew", ipady=8, padx=(0, 8))
        mode = tk.OptionMenu(controls, self.mission_mode_var, "deep", "topic", "website", "ebooks", "documents", "wikipedia", "competitor", "news")
        self._style_option_menu(mode)
        mode.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        tk.Label(controls, text="Workers", bg=P.panel, fg=P.muted, font=self.font_small).grid(row=0, column=3, sticky="e", padx=(0, 4))
        tk.Spinbox(controls, from_=1, to=8, textvariable=self.mission_workers_var, width=4, bg=P.panel_2, fg=P.text, insertbackground=P.text, relief="flat").grid(row=0, column=4, sticky="w", padx=(0, 8))
        tk.Button(controls, text="Create Plan", command=self._mission_create_plan, bg=P.panel_2, fg=P.text, relief="flat", font=self.font_small).grid(row=0, column=5, sticky="e", padx=(0, 8))
        tk.Button(controls, text="Start Mission", command=self._mission_start, bg=P.purple_dark, fg=P.text, relief="flat", font=self.font_body_bold).grid(row=0, column=6, sticky="e")

        plan_card = tk.Frame(self.mission_panel, bg=P.panel, padx=12, pady=10, highlightbackground=P.border, highlightthickness=1)
        plan_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        plan_card.grid_columnconfigure(0, weight=1)
        tk.Label(plan_card, text="MISSION PLAN", bg=P.panel, fg=P.gold, font=("Consolas", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.mission_plan_text = tk.Text(plan_card, height=10, bg="#03050b", fg="#d9e0ff", relief="flat", wrap="word", font=("Consolas", 10), padx=12, pady=10)
        self.mission_plan_text.grid(row=1, column=0, sticky="ew")
        self._set_text_widget(self.mission_plan_text, "Vul een groot doel in en klik Create Plan. Daarna kan M0N4C0 jobs queueën en een worker CMD starten.")

        status_card = tk.Frame(self.mission_panel, bg=P.panel, padx=12, pady=10, highlightbackground=P.border, highlightthickness=1)
        status_card.grid(row=3, column=0, sticky="nsew")
        status_card.grid_columnconfigure(0, weight=1)
        status_card.grid_rowconfigure(1, weight=1)
        tk.Label(status_card, text="MISSION STATUS", bg=P.panel, fg=P.gold, font=("Consolas", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.mission_status_text = tk.Text(status_card, bg="#03050b", fg="#d9e0ff", relief="flat", wrap="word", font=("Consolas", 10), padx=12, pady=10)
        self.mission_status_text.grid(row=1, column=0, sticky="nsew")

    def _mission_plan_lines(self, goal: str, mode: str) -> list[str]:
        return [
            f"Mission: {goal}",
            f"Primary mode: {mode}",
            "",
            "1. Begrijp doel en splits in subvragen.",
            "2. Kies passende bronnen: web, documenten, Wikipedia, e-book links en opgeslagen sources.",
            "3. Queue externe research jobs met fact-check ronde.",
            "4. Laat workers data ophalen, chunkeren, dedupliceren en opslaan.",
            "5. Genereer open vragen na elke ronde en zoek door tot die beantwoord zijn.",
            "6. Schrijf samenvattingen met bronnen, onzekerheden en vervolgstappen.",
            "7. Toon voortgang in Research/Live Feed en bewaar missie-status in app_tasks.",
        ]

    def _mission_create_plan(self) -> None:
        goal = (self.mission_goal_var.get() if self.mission_goal_var else "").strip()
        if not goal:
            messagebox.showinfo("M0N4C0 Mission Control", "Vul eerst een missie/doel in.")
            return
        mode = self.mission_mode_var.get() if self.mission_mode_var else "deep"
        lines = self._mission_plan_lines(goal, mode)
        self._set_text_widget(self.mission_plan_text, "\n".join(lines))
        self._emit_activity(f"Mission plan created: {goal[:80]}", "OK")

    def _mission_start(self) -> None:
        goal = (self.mission_goal_var.get() if self.mission_goal_var else "").strip()
        if not goal:
            messagebox.showinfo("M0N4C0 Mission Control", "Vul eerst een missie/doel in.")
            return
        mode = self.mission_mode_var.get() if self.mission_mode_var else "deep"
        task_id = self.router.db.create_app_task("mission", f"Mission: {goal[:120]}", status="running", progress=5, message="Mission queued", metadata={"goal": goal, "mode": mode})
        # Queue a compact mission pack. One broad/deep job plus a fact-check job gives
        # the worker enough structure without flooding the DB.
        main_job = self.router.db.enqueue_learning_job(goal, 3, mode=mode, priority=8, source="mission_control", agent="mission_control", metadata={"mission_task_id": task_id, "autopilot": True, "goal": goal})
        fact_job = self.router.db.enqueue_learning_job(f"fact check en open vragen: {goal}", 2, mode="deep", priority=7, source="mission_control", agent="mission_control", metadata={"mission_task_id": task_id, "autopilot": True, "phase": "fact_check"})
        self._emit_activity(f"Mission #{task_id} started; jobs #{main_job}, #{fact_job} queued.", "OK")
        if self.mission_workers_var is not None:
            self.research_workers_var = self.research_workers_var or tk.IntVar(value=3)
            self.research_workers_var.set(int(self.mission_workers_var.get()))
        self._start_research_worker_process()
        self._refresh_mission_status()

    def _refresh_mission_status(self) -> None:
        try:
            tasks = self.router.db.list_app_tasks(limit=20)
            jobs = self.router.db.list_learning_jobs(limit=20)
            lines = ["RECENT MISSIONS"]
            for t in tasks:
                if str(t["task_type"]) == "mission":
                    lines.append(f"#{t['id']} | {t['status']} | {t['progress']}% | {t['title']} | {t['updated_at']}")
            lines.append("\nRECENT RESEARCH JOBS")
            for j in jobs[:12]:
                lines.append(f"#{j['id']} | {j['status']} | {j['mode']} | {j['topic']}")
            self._set_text_widget(self.mission_status_text, "\n".join(lines))
        except Exception as exc:
            self._set_text_widget(self.mission_status_text, f"Mission status laden mislukt: {type(exc).__name__}: {exc}")

    def _show_idle_learning(self) -> None:
        self._show_panel_base("idle_panel", self._build_idle_learning_panel, "Idle Learning online")
        self._refresh_idle_topics()

    def _build_idle_learning_panel(self) -> None:
        self.idle_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.idle_panel.grid_columnconfigure(0, weight=1)
        self.idle_panel.grid_rowconfigure(3, weight=1)
        self._build_simple_page_header(self.idle_panel, "☼", "IDLE LEARNING", "Als de bot 5+ minuten stil is, queue’t hij eigen research via externe workers.")
        controls = tk.Frame(self.idle_panel, bg=P.panel, padx=16, pady=14, highlightbackground=P.border, highlightthickness=1)
        controls.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        controls.grid_columnconfigure(1, weight=1)
        self.idle_topic_var = tk.StringVar(value="")
        self.idle_enabled_var = tk.BooleanVar(value=bool(self.router.db.get_app_setting("idle_learning_enabled", True)))
        self.idle_wikipedia_var = tk.BooleanVar(value=bool(self.router.db.get_app_setting("idle_wikipedia_enabled", False)))
        self.idle_seconds_var = tk.IntVar(value=int(self.router.db.get_app_setting("idle_seconds", 300)))
        tk.Checkbutton(controls, text="Idle learning enabled", variable=self.idle_enabled_var, bg=P.panel, fg=P.text, selectcolor=P.purple_dark, activebackground=P.panel, activeforeground=P.text, command=self._save_idle_settings).grid(row=0, column=0, sticky="w", padx=(0, 10))
        tk.Checkbutton(controls, text="Wikipedia random als er geen topic klaarstaat", variable=self.idle_wikipedia_var, bg=P.panel, fg=P.text, selectcolor=P.purple_dark, activebackground=P.panel, activeforeground=P.text, command=self._save_idle_settings).grid(row=0, column=1, sticky="w", padx=(0, 10))
        tk.Label(controls, text="Idle seconds", bg=P.panel, fg=P.muted, font=self.font_small).grid(row=0, column=2, sticky="e", padx=(0, 8))
        tk.Spinbox(controls, from_=60, to=7200, textvariable=self.idle_seconds_var, bg=P.panel_2, fg=P.text, width=8, command=self._save_idle_settings).grid(row=0, column=3, sticky="w")
        tk.Label(controls, text="Topic", bg=P.panel, fg=P.muted, font=self.font_small).grid(row=1, column=0, sticky="w", pady=(12, 0))
        tk.Entry(controls, textvariable=self.idle_topic_var, bg=P.panel_2, fg=P.text, insertbackground=P.text, relief="flat", font=self.font_body).grid(row=1, column=1, sticky="ew", pady=(12, 0), ipady=8, padx=(0, 10))
        tk.Button(controls, text="Add Topic", command=self._add_idle_topic, bg=P.purple_dark, fg=P.text, relief="flat", font=self.font_body_bold).grid(row=1, column=2, sticky="e", pady=(12, 0))
        tk.Button(controls, text="Add Wikipedia Topic", command=self._add_idle_wikipedia_topic, bg=P.panel_2, fg=P.gold, relief="flat", font=self.font_small).grid(row=1, column=3, sticky="e", pady=(12, 0), padx=(8,0))
        btns = tk.Frame(self.idle_panel, bg=P.bg)
        btns.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        tk.Button(btns, text="Start Idle Watcher CMD", command=self._start_idle_worker, bg=P.purple_dark, fg=P.text, relief="flat", font=self.font_small).pack(side="left", padx=(0, 8))
        tk.Button(btns, text="Queue Next Topic Now", command=self._queue_next_idle_topic_now, bg=P.panel_2, fg=P.text, relief="flat", font=self.font_small).pack(side="left", padx=(0, 8))
        tk.Button(btns, text="Refresh", command=self._refresh_idle_topics, bg=P.panel_2, fg=P.text, relief="flat", font=self.font_small).pack(side="left")
        self.idle_topics_text = tk.Text(self.idle_panel, bg=P.panel, fg=P.text, relief="flat", font=("Consolas", 10), padx=12, pady=10)
        self.idle_topics_text.grid(row=3, column=0, sticky="nsew")

    def _save_idle_settings(self) -> None:
        if self.idle_enabled_var is not None:
            self.router.db.set_app_setting("idle_learning_enabled", bool(self.idle_enabled_var.get()))
        if self.idle_seconds_var is not None:
            self.router.db.set_app_setting("idle_seconds", int(self.idle_seconds_var.get()))
        if self.idle_wikipedia_var is not None:
            self.router.db.set_app_setting("idle_wikipedia_enabled", bool(self.idle_wikipedia_var.get()))

    def _add_idle_topic(self) -> None:
        topic = (self.idle_topic_var.get() if self.idle_topic_var else "").strip()
        if not topic:
            return
        self.router.db.upsert_idle_topic(topic, enabled=True, priority=5, rounds=2, mode="topic")
        self.idle_topic_var.set("")
        self._refresh_idle_topics()

    def _add_idle_wikipedia_topic(self) -> None:
        topic = (self.idle_topic_var.get() if self.idle_topic_var else "").strip() or "random wikipedia"
        self.router.db.upsert_idle_topic(topic, enabled=True, priority=5, rounds=2, mode="wikipedia", metadata={"source": "idle_gui_wikipedia"})
        if self.idle_topic_var:
            self.idle_topic_var.set("")
        if self.idle_wikipedia_var:
            self.idle_wikipedia_var.set(True)
        self._save_idle_settings()
        self._refresh_idle_topics()

    def _refresh_idle_topics(self) -> None:
        rows = self.router.db.list_idle_topics(limit=200)
        lines = []
        for r in rows:
            lines.append(f"#{r['id']:>3} | {'ON ' if r['enabled'] else 'OFF'} | prio={r['priority']} | rounds={r['rounds']} | {r['mode']} | last={r['last_queued_at'] or '-'} | {r['topic']}")
        self._set_text_widget(self.idle_topics_text, "\n".join(lines) if lines else "Geen idle topics. Voeg hierboven onderwerpen toe.")
        self._save_idle_settings()

    def _start_idle_worker(self) -> None:
        if self.idle_worker_process is not None and self.idle_worker_process.poll() is None:
            messagebox.showinfo("M0N4C0 Idle", "Idle watcher draait al vanuit deze GUI.")
            return
        self._save_idle_settings()
        idle_seconds = int(self.idle_seconds_var.get() if self.idle_seconds_var else 300)
        cmd = [sys.executable, str(self.settings.root / "idle_worker.py"), "--idle-seconds", str(idle_seconds)]
        try:
            if os.name == "nt":
                self.idle_worker_process = subprocess.Popen(cmd, cwd=str(self.settings.root), creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                self.idle_worker_process = subprocess.Popen(cmd, cwd=str(self.settings.root))
            self._emit_activity("Idle watcher process started.", "OK")
        except Exception as exc:
            messagebox.showerror("M0N4C0 Idle", f"Idle watcher starten mislukt:\n{type(exc).__name__}: {exc}")

    def _queue_next_idle_topic_now(self) -> None:
        topics = self.router.db.list_idle_topics(enabled_only=True, limit=1)
        if not topics:
            if self.idle_wikipedia_var is not None and self.idle_wikipedia_var.get():
                job_id = self.router.db.enqueue_learning_job("random wikipedia", 2, mode="wikipedia", priority=4, source="idle_learning", agent="idle_gui", metadata={"manual": True, "source": "wikipedia_random"})
                self._emit_activity(f"Idle Wikipedia job queued manually: #{job_id}", "OK")
                self._refresh_idle_topics()
                return
            messagebox.showinfo("M0N4C0 Idle", "Geen enabled idle topic gevonden.")
            return
        r = topics[0]
        job_id = self.router.db.enqueue_learning_job(str(r['topic']), int(r['rounds'] or 2), mode=str(r['mode'] or 'topic'), priority=int(r['priority'] or 5), source="idle_learning", agent="idle_gui")
        self.router.db.mark_idle_topic_queued(int(r['id']))
        self._emit_activity(f"Idle job queued manually: #{job_id}", "OK")
        self._refresh_idle_topics()

    def _show_performance_center(self) -> None:
        self._show_panel_base("performance_panel", self._build_performance_panel, "Performance Center online")
        self._refresh_performance_report()

    def _performance_slider(self, parent: tk.Widget, label: str, var: tk.IntVar, low: int, high: int, row: int, suffix: str = "MB") -> None:
        frame = tk.Frame(parent, bg=P.panel_2)
        frame.grid(row=row, column=0, sticky="ew", pady=8)
        frame.grid_columnconfigure(1, weight=1)
        value = tk.Label(frame, text=f"{var.get()} {suffix}", bg=P.panel, fg=P.text, font=("Consolas", 10), width=10, padx=8, pady=4)
        value.grid(row=0, column=2, sticky="e", padx=(10, 0))
        tk.Label(frame, text=label, bg=P.panel_2, fg=P.text, font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 12))
        scale = tk.Scale(frame, from_=low, to=high, resolution=16, orient="horizontal", showvalue=0, variable=var, bg=P.panel_2, fg=P.text, troughcolor="#313849", activebackground=P.purple, highlightthickness=0, bd=0, sliderrelief="flat")
        scale.grid(row=0, column=1, sticky="ew")
        scale.configure(command=lambda _v: value.configure(text=f"{var.get()} {suffix}"))

    def _build_performance_panel(self) -> None:
        self.performance_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.performance_panel.grid_columnconfigure(0, weight=1)
        self.performance_panel.grid_rowconfigure(2, weight=1)
        self._build_simple_page_header(self.performance_panel, "⚡", "PERFORMANCE CENTER", "Gebruiksvriendelijke presets, sliders, health checks en veilige database-optimalisatie.")

        self.performance_preset_var = tk.StringVar(value="Balanced")
        self.performance_cache_mb_var = tk.IntVar(value=64)
        self.performance_mmap_mb_var = tk.IntVar(value=256)
        self.performance_auto_backup_var = tk.BooleanVar(value=True)
        self.performance_wal_var = tk.BooleanVar(value=True)

        controls = tk.Frame(self.performance_panel, bg=P.bg)
        controls.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        controls.grid_columnconfigure(0, weight=1)
        controls.grid_columnconfigure(1, weight=1)
        controls.grid_columnconfigure(2, weight=1)

        tuning = tk.Frame(controls, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        tuning.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tuning.grid_columnconfigure(0, weight=1)
        tk.Label(tuning, text="SPEED PROFILE", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))
        tk.Label(tuning, text="Kies simpel een profiel. De sliders blijven aanpasbaar als je fijner wil tunen.", bg=P.panel_2, fg=P.muted, font=self.font_small, wraplength=360, justify="left").grid(row=1, column=0, sticky="w", pady=(0, 10))
        menu = tk.OptionMenu(tuning, self.performance_preset_var, "Safe", "Balanced", "Fast", "Max Performance", command=lambda _v: self._performance_apply_preset())
        self._style_option_menu(menu)
        menu.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self._performance_slider(tuning, "SQLite cache", self.performance_cache_mb_var, 16, 512, 3)
        self._performance_slider(tuning, "Memory map", self.performance_mmap_mb_var, 0, 2048, 4)

        switches = tk.Frame(controls, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        switches.grid(row=0, column=1, sticky="nsew", padx=8)
        switches.grid_columnconfigure(0, weight=1)
        tk.Label(switches, text="SAFE CONTROLS", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))
        tk.Checkbutton(switches, text="Maak backup vóór zware database-acties", variable=self.performance_auto_backup_var, bg=P.panel_2, fg=P.text, activebackground=P.panel_2, activeforeground=P.text, selectcolor=P.purple_dark, relief="flat", font=self.font_small, cursor="hand2").grid(row=1, column=0, sticky="w", pady=6)
        tk.Checkbutton(switches, text="WAL mode gebruiken voor betere SQLite performance", variable=self.performance_wal_var, bg=P.panel_2, fg=P.text, activebackground=P.panel_2, activeforeground=P.text, selectcolor=P.purple_dark, relief="flat", font=self.font_small, cursor="hand2").grid(row=2, column=0, sticky="w", pady=6)
        tk.Label(switches, text="Alles draait veilig: geen data wordt verwijderd behalve als je bewust cache wist.", bg=P.panel_2, fg=P.muted, font=self.font_small, wraplength=360, justify="left").grid(row=3, column=0, sticky="w", pady=(10, 0))

        actions = tk.Frame(controls, bg=P.panel_2, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        actions.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        actions.grid_columnconfigure(0, weight=1)
        tk.Label(actions, text="ACTIONS", bg=P.panel_2, fg=P.text, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))
        self._llm_button(actions, "Apply Speed Settings", self._performance_apply_speed_settings, primary=True).grid(row=1, column=0, sticky="ew", pady=4)
        self._llm_button(actions, "Refresh Health Check", self._refresh_performance_report).grid(row=2, column=0, sticky="ew", pady=4)
        self._llm_button(actions, "Rebuild FTS", self._performance_rebuild_fts).grid(row=3, column=0, sticky="ew", pady=4)
        self._llm_button(actions, "Backup DB", self._performance_backup_db).grid(row=4, column=0, sticky="ew", pady=4)
        self._llm_button(actions, "Clear Answer Cache", self._performance_clear_answer_cache).grid(row=5, column=0, sticky="ew", pady=4)

        report_card = tk.Frame(self.performance_panel, bg=P.panel, padx=12, pady=10, highlightbackground=P.border, highlightthickness=1)
        report_card.grid(row=2, column=0, sticky="nsew")
        report_card.grid_columnconfigure(0, weight=1)
        report_card.grid_rowconfigure(1, weight=1)
        tk.Label(report_card, text="HEALTH REPORT", bg=P.panel, fg=P.gold, font=("Consolas", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.performance_text = tk.Text(report_card, bg="#03050b", fg="#d9e0ff", relief="flat", font=("Consolas", 10), padx=12, pady=10, wrap="word")
        self.performance_text.grid(row=1, column=0, sticky="nsew")

    def _performance_apply_preset(self) -> None:
        preset = self.performance_preset_var.get() if self.performance_preset_var else "Balanced"
        values = {
            "Safe": (32, 128),
            "Balanced": (64, 256),
            "Fast": (128, 512),
            "Max Performance": (256, 1024),
        }.get(preset, (64, 256))
        if self.performance_cache_mb_var: self.performance_cache_mb_var.set(values[0])
        if self.performance_mmap_mb_var: self.performance_mmap_mb_var.set(values[1])
        self._emit_activity(f"Performance preset selected: {preset}", "STEP")

    def _performance_apply_speed_settings(self) -> None:
        if self.performance_auto_backup_var is not None and self.performance_auto_backup_var.get():
            self._performance_backup_db()
        cache_mb = int(self.performance_cache_mb_var.get() if self.performance_cache_mb_var else 64)
        mmap_mb = int(self.performance_mmap_mb_var.get() if self.performance_mmap_mb_var else 256)
        with self.router.db.connect() as conn:
            if self.performance_wal_var is None or self.performance_wal_var.get():
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute(f"PRAGMA cache_size={-max(16, cache_mb) * 1024}")
            conn.execute(f"PRAGMA mmap_size={max(0, mmap_mb) * 1024 * 1024}")
            conn.execute("PRAGMA optimize")
        self._emit_activity(f"Performance settings applied: cache={cache_mb}MB mmap={mmap_mb}MB", "OK")
        self._refresh_performance_report()

    def _refresh_performance_report(self) -> None:
        try:
            stats = self.router.db.stats()
            with self.router.db.connect() as conn:
                pragmas = {
                    "journal_mode": conn.execute("PRAGMA journal_mode").fetchone()[0],
                    "page_count": conn.execute("PRAGMA page_count").fetchone()[0],
                    "page_size": conn.execute("PRAGMA page_size").fetchone()[0],
                    "cache_size": conn.execute("PRAGMA cache_size").fetchone()[0],
                    "mmap_size": conn.execute("PRAGMA mmap_size").fetchone()[0],
                    "quick_check": conn.execute("PRAGMA quick_check").fetchone()[0],
                }
            db_mb = (int(pragmas["page_count"]) * int(pragmas["page_size"])) / (1024 * 1024)
            lines = [
                "DATABASE HEALTH",
                f"Database file: {self.settings.db_path}",
                f"Estimated size: {db_mb:.1f} MB",
                "",
                "TABLE / APP STATS",
                *[f"{k}: {v}" for k, v in stats.items()],
                "",
                "SQLITE PRAGMAS",
                *[f"{k}: {v}" for k, v in pragmas.items()],
                "",
                "GUIDE",
                "- Safe: minder RAM, stabiel voor oude machines.",
                "- Balanced: aanbevolen standaard.",
                "- Fast/Max: sneller browsen/zoeken, gebruikt meer geheugen.",
            ]
            self._set_text_widget(self.performance_text, "\n".join(lines))
        except Exception as exc:
            self._set_text_widget(self.performance_text, f"Health check error: {type(exc).__name__}: {exc}")

    def _performance_optimize_db(self) -> None:
        self._performance_apply_speed_settings()

    def _performance_rebuild_fts(self) -> None:
        if self.performance_auto_backup_var is not None and self.performance_auto_backup_var.get():
            self._performance_backup_db()
        with self.router.db.connect() as conn:
            try:
                conn.execute("INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts) VALUES('rebuild')")
                self._emit_activity("FTS index rebuilt.", "OK")
            except Exception as exc:
                self.router.db.log_error("FTS_REBUILD", f"{type(exc).__name__}: {exc}")
                self._emit_activity(f"FTS rebuild skipped/failed: {type(exc).__name__}: {exc}", "WARN")
        self._refresh_performance_report()

    def _performance_backup_db(self) -> None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        dst = self.settings.root / "data" / "backups" / f"monaco_memory_backup_{ts}.db"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.settings.db_path, dst)
        self._emit_activity(f"Database backup created: {dst}", "OK")
        self._refresh_performance_report()

    def _performance_clear_answer_cache(self) -> None:
        with self.router.db.connect() as conn:
            conn.execute("DELETE FROM answer_cache")
        self._emit_activity("Answer cache cleared.", "OK")
        self._refresh_performance_report()

    def _show_memory_manager(self) -> None:
        self._show_panel_base("memory_panel", self._build_memory_panel, "Memory manager online")
        self._refresh_memory_manager()

    def _build_memory_panel(self) -> None:
        self.memory_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.memory_panel.grid_columnconfigure(0, weight=1)
        self.memory_panel.grid_rowconfigure(2, weight=1)
        self._build_simple_page_header(self.memory_panel, "▤", "MEMORY MANAGER", "Bekijk memory facts en lokale kennis zonder destructive defaults.")
        bar = tk.Frame(self.memory_panel, bg=P.bg)
        bar.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        bar.grid_columnconfigure(1, weight=1)
        self.memory_search_var = tk.StringVar(value="")
        tk.Label(bar, text="Search", bg=P.bg, fg=P.muted, font=self.font_small).grid(row=0, column=0, sticky="w", padx=(0, 8))
        tk.Entry(bar, textvariable=self.memory_search_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", font=self.font_body).grid(row=0, column=1, sticky="ew", ipady=8)
        tk.Button(bar, text="Search", command=self._refresh_memory_manager, bg=P.purple_dark, fg=P.text, relief="flat", font=self.font_small).grid(row=0, column=2, sticky="e", padx=(8, 0))
        tk.Button(bar, text="Lege Brein / Wipe Knowledge", command=self._wipe_brain_from_gui, bg="#3a1320", fg=P.danger, relief="flat", font=self.font_small).grid(row=0, column=3, sticky="e", padx=(8, 0))
        self.memory_text = tk.Text(self.memory_panel, bg=P.panel, fg=P.text, relief="flat", font=("Consolas", 10), padx=12, pady=10)
        self.memory_text.grid(row=2, column=0, sticky="nsew")

    def _wipe_brain_from_gui(self) -> None:
        if not messagebox.askyesno("M0N4C0 Lege Brein", "WEET JE ZEKER DAT JE HET BREIN WILT WISSEN?\n\nEr wordt eerst automatisch een backup gemaakt. Daarna worden kennis, memory, relaties, personen, sources, researchdata en learned facts gewist."):
            return
        try:
            result = self.router.db.wipe_brain_data(make_backup=True)
            backup = result.get("backup")
            counts = result.get("deleted_counts", {})
            deleted_total = sum(int(v or 0) for v in counts.values()) if isinstance(counts, dict) else 0
            self._emit_activity(f"Empty brain executed. Deleted rows={deleted_total}. Backup={backup}", "WARN")
            messagebox.showinfo("M0N4C0 Lege Brein", f"Brein gewist. Backup gemaakt:\n{backup}\n\nVerwijderde rijen: {deleted_total}")
            self._refresh_memory_manager()
            if self.research_panel is not None:
                self._refresh_research_jobs()
            if self.idle_panel is not None:
                self._refresh_idle_topics()
        except Exception as exc:
            messagebox.showerror("M0N4C0 Lege Brein", f"Wissen mislukt:\n{type(exc).__name__}: {exc}")

    def _refresh_memory_manager(self) -> None:
        q = (self.memory_search_var.get() if self.memory_search_var else "").strip()
        lines = []
        if q:
            rows = self.router.db.search_memory(q, limit=50)
            lines.append(f"MEMORY SEARCH: {q}")
            for r in rows:
                lines.append(f"#{r['id']} {r['subject']} {r['predicate']} {r['object']} conf={r['confidence']} user={r['user_key'] or '-'}")
            chunks = self.router.db.fts_search(q, limit=20)
            lines.append("\nKNOWLEDGE MATCHES")
            for c in chunks:
                lines.append(f"#{c['id']} topic={c['topic']} title={c['title']} url={c['url']}\n  {str(c['content'])[:240]}...")
        else:
            with self.router.db.connect() as conn:
                rows = conn.execute("SELECT * FROM memory_facts ORDER BY updated_at DESC LIMIT 80").fetchall()
            lines.append("RECENT MEMORY FACTS")
            for r in rows:
                lines.append(f"#{r['id']} {r['subject']} {r['predicate']} {r['object']} conf={r['confidence']} updated={r['updated_at']}")
        self._set_text_widget(self.memory_text, "\n".join(lines) if lines else "Geen memory gevonden.")

    def _show_logs_page(self) -> None:
        self._show_panel_base("logs_panel", self._build_logs_panel, "Logs online")
        self._refresh_logs_page()

    def _build_logs_panel(self) -> None:
        self.logs_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.logs_panel.grid_columnconfigure(0, weight=1)
        self.logs_panel.grid_rowconfigure(2, weight=1)
        self._build_simple_page_header(self.logs_panel, "▧", "LOGS", "Errors, research events en technische status.")
        bar = tk.Frame(self.logs_panel, bg=P.bg)
        bar.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        tk.Button(bar, text="Refresh", command=self._refresh_logs_page, bg=P.purple_dark, fg=P.text, relief="flat", font=self.font_small).pack(side="left")
        self.logs_text = tk.Text(self.logs_panel, bg=P.panel, fg=P.text, relief="flat", font=("Consolas", 10), padx=12, pady=10)
        self.logs_text.grid(row=2, column=0, sticky="nsew")

    def _refresh_logs_page(self) -> None:
        with self.router.db.connect() as conn:
            errs = conn.execute("SELECT * FROM errors ORDER BY id DESC LIMIT 50").fetchall()
            evs = conn.execute("SELECT * FROM learning_events ORDER BY id DESC LIMIT 80").fetchall()
        lines = ["ERRORS"]
        for e in errs:
            lines.append(f"#{e['id']} [{e['created_at']}] {e['error_type']} :: {e['message']}")
        lines.append("\nLEARNING EVENTS")
        for e in evs:
            lines.append(f"#{e['id']} [{e['created_at']}] {e['level']} job={e['job_id'] or '-'} {e['message']}")
        self._set_text_widget(self.logs_text, "\n".join(lines))


    # ---------- Tools page + Build Agent ----------
    def _show_tools_page(self) -> None:
        self._show_panel_base("tools_panel", self._build_tools_panel, "Tools online")
        self._tools_refresh_output("Tools ready. Kies een diagnostic of validator.")

    def _build_tools_panel(self) -> tk.Frame:
        # Maak een nieuwe container frame
        container = tk.Frame(self.main_panel, bg=P.bg)
        
        # 1. Kop
        header = tk.Frame(container, bg=P.bg)
        header.pack(fill="x", padx=20, pady=(20, 10))
        tk.Label(header, text="GhostTrack Tools", font=self.font_heading, bg=P.bg, fg=P.gold).pack()
        tk.Label(header, text="IP, Telefoon en Username opsporing", font=self.font_body, bg=P.bg, fg=P.muted).pack()

        # 2. Input Sectie
        input_frame = tk.Frame(container, bg=P.bg)
        input_frame.pack(fill="x", padx=20, pady=10)
        
        # Tabs voor keuzes
        tab_frame = tk.Frame(input_frame, bg=P.bg)
        tab_frame.pack(fill="x")
        
        # Sla de geselecteerde tool op in de class zodat andere functies erbij kunnen
        self._gt_selected_tool = "ip"
        
        def select_tool(tool):
            self._gt_selected_tool = tool
            if tool == "ip":
                self._gt_label.config(text="Voer IP Adres in (bijv. 8.8.8.8):")
            elif tool == "phone":
                self._gt_label.config(text="Voer Telefoonnummer in (bijv. +31612345678):")
            elif tool == "user":
                self._gt_label.config(text="Voer Username in (bijv. HunxByts):")
        
        # Maak knoppen voor keuzes
        btn_ip = tk.Button(tab_frame, text="IP Tracker", bg=P.purple_dark, fg=P.text, 
                           command=lambda: select_tool("ip"), font=self.font_body_small, padx=10, pady=5)
        btn_ip.pack(side="left", padx=5)
        
        btn_phone = tk.Button(tab_frame, text="Phone Tracker", bg=P.purple_dark, fg=P.text, 
                              command=lambda: select_tool("phone"), font=self.font_body_small, padx=10, pady=5)
        btn_phone.pack(side="left", padx=5)
        
        btn_user = tk.Button(tab_frame, text="Username Tracker", bg=P.purple_dark, fg=P.text, 
                             command=lambda: select_tool("user"), font=self.font_body_small, padx=10, pady=5)
        btn_user.pack(side="left", padx=5)

        # Input veld
        input_row = tk.Frame(input_frame, bg=P.bg)
        input_row.pack(fill="x", pady=10)
        
        self._gt_label = tk.Label(input_row, text="Voer IP Adres in (bijv. 8.8.8.8):", bg=P.bg, fg=P.text)
        self._gt_label.pack(side="left", padx=(0, 10))
        
        self._gt_entry = tk.Entry(input_row, font=self.font_body, bg=P.panel_2, fg=P.text, 
                                  relief="flat", bd=1, highlightbackground=P.border, highlightthickness=1)
        self._gt_entry.pack(side="left", fill="x", expand=True)
        self._gt_entry.insert(0, "8.8.8.8") 

        # Run knop
        btn_run = tk.Button(input_row, text="Start Tracking", bg=P.green, fg=P.text,
                            command=self._gt_run_tracking, font=self.font_body, padx=20, pady=10)
        btn_run.pack(side="left", padx=(10, 0))

        # 3. Output Sectie
        output_frame = tk.Frame(container, bg=P.bg)
        output_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        tk.Label(output_frame, text="Resultaten:", bg=P.bg, fg=P.muted, font=self.font_body).pack(anchor="w")
        
        # Text widget voor resultaten
        self._gt_output = tk.Text(output_frame, bg=P.panel_2, fg=P.text, font=self.font_code, 
                                  relief="flat", bd=1, highlightbackground=P.border, highlightthickness=1,
                                  wrap="word", height=15)
        self._gt_output.pack(fill="both", expand=True, pady=10)
        
        # Scrollbar
        scrollbar = tk.Scrollbar(output_frame, command=self._gt_output.yview)
        scrollbar.pack(side="right", fill="y")
        self._gt_output.config(yscrollcommand=scrollbar.set)

        return container

    # NIEUWE HULP-FUNCTIE: Voeg deze toe net onder _build_tools_panel
    def _gt_run_tracking(self):
        value = self._gt_entry.get().strip()
        tool = self._gt_selected_tool
        
        self._gt_output.delete(1.0, tk.END)
        self._gt_output.insert(tk.END, f"Zoeken naar: {value}...\n\n")
        self.root.update_idletasks()

        result = ""
        if tool == "ip":
            result = ghost_service.ip_track(value)
        elif tool == "phone":
            result = ghost_service.phone_track(value)
        elif tool == "user":
            result = f"Username '{value}' gevonden op:\n- GitHub\n- Twitter\n(Functie te implementeren in tools_service)"

        self._gt_output.insert(tk.END, result + "\n")

    def _show_ghosttrack_tool(self, tool_type: str):
        self.current_ghost_tool = tool_type
        if tool_type == 'ip':
            self.ghost_input_label.config(text="Voer IP Adres in:")
            self.ghost_input_var.set("")
            self.ghost_output_text.delete(1.0, tk.END)
        elif tool_type == 'phone':
            self.ghost_input_label.config(text="Voer Telefoonnummer in (bijv. +31612345678):")
            self.ghost_input_var.set("")
            self.ghost_output_text.delete(1.0, tk.END)
        elif tool_type == 'user':
            self.ghost_input_label.config(text="Voer Username in:")
            self.ghost_input_var.set("")
            self.ghost_output_text.delete(1.0, tk.END)

    def _run_ghosttrack(self):
        input_val = self.ghost_input_var.get().strip()
        self.ghost_output_text.insert(tk.END, f"Zoeken naar: {input_val}...\n\n")
        self.root.update_idletasks()

        try:
            if self.current_ghost_tool == 'ip':
                result = ghost_track_service.ip_track(input_val)
            elif self.current_ghost_tool == 'phone':
                result = ghost_track_service.phone_track(input_val)
            elif self.current_ghost_tool == 'user':
                result = ghost_track_service.username_track(input_val)
            
            self.ghost_output_text.insert(tk.END, result + "\n")
        except Exception as e:
            self.ghost_output_text.insert(tk.END, f"Fout: {e}\n")

# BELANGRIJK: Zorg dat je de import toevoegt bovenaan gui.py
# Voeg dit toe aan je imports sectie:
# from .tools_service import ..., ghost_track_service

    def _build_tools_panel(self) -> None:
        self.tools_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.tools_panel.grid_columnconfigure(0, weight=1)
        self.tools_panel.grid_rowconfigure(1, weight=1)
        self._build_simple_page_header(self.tools_panel, "✣", "TOOLS", "Veilige utilities voor Telegram, bronnen, database en consent-based diagnostics.")

        wrap = tk.Frame(self.tools_panel, bg=P.bg, highlightbackground=P.border, highlightthickness=1)
        wrap.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(0, weight=1)
        canvas = tk.Canvas(wrap, bg=P.bg, highlightthickness=0, bd=0)
        canvas.grid(row=0, column=0, sticky="nsew")
        scroll = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scroll.set)
        content = tk.Frame(canvas, bg=P.bg, padx=16, pady=16)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width))
        self._bind_mousewheel_to_canvas(canvas)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)

        self.tools_username_var = tk.StringVar(value="")
        self.tools_url_var = tk.StringVar(value="")
        self.tools_diag_port_var = tk.IntVar(value=8787)

        user_card = self._tools_card(content, "Telegram username tools", 0, 0)
        tk.Label(user_card, text="Usernames", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=0, column=0, sticky="w")
        tk.Entry(user_card, textvariable=self.tools_username_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", font=self.font_body).grid(row=1, column=0, sticky="ew", ipady=8, pady=(4, 8))
        self._llm_button(user_card, "Normalize usernames", self._tools_normalize_usernames, primary=True).grid(row=2, column=0, sticky="w")
        tk.Label(user_card, text="Voorbeeld: @Name, andereUser → nette lowercase @usernames voor allowlists.", bg=P.panel_2, fg=P.muted_2, font=self.font_small, wraplength=440, justify="left").grid(row=3, column=0, sticky="ew", pady=(8, 0))

        tg_card = self._tools_card(content, "Telegram bot diagnostics", 0, 1)
        self._llm_button(tg_card, "Test saved Telegram token", self._tools_test_telegram_token, primary=True).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self._llm_button(tg_card, "Show runtime Telegram settings", self._tools_show_telegram_settings).grid(row=1, column=0, sticky="w")
        tk.Label(tg_card, text="Token wordt alleen gebruikt voor officiële getMe-check. Geen token wordt in logs/export gezet.", bg=P.panel_2, fg=P.muted_2, font=self.font_small, wraplength=440, justify="left").grid(row=2, column=0, sticky="ew", pady=(8, 0))

        url_card = self._tools_card(content, "Source / URL validator", 1, 0)
        tk.Label(url_card, text="URL", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=0, column=0, sticky="w")
        tk.Entry(url_card, textvariable=self.tools_url_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", font=self.font_body).grid(row=1, column=0, sticky="ew", ipady=8, pady=(4, 8))
        btns = tk.Frame(url_card, bg=P.panel_2)
        btns.grid(row=2, column=0, sticky="ew")
        self._llm_button(btns, "Check URL", self._tools_check_url, primary=True).pack(side="left", padx=(0, 8))
        self._llm_button(btns, "Research URL check", self._tools_research_url_check).pack(side="left")
        tk.Label(url_card, text="Controleert status, redirects, content-type en of het waarschijnlijk een document/e-book is.", bg=P.panel_2, fg=P.muted_2, font=self.font_small, wraplength=440, justify="left").grid(row=3, column=0, sticky="ew", pady=(8, 0))

        net_card = self._tools_card(content, "Consent-based network diagnostics", 1, 1)
        port_row = tk.Frame(net_card, bg=P.panel_2)
        port_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(port_row, text="Port", bg=P.panel_2, fg=P.muted, font=self.font_small).pack(side="left", padx=(0, 8))
        tk.Spinbox(port_row, from_=1024, to=65535, textvariable=self.tools_diag_port_var, width=8, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat").pack(side="left")
        net_btns = tk.Frame(net_card, bg=P.panel_2)
        net_btns.grid(row=1, column=0, sticky="ew")
        self._llm_button(net_btns, "Start consent link", self._tools_start_consent_diagnostic, primary=True).pack(side="left", padx=(0, 8))
        self._llm_button(net_btns, "Stop", self._tools_stop_consent_diagnostic).pack(side="left", padx=(0, 8))
        self._llm_button(net_btns, "View results", self._tools_view_consent_results).pack(side="left")
        self._llm_button(net_card, "My public IP self-check", self._tools_public_ip_check).grid(row=2, column=0, sticky="w", pady=(8, 0))
        tk.Label(net_card, text="Deze tool werkt alleen met duidelijke toestemming: iemand opent bewust een diagnostic link. Niet via Telegram username.", bg=P.panel_2, fg=P.orange, font=self.font_small, wraplength=440, justify="left").grid(row=3, column=0, sticky="ew", pady=(8, 0))

        db_card = self._tools_card(content, "Database + logs quick tools", 2, 0)
        db_btns = tk.Frame(db_card, bg=P.panel_2)
        db_btns.grid(row=0, column=0, sticky="ew")
        self._llm_button(db_btns, "DB quick health", self._tools_db_health, primary=True).pack(side="left", padx=(0, 8))
        self._llm_button(db_btns, "Latest app logs", self._tools_latest_logs).pack(side="left", padx=(0, 8))
        self._llm_button(db_btns, "Open Logs page", self._show_logs_page).pack(side="left")
        tk.Label(db_card, text="Snelle checks zonder omwegen naar Database Manager.", bg=P.panel_2, fg=P.muted_2, font=self.font_small, wraplength=440, justify="left").grid(row=1, column=0, sticky="ew", pady=(8, 0))

        out_card = self._tools_card(content, "Output", 2, 1)
        self.tools_output_text = tk.Text(out_card, height=18, bg=P.panel, fg=P.text, relief="flat", font=("Consolas", 10), padx=10, pady=10, wrap="word")
        self.tools_output_text.grid(row=0, column=0, sticky="nsew")
        out_card.grid_rowconfigure(0, weight=1)

    def _tools_card(self, parent: tk.Widget, title: str, row: int, column: int) -> tk.Frame:
        outer = tk.Frame(parent, bg=P.panel_2, padx=14, pady=14, highlightbackground=P.border, highlightthickness=1)
        outer.grid(row=row, column=column, sticky="nsew", padx=8, pady=8)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=1)
        tk.Label(outer, text=title, bg=P.panel_2, fg=P.gold, font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))
        body = tk.Frame(outer, bg=P.panel_2)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        return body

    def _tools_refresh_output(self, text: str) -> None:
        if self.tools_output_text is None:
            return
        self._set_text_widget(self.tools_output_text, text)

    def _tools_run_threaded(self, label: str, fn: Callable[[], str]) -> None:
        self._tools_refresh_output(f"{label}... bezig")
        self._emit_activity(label, "STEP")
        def worker() -> None:
            try:
                output = fn()
            except Exception as exc:
                output = f"{label} mislukt: {type(exc).__name__}: {exc}"
            self.root.after(0, lambda: self._tools_refresh_output(output))
        threading.Thread(target=worker, daemon=True).start()

    def _tools_normalize_usernames(self) -> None:
        raw = self.tools_username_var.get() if self.tools_username_var else ""
        names = normalize_username_list(raw)
        self._tools_refresh_output("Normalized usernames:\n" + ("\n".join(names) if names else "Geen geldige usernames gevonden."))

    def _tools_test_telegram_token(self) -> None:
        cfg = load_telegram_runtime_config(self.settings)
        self._tools_run_threaded("Telegram token test", lambda: test_telegram_token(cfg.token))

    def _tools_show_telegram_settings(self) -> None:
        cfg = load_telegram_runtime_config(self.settings)
        lines = [
            "TELEGRAM RUNTIME SETTINGS",
            f"enabled: {cfg.enabled}",
            f"allow_all: {cfg.allow_all}",
            f"auto_start: {cfg.auto_start}",
            f"owner_usernames: {', '.join('@' + u for u in parse_owner_usernames(cfg.owner_usernames)) or '-'}",
            f"legacy_owner_ids: {', '.join(map(str, parse_owner_ids(cfg.owner_ids))) or '-'}",
            f"token_present: {bool(cfg.token)}",
            f"updated_at: {cfg.updated_at}",
        ]
        self._tools_refresh_output("\n".join(lines))

    def _tools_check_url(self) -> None:
        url = self.tools_url_var.get() if self.tools_url_var else ""
        self._tools_run_threaded("URL check", lambda: validate_url(url).to_text())

    def _tools_research_url_check(self) -> None:
        url = self.tools_url_var.get() if self.tools_url_var else ""
        def run() -> str:
            result = validate_url(url)
            advice = []
            if result.ok and result.is_document:
                advice.append("Advies: geschikt als documents/e-books bron. Downloaden/lezen is logisch.")
            elif result.ok:
                advice.append("Advies: gebruik als crawl/source pagina; niet automatisch opslaan als document.")
            else:
                advice.append("Advies: check URL, blokkade of internetverbinding.")
            return result.to_text() + "\n\n" + "\n".join(advice)
        self._tools_run_threaded("Research URL check", run)

    def _tools_public_ip_check(self) -> None:
        self._tools_run_threaded("Public IP self-check", get_public_ip)

    def _tools_start_consent_diagnostic(self) -> None:
        try:
            port = int(self.tools_diag_port_var.get() if self.tools_diag_port_var else 8787)
            if self.consent_diag_server is not None:
                self.consent_diag_server.stop()
            self.consent_diag_server = ConsentDiagnosticServer(self.settings.root / "data" / "diagnostics", port=port)
            url = self.consent_diag_server.start()
            self._tools_refresh_output(
                "Consent diagnostic server gestart.\n\n"
                f"Link: {url}\n\n"
                "De andere persoon moet deze link bewust openen. De pagina meldt duidelijk welke data wordt gemeten. "
                "Voor mensen buiten je netwerk heb je mogelijk port-forwarding/VPN-tunnel nodig."
            )
        except Exception as exc:
            self._tools_refresh_output(f"Consent diagnostic starten mislukt: {type(exc).__name__}: {exc}")

    def _tools_stop_consent_diagnostic(self) -> None:
        if self.consent_diag_server is not None:
            self.consent_diag_server.stop()
            self.consent_diag_server = None
        self._tools_refresh_output("Consent diagnostic server gestopt.")

    def _tools_view_consent_results(self) -> None:
        path = self.settings.root / "data" / "diagnostics" / "consent_diagnostics.jsonl"
        self._tools_refresh_output(read_diagnostic_records(path))

    def _tools_db_health(self) -> None:
        try:
            stats = self.router.db.stats()
            lines = ["DATABASE QUICK HEALTH", f"path: {self.settings.db_path}"]
            lines.extend(f"{k}: {v}" for k, v in stats.items())
            self._tools_refresh_output("\n".join(lines))
        except Exception as exc:
            self._tools_refresh_output(f"DB health mislukt: {type(exc).__name__}: {exc}")

    def _tools_latest_logs(self) -> None:
        try:
            lines = ["LATEST LOG FILES"]
            log_dir = self.settings.logs_dir
            files = sorted([p for p in log_dir.glob("*") if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=True)[:6]
            if not files:
                lines.append("Geen losse logfiles gevonden. Laatste DB errors hieronder.")
            for p in files:
                lines.append(f"\n--- {p.name} ---")
                lines.extend(p.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
            with self.router.db.connect() as conn:
                errs = conn.execute("SELECT created_at,error_type,message FROM errors ORDER BY id DESC LIMIT 12").fetchall()
            lines.append("\nLATEST DB ERRORS")
            for e in errs:
                lines.append(f"{e['created_at']} | {e['error_type']} | {e['message']}")
            self._tools_refresh_output("\n".join(lines))
        except Exception as exc:
            self._tools_refresh_output(f"Logs lezen mislukt: {type(exc).__name__}: {exc}")

    def _show_build_agent(self) -> None:
        self._show_panel_base("build_agent_panel", self._build_build_agent_panel, "Build Agent online")

    def _build_build_agent_panel(self) -> None:
        self.build_agent_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.build_agent_panel.grid_columnconfigure(0, weight=1)
        self.build_agent_panel.grid_rowconfigure(3, weight=1)
        self._build_simple_page_header(self.build_agent_panel, "⚒", "GUI BUILD AGENT", "Patch source safely, preview diffs, run checks, preview build en export zip zonder database/.env.")

        controls = tk.Frame(self.build_agent_panel, bg=P.panel, padx=16, pady=14, highlightbackground=P.border, highlightthickness=1)
        controls.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        controls.grid_columnconfigure(1, weight=1)
        self.build_agent_source_var = tk.StringVar(value="")
        tk.Label(controls, text="Source zip/projectmap", bg=P.panel, fg=P.muted, font=self.font_small).grid(row=0, column=0, sticky="w", padx=(0, 10))
        tk.Entry(controls, textvariable=self.build_agent_source_var, bg=P.panel_2, fg=P.text, insertbackground=P.text, relief="flat", font=self.font_body).grid(row=0, column=1, sticky="ew", ipady=8)
        self._llm_button(controls, "Browse zip", self._build_agent_browse_zip).grid(row=0, column=2, padx=(8, 0))
        self._llm_button(controls, "Browse folder", self._build_agent_browse_folder).grid(row=0, column=3, padx=(8, 0))

        prompt_card = tk.Frame(self.build_agent_panel, bg=P.panel, padx=16, pady=14, highlightbackground=P.border, highlightthickness=1)
        prompt_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        prompt_card.grid_columnconfigure(0, weight=1)
        tk.Label(prompt_card, text="Opdracht", bg=P.panel, fg=P.gold, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.build_agent_instruction_text = tk.Text(prompt_card, height=4, bg=P.panel_2, fg=P.text, insertbackground=P.text, relief="flat", font=self.font_body, wrap="word", padx=10, pady=8)
        self.build_agent_instruction_text.grid(row=1, column=0, sticky="ew")
        tk.Label(prompt_card, text="Manual File Target Mode (optioneel) — één pad per regel, bv. monaco_ai/gui.py. Laat leeg voor auto-selectie.", bg=P.panel, fg=P.muted, font=self.font_small).grid(row=2, column=0, sticky="w", pady=(10, 5))
        self.build_agent_targets_text = tk.Text(prompt_card, height=3, bg=P.panel_2, fg=P.text, insertbackground=P.text, relief="flat", font=("Consolas", 10), wrap="none", padx=10, pady=6)
        self.build_agent_targets_text.grid(row=3, column=0, sticky="ew")
        tk.Label(prompt_card, text="Context fix actief: bij 'context size exceeded' probeert hij automatisch small-context retry met 3-5 files/snippets.", bg=P.panel, fg=P.muted_2, font=self.font_small).grid(row=4, column=0, sticky="w", pady=(6, 0))
        action = tk.Frame(prompt_card, bg=P.panel)
        action.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        for label, cmd, primary in [
            ("Analyze only", self._build_agent_analyze, False),
            ("Apply Patch / Run", self._build_agent_run, True),
            ("Run compile checks", self._build_agent_run_checks, False),
            ("Run preview build", self._build_agent_run_preview, False),
            ("Stop preview", self._build_agent_stop_preview, False),
            ("Rollback", self._build_agent_rollback, False),
            ("Open workspace", self._build_agent_open_workspace, False),
            ("Export final zip", self._build_agent_export_final, True),
        ]:
            self._llm_button(action, label, cmd, primary=primary).pack(side="left", padx=(0, 7), pady=3)
        tk.Label(prompt_card, text="No Fake Success actief: zonder echte changed-files + diff + export-check toont hij geen succes.", bg=P.panel, fg=P.muted_2, font=self.font_small).grid(row=6, column=0, sticky="w", pady=(8, 0))

        notebook = tk.Frame(self.build_agent_panel, bg=P.bg)
        notebook.grid(row=3, column=0, sticky="nsew")
        notebook.grid_columnconfigure(0, weight=2)
        notebook.grid_columnconfigure(1, weight=2)
        notebook.grid_columnconfigure(2, weight=1)
        notebook.grid_rowconfigure(0, weight=1)
        self.build_agent_output_text = tk.Text(notebook, bg=P.panel, fg=P.text, relief="flat", font=("Consolas", 10), padx=12, pady=10, wrap="word")
        self.build_agent_output_text.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.build_agent_diff_text = tk.Text(notebook, bg="#050812", fg="#d9e0ff", relief="flat", font=("Consolas", 9), padx=12, pady=10, wrap="none")
        self.build_agent_diff_text.grid(row=0, column=1, sticky="nsew", padx=(0, 8))
        self.build_agent_changed_text = tk.Text(notebook, bg=P.panel, fg=P.text, relief="flat", font=("Consolas", 10), padx=12, pady=10, wrap="word")
        self.build_agent_changed_text.grid(row=0, column=2, sticky="nsew")
        self._build_agent_set_output("Build Agent ready. Selecteer een zip/projectmap en geef een duidelijke opdracht.")
        self._build_agent_set_diff("Diff preview verschijnt hier na echte wijzigingen.")
        self._build_agent_set_changed("Changed files/checks verschijnen hier.")

    def _build_agent_set_output(self, text: str) -> None:
        self._set_text_widget(self.build_agent_output_text, text)

    def _build_agent_set_changed(self, text: str) -> None:
        self._set_text_widget(self.build_agent_changed_text, text)

    def _build_agent_set_diff(self, text: str) -> None:
        self._set_text_widget(self.build_agent_diff_text, text)

    def _build_agent_browse_zip(self) -> None:
        path = filedialog.askopenfilename(title="Select source zip", filetypes=[("Zip files", "*.zip"), ("All files", "*.*")])
        if path and self.build_agent_source_var is not None:
            self.build_agent_source_var.set(path)

    def _build_agent_browse_folder(self) -> None:
        path = filedialog.askdirectory(title="Select project folder")
        if path and self.build_agent_source_var is not None:
            self.build_agent_source_var.set(path)

    def _build_agent_instruction(self) -> str:
        return self.build_agent_instruction_text.get("1.0", "end").strip() if self.build_agent_instruction_text is not None else ""

    def _build_agent_manual_targets(self) -> list[str]:
        if self.build_agent_targets_text is None:
            return []
        raw = self.build_agent_targets_text.get("1.0", "end").strip()
        return [line.strip() for line in raw.replace(",", "\n").splitlines() if line.strip()]

    def _build_agent_source(self) -> str:
        return self.build_agent_source_var.get().strip() if self.build_agent_source_var is not None else ""

    def _build_agent_analyze(self) -> None:
        self._build_agent_execute(analyze_only=True)

    def _build_agent_run(self) -> None:
        self._build_agent_execute(analyze_only=False)

    def _build_agent_execute(self, analyze_only: bool = False) -> None:
        source = self._build_agent_source()
        instruction = self._build_agent_instruction()
        manual_targets = self._build_agent_manual_targets()
        if not source:
            messagebox.showwarning("M0N4C0 Build Agent", "Kies eerst een source zip of projectmap.")
            return
        if not instruction:
            messagebox.showwarning("M0N4C0 Build Agent", "Typ eerst wat de Build Agent moet aanpassen/maken.")
            return
        self._build_agent_set_output(("Analyzing" if analyze_only else "Running build") + "... dit draait veilig in een tijdelijke workspace.")
        self._build_agent_set_diff("Bezig met diff voorbereiden...")
        self._build_agent_set_changed("Bezig...")
        self._emit_activity("Build Agent started.", "STEP")

        def worker() -> None:
            agent = BuildAgent(self.settings.root, self.router.llm, log=lambda msg: self._emit_activity(f"BuildAgent: {msg}", "INFO"))
            result = agent.analyze_only(source, instruction, manual_targets=manual_targets) if analyze_only else agent.run(source, instruction, manual_targets=manual_targets)
            self.build_agent_last_result = result
            self.root.after(0, lambda: self._build_agent_render_result(result))
        threading.Thread(target=worker, daemon=True).start()

    def _build_agent_render_result(self, result: BuildAgentResult) -> None:
        self._build_agent_set_output(result.report())
        self._build_agent_set_diff(result.diff_text() if hasattr(result, "diff_text") else "No diff available.")
        changed_lines = ["CHANGED FILES", *(result.changed_files or ["-"]), "", "CHECKS", *(result.checks or ["-"])]
        if result.output_zip:
            changed_lines.extend(["", "EXPORT ZIP", str(result.output_zip), f"Export verified: {result.export_verified}"])
        if result.error:
            changed_lines.extend(["", "ERROR", result.error])
        self._build_agent_set_changed("\n".join(changed_lines))
        self._emit_activity("Build Agent finished." if result.ok else "Build Agent finished with warnings/errors.", "OK" if result.ok else "WARN")
        if result.ok and result.output_zip:
            messagebox.showinfo("M0N4C0 Build Agent", f"Build klaar en geverifieerd:\n{result.output_zip}")
        elif result.error:
            messagebox.showwarning("M0N4C0 Build Agent", result.error[:900])

    def _build_agent_current_result_or_warn(self) -> BuildAgentResult | None:
        if not self.build_agent_last_result:
            messagebox.showwarning("M0N4C0 Build Agent", "Run eerst Analyze of Apply Patch.")
            return None
        return self.build_agent_last_result

    def _build_agent_run_checks(self) -> None:
        result = self._build_agent_current_result_or_warn()
        if not result:
            return
        def worker() -> None:
            agent = BuildAgent(self.settings.root, self.router.llm)
            checks = agent.run_checks_only(result.source_root)
            result.checks = checks
            self.root.after(0, lambda: self._build_agent_render_result(result))
        threading.Thread(target=worker, daemon=True).start()

    def _build_agent_run_preview(self) -> None:
        result = self._build_agent_current_result_or_warn()
        if not result:
            return
        if not result.source_root.exists():
            messagebox.showwarning("M0N4C0 Build Agent", "Workspace source bestaat niet meer.")
            return
        if not messagebox.askyesno("M0N4C0 Build Agent", "Run preview build starten vanuit tijdelijke workspace?\n\nDit voert code uit, maar raakt je echte projectmap niet."):
            return
        try:
            agent = BuildAgent(self.settings.root, self.router.llm)
            self.build_agent_preview_process = agent.run_preview(result.source_root)
            self._emit_activity("Preview build started from workspace.", "STEP")
            self._build_agent_set_changed("Preview build gestart. Gebruik Stop preview om te stoppen.\n\n" + self.build_agent_changed_text.get("1.0", "end") if self.build_agent_changed_text else "Preview build gestart.")
        except Exception as exc:
            messagebox.showerror("M0N4C0 Build Agent", f"Preview starten mislukt:\n{type(exc).__name__}: {exc}")

    def _build_agent_stop_preview(self) -> None:
        try:
            agent = BuildAgent(self.settings.root, self.router.llm)
            stopped = agent.stop_preview(self.build_agent_preview_process)
            self.build_agent_preview_process = None
            messagebox.showinfo("M0N4C0 Build Agent", "Preview gestopt." if stopped else "Geen actieve preview gevonden.")
        except Exception as exc:
            messagebox.showerror("M0N4C0 Build Agent", f"Stop preview mislukt: {exc}")

    def _build_agent_rollback(self) -> None:
        result = self._build_agent_current_result_or_warn()
        if not result:
            return
        if not messagebox.askyesno("M0N4C0 Build Agent", "Workspace terugzetten naar originele snapshot?"):
            return
        agent = BuildAgent(self.settings.root, self.router.llm)
        ok, msg = agent.rollback_workspace(result.workspace)
        messagebox.showinfo("M0N4C0 Build Agent", msg)
        if ok:
            result.changed_files = []
            result.diffs = {}
            result.output_zip = None
            result.ok = False
            result.summary = "Rollback uitgevoerd. Geen actieve wijzigingen."
            self._build_agent_render_result(result)

    def _build_agent_open_workspace(self) -> None:
        result = self._build_agent_current_result_or_warn()
        path = result.workspace if result else self.settings.root / "data" / "build_agent_workspaces"
        self._open_path(path)

    def _build_agent_open_export_folder(self) -> None:
        path = None
        if self.build_agent_last_result and self.build_agent_last_result.output_zip:
            path = self.build_agent_last_result.output_zip.parent
        else:
            path = self.settings.root / "data" / "build_agent_workspaces"
        self._open_path(path)

    def _build_agent_export_final(self) -> None:
        result = self._build_agent_current_result_or_warn()
        if not result:
            return
        if not result.changed_files:
            messagebox.showwarning("M0N4C0 Build Agent", "Geen echte wijzigingen gevonden. Export geblokkeerd door No Fake Success.")
            return
        try:
            agent = BuildAgent(self.settings.root, self.router.llm)
            out = agent.export_final_zip(result.source_root, expected_changed_files=[p for p in result.changed_files if not p.startswith("DELETED:")])
            result.output_zip = out
            result.export_verified = True
            result.ok = not any(c.startswith("FAIL") for c in result.checks)
            self._build_agent_render_result(result)
            messagebox.showinfo("M0N4C0 Build Agent", f"Final zip gemaakt:\n{out}")
        except Exception as exc:
            messagebox.showerror("M0N4C0 Build Agent", f"Export mislukt:\n{type(exc).__name__}: {exc}")

    def _open_path(self, path: Path) -> None:
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            messagebox.showinfo("M0N4C0", f"Pad:\n{path}\n\nOpenen lukte niet automatisch: {exc}")

    # ---------- Dependency Doctor / Benchmark / Error Explainer / Plugins ----------
    def _show_dependency_doctor(self) -> None:
        self._show_panel_base("dependency_panel", self._build_dependency_doctor_panel, "Dependency Doctor online")
        self._dependency_refresh()

    def _build_dependency_doctor_panel(self) -> None:
        self.dependency_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.dependency_panel.grid_columnconfigure(0, weight=1)
        self.dependency_panel.grid_rowconfigure(2, weight=1)
        self._build_simple_page_header(self.dependency_panel, "☑", "DEPENDENCY DOCTOR", "Check Python packages, Playwright, LM Studio en repair helpers.")
        bar = tk.Frame(self.dependency_panel, bg=P.panel, padx=14, pady=12, highlightbackground=P.border, highlightthickness=1)
        bar.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        self._llm_button(bar, "Refresh checks", self._dependency_refresh, primary=True).pack(side="left", padx=(0, 8))
        self._llm_button(bar, "Create START_SAFE_MODE.bat", self._dependency_create_safe_mode).pack(side="left", padx=(0, 8))
        self._llm_button(bar, "Source Cleaner preview", self._dependency_clean_preview).pack(side="left", padx=(0, 8))
        self._llm_button(bar, "Run Source Cleaner", self._dependency_clean_run).pack(side="left")
        self.dependency_text = tk.Text(self.dependency_panel, bg=P.panel, fg=P.text, relief="flat", font=("Consolas", 10), padx=12, pady=10, wrap="word")
        self.dependency_text.grid(row=2, column=0, sticky="nsew")

    def _dependency_refresh(self) -> None:
        self._set_text_widget(self.dependency_text, dependency_doctor(self.settings.root))

    def _dependency_create_safe_mode(self) -> None:
        self._set_text_widget(self.dependency_text, create_safe_mode_files(self.settings.root))

    def _dependency_clean_preview(self) -> None:
        text, _ = source_cleaner_preview(self.settings.root)
        self._set_text_widget(self.dependency_text, text)

    def _dependency_clean_run(self) -> None:
        if not messagebox.askyesno("M0N4C0 Source Cleaner", "Veilig opruimen uitvoeren? Database en .env blijven beschermd."):
            return
        self._set_text_widget(self.dependency_text, source_cleaner_run(self.settings.root))

    def _show_model_benchmark_page(self) -> None:
        self._show_panel_base("benchmark_panel", self._build_model_benchmark_panel, "Model Benchmark online")

    def _build_model_benchmark_panel(self) -> None:
        self.benchmark_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.benchmark_panel.grid_columnconfigure(0, weight=1)
        self.benchmark_panel.grid_rowconfigure(2, weight=1)
        self._build_simple_page_header(self.benchmark_panel, "◌", "MODEL BENCHMARK", "Vergelijk chat/code routing op snelheid en korte outputkwaliteit.")
        bar = tk.Frame(self.benchmark_panel, bg=P.panel, padx=14, pady=12, highlightbackground=P.border, highlightthickness=1)
        bar.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        self._llm_button(bar, "Run quick benchmark", self._benchmark_run, primary=True).pack(side="left")
        self.benchmark_text = tk.Text(self.benchmark_panel, bg=P.panel, fg=P.text, relief="flat", font=("Consolas", 10), padx=12, pady=10, wrap="word")
        self.benchmark_text.grid(row=2, column=0, sticky="nsew")
        self._set_text_widget(self.benchmark_text, "Klik op Run quick benchmark. LM Studio moet aan staan.")

    def _benchmark_run(self) -> None:
        self._set_text_widget(self.benchmark_text, "Benchmark draait...")
        def worker() -> None:
            result = basic_model_benchmark(self.router.llm)
            self.root.after(0, lambda: self._set_text_widget(self.benchmark_text, result))
        threading.Thread(target=worker, daemon=True).start()

    def _show_error_explainer(self) -> None:
        self._show_panel_base("error_panel", self._build_error_explainer_panel, "Error Explainer online")

    def _build_error_explainer_panel(self) -> None:
        self.error_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.error_panel.grid_columnconfigure(0, weight=1)
        self.error_panel.grid_rowconfigure(2, weight=1)
        self._build_simple_page_header(self.error_panel, "⚠", "SMART ERROR EXPLAINER", "Plak een traceback, krijg uitleg en Build Agent instructie.")
        top = tk.Frame(self.error_panel, bg=P.bg)
        top.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=1)
        self.error_input_text = tk.Text(top, height=10, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", font=("Consolas", 10), padx=12, pady=10, wrap="word")
        self.error_input_text.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.error_output_text = tk.Text(top, height=10, bg=P.panel, fg=P.text, relief="flat", font=("Consolas", 10), padx=12, pady=10, wrap="word")
        self.error_output_text.grid(row=0, column=1, sticky="nsew")
        bar = tk.Frame(self.error_panel, bg=P.panel, padx=14, pady=12, highlightbackground=P.border, highlightthickness=1)
        bar.grid(row=2, column=0, sticky="ew")
        self._llm_button(bar, "Explain error", self._error_explain, primary=True).pack(side="left", padx=(0, 8))
        self._llm_button(bar, "Send instruction to Build Agent", self._error_to_build_agent).pack(side="left")

    def _error_explain(self) -> None:
        text = self.error_input_text.get("1.0", "end").strip() if self.error_input_text else ""
        self._set_text_widget(self.error_output_text, smart_error_explain(text))

    def _error_to_build_agent(self) -> None:
        text = self.error_input_text.get("1.0", "end").strip() if self.error_input_text else ""
        if not text:
            messagebox.showwarning("M0N4C0 Error Explainer", "Plak eerst een error.")
            return
        self._show_build_agent()
        if self.build_agent_instruction_text is not None:
            self.build_agent_instruction_text.delete("1.0", "end")
            self.build_agent_instruction_text.insert("1.0", build_agent_instruction_from_error(text))

    def _show_plugin_manager(self) -> None:
        self._show_panel_base("plugin_panel", self._build_plugin_manager_panel, "Plugin Manager online")

    def _build_plugin_manager_panel(self) -> None:
        self.plugin_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.plugin_panel.grid_columnconfigure(0, weight=1)
        self._build_simple_page_header(self.plugin_panel, "▦", "PLUGIN MANAGER", "Zet modules aan/uit zodat M0N4C0 sneller en cleaner kan starten.")
        card = tk.Frame(self.plugin_panel, bg=P.panel, padx=18, pady=16, highlightbackground=P.border, highlightthickness=1)
        card.grid(row=1, column=0, sticky="ew", pady=(18, 12))
        card.grid_columnconfigure(0, weight=1)
        plugins = load_plugins(self.settings.root)
        self.plugin_vars = {}
        for i, (name, enabled) in enumerate(plugins.items()):
            var = tk.BooleanVar(value=enabled)
            self.plugin_vars[name] = var
            cb = tk.Checkbutton(card, text=name, variable=var, bg=P.panel, fg=P.text, selectcolor=P.panel_2, activebackground=P.panel, activeforeground=P.text, font=self.font_body, anchor="w")
            cb.grid(row=i, column=0, sticky="ew", pady=4)
        self._llm_button(card, "Save plugin settings", self._plugin_save, primary=True).grid(row=len(plugins)+1, column=0, sticky="w", pady=(12, 0))
        tk.Label(card, text="Instellingen worden opgeslagen in data/plugin_settings.json. Uitgeschakelde modules kunnen in latere builds lazy/disabled geladen worden.", bg=P.panel, fg=P.muted, font=self.font_small, wraplength=900, justify="left").grid(row=len(plugins)+2, column=0, sticky="w", pady=(8, 0))

    def _plugin_save(self) -> None:
        data = {name: bool(var.get()) for name, var in self.plugin_vars.items()}
        save_plugins(self.settings.root, data)
        messagebox.showinfo("M0N4C0 Plugin Manager", "Plugin settings opgeslagen.")


    # ---------- Worldclass Lab: Truth, automation, release and memory ----------
    def _show_worldclass_lab(self) -> None:
        self._show_panel_base("worldclass_panel", self._build_worldclass_lab_panel, "Worldclass Lab online")
        self._worldclass_refresh_overview()

    def _build_worldclass_lab_panel(self) -> None:
        self.worldclass_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.worldclass_panel.grid_columnconfigure(0, weight=1)
        self.worldclass_panel.grid_rowconfigure(4, weight=1)
        self._build_simple_page_header(self.worldclass_panel, "◆", "WORLDCLASS LAB", "Truth Engine, source rules, memory, scheduler, release tools en self-tests.")

        top = tk.Frame(self.worldclass_panel, bg=P.panel, padx=14, pady=12, highlightbackground=P.border, highlightthickness=1)
        top.grid(row=1, column=0, sticky="ew", pady=(18, 10))
        for label, cmd, primary in [
            ("Run Self-Test Lab", self._worldclass_run_self_test, True),
            ("Knowledge Timeline", self._worldclass_show_timeline, False),
            ("Evidence Vault", self._worldclass_show_evidence, False),
            ("Quality Reports", self._worldclass_show_quality_reports, False),
            ("Workflow Templates", self._worldclass_show_workflows, False),
            ("Permission Center", self._worldclass_show_permission_center, False),
            ("Create Clean Release Zip", self._worldclass_create_release_zip, False),
        ]:
            self._llm_button(top, label, cmd, primary=primary).pack(side="left", padx=(0, 8), pady=2)

        rules = tk.Frame(self.worldclass_panel, bg=P.panel_2, padx=14, pady=12, highlightbackground=P.border, highlightthickness=1)
        rules.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        rules.grid_columnconfigure(1, weight=1)
        rules.grid_columnconfigure(3, weight=1)
        tk.Label(rules, text="Source whitelist/blacklist", bg=P.panel_2, fg=P.text, font=self.font_body_bold).grid(row=0, column=0, sticky="w", columnspan=5, pady=(0, 8))
        self.source_rule_pattern_var = tk.StringVar(value="")
        self.source_rule_action_var = tk.StringVar(value="trust")
        tk.Label(rules, text="Pattern/domain", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=1, column=0, sticky="w")
        tk.Entry(rules, textvariable=self.source_rule_pattern_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", highlightbackground=P.border, highlightthickness=1).grid(row=1, column=1, sticky="ew", padx=(8, 12), ipady=6)
        tk.Label(rules, text="Action", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=1, column=2, sticky="w")
        opt = tk.OptionMenu(rules, self.source_rule_action_var, "trust", "boost", "block", "blacklist")
        self._style_option_menu(opt)
        opt.grid(row=1, column=3, sticky="ew", padx=(8, 12))
        self._llm_button(rules, "Save Rule", self._worldclass_save_source_rule, primary=True).grid(row=1, column=4, sticky="e")

        pm = tk.Frame(self.worldclass_panel, bg=P.panel_2, padx=14, pady=12, highlightbackground=P.border, highlightthickness=1)
        pm.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        pm.grid_columnconfigure(1, weight=1)
        pm.grid_columnconfigure(3, weight=1)
        pm.grid_columnconfigure(5, weight=2)
        tk.Label(pm, text="Project Memory + AI Job Scheduler", bg=P.panel_2, fg=P.text, font=self.font_body_bold).grid(row=0, column=0, sticky="w", columnspan=7, pady=(0, 8))
        self.project_key_var = tk.StringVar(value=self.settings.root.name)
        self.project_memory_key_var = tk.StringVar(value="note")
        self.project_memory_value_var = tk.StringVar(value="")
        tk.Label(pm, text="Project", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=1, column=0, sticky="w")
        tk.Entry(pm, textvariable=self.project_key_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat").grid(row=1, column=1, sticky="ew", padx=(6, 10), ipady=6)
        tk.Label(pm, text="Key", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=1, column=2, sticky="w")
        tk.Entry(pm, textvariable=self.project_memory_key_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat").grid(row=1, column=3, sticky="ew", padx=(6, 10), ipady=6)
        tk.Label(pm, text="Value", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=1, column=4, sticky="w")
        tk.Entry(pm, textvariable=self.project_memory_value_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat").grid(row=1, column=5, sticky="ew", padx=(6, 10), ipady=6)
        self._llm_button(pm, "Save Memory", self._worldclass_save_project_memory, primary=True).grid(row=1, column=6, sticky="e")

        self.scheduler_title_var = tk.StringVar(value="Weekly source fact-check")
        self.scheduler_type_var = tk.StringVar(value="fact_check")
        self.scheduler_cadence_var = tk.StringVar(value="weekly")
        tk.Label(pm, text="Job", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=2, column=0, sticky="w", pady=(10,0))
        tk.Entry(pm, textvariable=self.scheduler_title_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat").grid(row=2, column=1, sticky="ew", padx=(6,10), ipady=6, pady=(10,0))
        tk.Label(pm, text="Type", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=2, column=2, sticky="w", pady=(10,0))
        tk.Entry(pm, textvariable=self.scheduler_type_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat").grid(row=2, column=3, sticky="ew", padx=(6,10), ipady=6, pady=(10,0))
        tk.Label(pm, text="Cadence", bg=P.panel_2, fg=P.muted, font=self.font_small).grid(row=2, column=4, sticky="w", pady=(10,0))
        tk.Entry(pm, textvariable=self.scheduler_cadence_var, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat").grid(row=2, column=5, sticky="ew", padx=(6,10), ipady=6, pady=(10,0))
        self._llm_button(pm, "Schedule Job", self._worldclass_schedule_job).grid(row=2, column=6, sticky="e", pady=(10,0))

        self.worldclass_text = tk.Text(self.worldclass_panel, bg=P.panel, fg=P.text, relief="flat", font=("Consolas", 10), padx=12, pady=10, wrap="word")
        self.worldclass_text.grid(row=4, column=0, sticky="nsew")

    def _worldclass_refresh_overview(self) -> None:
        lines = ["M0N4C0 Worldclass Lab", "", "SOURCE RULES", source_rules_text(self.router.db), "", "PROJECT MEMORY", project_memory_text(self.router.db, limit=30), "", "SCHEDULED JOBS", list_scheduled_jobs(self.router.db), "", "WORKFLOW TEMPLATES", WorkflowTemplates.list_text()]
        self._set_text_widget(self.worldclass_text, "\n".join(lines))

    def _worldclass_run_self_test(self) -> None:
        self._set_text_widget(self.worldclass_text, SelfTestLab(self.settings, self.router.db, self.router).run())

    def _worldclass_show_timeline(self) -> None:
        self._set_text_widget(self.worldclass_text, summarize_knowledge_timeline(self.router.db, limit=120))

    def _worldclass_show_evidence(self) -> None:
        try:
            rows = EvidenceVault(self.router.db).list_recent(80)
            if not rows:
                self._set_text_widget(self.worldclass_text, "Evidence Vault is leeg. Live web-checks/research vullen dit automatisch.")
                return
            lines = ["Evidence Vault", ""]
            for r in rows:
                lines.append(f"#{r.get('id')} conf={r.get('confidence')} fresh={r.get('freshness')} {r.get('title')}")
                lines.append(f"  {r.get('source_url') or '-'}")
                lines.append(f"  {str(r.get('snippet') or '')[:260]}...")
            self._set_text_widget(self.worldclass_text, "\n".join(lines))
        except Exception as exc:
            self._set_text_widget(self.worldclass_text, f"Evidence Vault error: {type(exc).__name__}: {exc}")

    def _worldclass_show_quality_reports(self) -> None:
        try:
            rows = self.router.db.list_quality_reports(100)
            if not rows:
                self._set_text_widget(self.worldclass_text, "Nog geen conversation quality reports.")
                return
            lines = ["Conversation Quality Reports", ""]
            for r in rows:
                lines.append(f"#{r['id']} [{r['created_at']}] {r['platform']} confidence={r['confidence']} warnings={r['warnings_json']}")
                lines.append(f"Q: {str(r['question'])[:180]}")
                lines.append(f"A: {str(r['answer_preview'])[:220]}...")
            self._set_text_widget(self.worldclass_text, "\n".join(lines))
        except Exception as exc:
            self._set_text_widget(self.worldclass_text, f"Quality reports error: {type(exc).__name__}: {exc}")

    def _worldclass_show_workflows(self) -> None:
        self._set_text_widget(self.worldclass_text, "Workflow Templates / One-Click Missions\n\n" + WorkflowTemplates.list_text())

    def _worldclass_save_source_rule(self) -> None:
        pattern = self.source_rule_pattern_var.get().strip() if self.source_rule_pattern_var else ""
        action = self.source_rule_action_var.get().strip() if self.source_rule_action_var else "trust"
        if not pattern:
            messagebox.showwarning("M0N4C0 Source Rules", "Vul eerst een domein/pattern in.")
            return
        rid = upsert_source_rule(self.router.db, pattern, action)
        self._worldclass_refresh_overview()
        messagebox.showinfo("M0N4C0 Source Rules", f"Rule opgeslagen: #{rid}")

    def _worldclass_save_project_memory(self) -> None:
        project = self.project_key_var.get().strip() if self.project_key_var else self.settings.root.name
        key = self.project_memory_key_var.get().strip() if self.project_memory_key_var else "note"
        value = self.project_memory_value_var.get().strip() if self.project_memory_value_var else ""
        if not value:
            messagebox.showwarning("M0N4C0 Project Memory", "Vul eerst een waarde in.")
            return
        mid = upsert_project_memory(self.router.db, project, key, value)
        self._worldclass_refresh_overview()
        messagebox.showinfo("M0N4C0 Project Memory", f"Project memory opgeslagen: #{mid}")

    def _worldclass_schedule_job(self) -> None:
        title = self.scheduler_title_var.get().strip() if self.scheduler_title_var else "Scheduled job"
        typ = self.scheduler_type_var.get().strip() if self.scheduler_type_var else "task"
        cadence = self.scheduler_cadence_var.get().strip() if self.scheduler_cadence_var else "manual"
        jid = schedule_job(self.router.db, title, typ, cadence, enabled=True)
        self._worldclass_refresh_overview()
        messagebox.showinfo("M0N4C0 AI Job Scheduler", f"Job ingepland: #{jid}")

    def _worldclass_create_release_zip(self) -> None:
        try:
            out = ReleaseManager(self.settings.root).clean_zip()
            try:
                self.router.db.add_release_history("manual-clean-release", "Clean release zip gemaakt vanuit Worldclass Lab", str(out), {})
            except Exception:
                pass
            self._set_text_widget(self.worldclass_text, f"Clean release zip gemaakt:\n{out}\n\nDatabase, .env, pycache, backups en oude zips zijn uitgesloten.")
            messagebox.showinfo("M0N4C0 Release Manager", f"Release zip gemaakt:\n{out}")
        except Exception as exc:
            messagebox.showerror("M0N4C0 Release Manager", f"Release zip maken mislukt:\n{type(exc).__name__}: {exc}")


    def _worldclass_show_permission_center(self) -> None:
        defaults = {
            "internet": bool(self.settings.internet_enabled),
            "external_processes": True,
            "build_preview_run": True,
            "database_wipe": True,
            "source_downloads": True,
            "telegram_responses": bool(self.settings.telegram_enabled),
        }
        saved = self.router.db.get_app_setting("permission_safety_center", defaults) or defaults
        defaults.update(saved if isinstance(saved, dict) else {})
        lines = ["Permission & Safety Center", "", "Deze settings worden opgeslagen in app_settings.permission_safety_center.", "Modules kunnen deze permissies gebruiken voordat ze riskante acties uitvoeren.", ""]
        for key, val in defaults.items():
            lines.append(f"{'ON ' if val else 'OFF'} {key}")
        lines.extend(["", "Klik één van deze knoppen via Command Center command:", "permission toggle internet", "permission toggle external_processes", "permission toggle build_preview_run", "permission toggle database_wipe", "permission toggle source_downloads"])
        self._set_text_widget(self.worldclass_text, "\n".join(lines))

    def _worldclass_toggle_permission(self, key: str) -> None:
        data = self.router.db.get_app_setting("permission_safety_center", {}) or {}
        if not isinstance(data, dict):
            data = {}
        data[key] = not bool(data.get(key, True))
        self.router.db.set_app_setting("permission_safety_center", data)
        self._worldclass_show_permission_center()

    def _open_command_center(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("M0N4C0 Command Center")
        win.configure(bg=P.bg)
        win.geometry("820x520")
        win.transient(self.root)
        win.grab_set()
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(2, weight=1)
        tk.Label(win, text="COMMAND CENTER / GLOBAL SEARCH", bg=P.bg, fg=P.gold, font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 8))
        qvar = tk.StringVar(value="")
        entry = tk.Entry(win, textvariable=qvar, bg=P.panel, fg=P.text, insertbackground=P.text, relief="flat", font=("Segoe UI", 13), highlightbackground=P.border, highlightthickness=1)
        entry.grid(row=1, column=0, sticky="ew", padx=18, ipady=10)
        box = tk.Listbox(win, bg=P.panel, fg=P.text, selectbackground=P.purple_dark, selectforeground=P.text, relief="flat", font=("Consolas", 11), activestyle="none")
        box.grid(row=2, column=0, sticky="nsew", padx=18, pady=14)
        results: list[tuple[str, Callable[[], None]]] = []
        pages: list[tuple[str, Callable[[], None]]] = [
            ("Live Feed", self._show_live_feed_page), ("LLM Models", self._show_llm_models), ("Personality", self._show_personality),
            ("Brain Nodes", self._show_brain_nodes), ("Local Database", self._show_database_manager), ("Research", self._show_research),
            ("Mission Control", self._show_mission_control), ("Idle Learning", self._show_idle_learning), ("Memory", self._show_memory_manager),
            ("Tools", self._show_tools_page), ("Worldclass Lab", self._show_worldclass_lab), ("Build Agent", self._show_build_agent),
            ("Dependency Doctor", self._show_dependency_doctor), ("Model Benchmark", self._show_model_benchmark_page),
            ("Error Explainer", self._show_error_explainer), ("Plugin Manager", self._show_plugin_manager), ("Telegram", self._show_telegram_manager),
            ("Performance", self._show_performance_center), ("Logs", self._show_logs_page), ("Image generation", self._show_image_generation),
            ("Trading Dashboard", self._show_trading_dashboard),
        ]
        commands: list[tuple[str, Callable[[], None]]] = [
            ("Run Self-Test Lab", lambda: (self._show_worldclass_lab(), self._worldclass_run_self_test())),
            ("Show Knowledge Timeline", lambda: (self._show_worldclass_lab(), self._worldclass_show_timeline())),
            ("Show Evidence Vault", lambda: (self._show_worldclass_lab(), self._worldclass_show_evidence())),
            ("Show Quality Reports", lambda: (self._show_worldclass_lab(), self._worldclass_show_quality_reports())),
            ("Create Clean Release Zip", lambda: (self._show_worldclass_lab(), self._worldclass_create_release_zip())),
            ("permission toggle internet", lambda: (self._show_worldclass_lab(), self._worldclass_toggle_permission("internet"))),
            ("permission toggle external_processes", lambda: (self._show_worldclass_lab(), self._worldclass_toggle_permission("external_processes"))),
            ("permission toggle build_preview_run", lambda: (self._show_worldclass_lab(), self._worldclass_toggle_permission("build_preview_run"))),
            ("permission toggle database_wipe", lambda: (self._show_worldclass_lab(), self._worldclass_toggle_permission("database_wipe"))),
            ("permission toggle source_downloads", lambda: (self._show_worldclass_lab(), self._worldclass_toggle_permission("source_downloads"))),
            ("Refresh Database", lambda: (self._show_database_manager(), self._db_refresh_tables())),
            ("Open Build Agent", self._show_build_agent),
            ("Safe Mode info", lambda: messagebox.showinfo("M0N4C0 Safe Mode", "Start met START_SAFE_MODE.bat of py -3.11 run_m0n4c0.py --gui --safe-mode")),
        ]
        def refresh(*_args: Any) -> None:
            nonlocal results
            query = qvar.get().lower().strip()
            combined = [("PAGE  " + name, action) for name, action in pages] + [("CMD   " + name, action) for name, action in commands]
            if query:
                combined = [(n, a) for n, a in combined if query in n.lower()]
            results = combined[:80]
            box.delete(0, "end")
            for name, _ in results:
                box.insert("end", name)
        def run_selected(_event: tk.Event | None = None) -> None:
            sel = box.curselection()
            if not sel:
                return
            _, action = results[int(sel[0])]
            win.destroy()
            action()
        qvar.trace_add("write", refresh)
        box.bind("<Double-Button-1>", run_selected)
        entry.bind("<Return>", lambda _e: (box.selection_set(0), run_selected()) if results else None)
        refresh()
        entry.focus_set()

    def _show_image_generation(self) -> None:
        self._show_panel_base("image_panel", self._build_image_generation_panel, "Image generation prepared")

    def _build_image_generation_panel(self) -> None:
        self.image_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.image_panel.grid_columnconfigure(0, weight=1)
        self._build_simple_page_header(self.image_panel, "✦", "IMAGE GENERATION", "ComfyUI-ready module. Later kan hier workflow/checkpoint/queue/gallery komen.")
        card = tk.Label(self.image_panel, text="ComfyUI wordt later gekoppeld als losse service op http://127.0.0.1:8188.\nDeze pagina is alvast netjes voorbereid zodat het menu niet opnieuw hoeft.", bg=P.panel, fg=P.text, justify="left", anchor="nw", padx=22, pady=22, font=self.font_body)
        card.grid(row=1, column=0, sticky="ew", pady=(18, 0))

    def _show_trading_dashboard(self) -> None:
        self._show_panel_base("trading_panel", self._build_trading_dashboard_panel, "Trading dashboard prepared")

    def _build_trading_dashboard_panel(self) -> None:
        self.trading_panel = tk.Frame(self.main_panel, bg=P.bg, padx=22, pady=20)
        self.trading_panel.grid_columnconfigure(0, weight=1)
        self._build_simple_page_header(self.trading_panel, "↗", "TRADING DASHBOARD", "Watchlists, marktdata, alerts en educatieve AI-analyse later op één plek.")
        card = tk.Label(self.trading_panel, text="Trading Dashboard is voorbereid als coming-soon module.\nLater: crypto/aandelen watchlist, nieuws, alerts, strategie-notities en aparte Trading Model prompt.\nLet op: analyse/educatie, geen financieel advies.", bg=P.panel, fg=P.text, justify="left", anchor="nw", padx=22, pady=22, font=self.font_body)
        card.grid(row=1, column=0, sticky="ew", pady=(18, 0))

    def _show_chat_view(self) -> None:
        self._hide_extra_panels()
        if self.brain_panel is not None:
            self.brain_panel.grid_remove()
        if self.personality_panel is not None:
            self.personality_panel.grid_remove()
        if self.llm_panel is not None:
            self.llm_panel.grid_remove()
        if self.research_panel is not None:
            self.research_panel.grid_remove()
        self.header.grid(row=0, column=0, sticky="ew")
        self.chat_holder.grid(row=1, column=0, sticky="nsew")
        self.input_footer.grid(row=2, column=0, sticky="ew", pady=(12, 24))
        self.current_view = "chat"
        self._set_status("Local GUI ready", P.success)
        self.input.focus_set()

    def _show_brain_nodes(self) -> None:
        self.current_view = "brain"
        self.header.grid_remove()
        self.chat_holder.grid_remove()
        self.input_footer.grid_remove()
        self._hide_extra_panels()
        if self.personality_panel is not None:
            self.personality_panel.grid_remove()
        if self.llm_panel is not None:
            self.llm_panel.grid_remove()
        if self.research_panel is not None:
            self.research_panel.grid_remove()
        if self.brain_panel is None:
            self._build_brain_panel()
        assert self.brain_panel is not None
        self.brain_panel.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self._set_status("Brain Nodes loading in background…", P.purple)
        self._write_brain_detail("Brain Nodes wordt op de achtergrond geladen zodat de GUI niet vastloopt…")
        self.root.after(80, lambda: threading.Thread(target=self._load_brain_graph_threadsafe, daemon=True).start())

    def _load_brain_graph_threadsafe(self) -> None:
        try:
            self.brain_graph = self.brain_builder.build(max_nodes=180)
            self.root.after(0, lambda: self._draw_brain_graph())
            self.root.after(0, lambda: self._set_status("Brain Nodes online", P.purple))
        except Exception as exc:
            self.root.after(0, lambda: self._write_brain_detail(f"Brain Nodes laden mislukt: {type(exc).__name__}: {exc}"))
            self.root.after(0, lambda: self._set_status("Brain Nodes error", P.danger))

    def _build_brain_panel(self) -> None:
        self.brain_panel = tk.Frame(self.main_panel, bg=P.bg, padx=28, pady=24)
        self.brain_panel.grid_columnconfigure(0, weight=1)
        self.brain_panel.grid_rowconfigure(2, weight=1)

        top = tk.Frame(self.brain_panel, bg=P.bg)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        avatar = tk.Label(top, text="☍", bg=P.bg, fg=P.purple, font=("Segoe UI Symbol", 34, "bold"), width=3)
        avatar.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 16))
        tk.Label(top, text="Brain Nodes", bg=P.bg, fg=P.text, font=("Segoe UI", 24, "bold")).grid(row=0, column=1, sticky="w")
        tk.Label(
            top,
            text="Obsidian-style map van M0N4C0 zijn lokale brein: kennis, memory, keywords en relaties.",
            bg=P.bg,
            fg=P.muted,
            font=("Segoe UI", 11),
        ).grid(row=1, column=1, sticky="w", pady=(4, 0))
        tk.Button(
            top,
            text="← Back to chat",
            command=self._show_chat_view,
            bg=P.panel_2,
            fg=P.text,
            activebackground=P.purple_dark,
            activeforeground=P.text,
            relief="flat",
            padx=15,
            pady=9,
            cursor="hand2",
        ).grid(row=0, column=2, rowspan=2, sticky="e")

        tools = tk.Frame(self.brain_panel, bg=P.bg, pady=14)
        tools.grid(row=1, column=0, sticky="ew")
        tools.grid_columnconfigure(1, weight=1)
        tk.Label(tools, text="Filter", bg=P.bg, fg=P.muted, font=self.font_small).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.brain_search = tk.Entry(
            tools,
            bg=P.panel,
            fg=P.text,
            insertbackground=P.text,
            relief="flat",
            font=self.font_body,
            highlightbackground=P.border,
            highlightthickness=1,
        )
        self.brain_search.grid(row=0, column=1, sticky="ew", ipady=9)
        self.brain_search.bind("<Return>", lambda _event: self._load_brain_graph())
        tk.Button(
            tools,
            text="Refresh",
            command=self._load_brain_graph,
            bg=P.purple_dark,
            fg=P.text,
            activebackground=P.purple,
            activeforeground=P.text,
            relief="flat",
            padx=16,
            pady=9,
            cursor="hand2",
        ).grid(row=0, column=2, sticky="e", padx=(12, 0))
        tk.Button(
            tools,
            text="Reset view",
            command=self._reset_brain_view,
            bg=P.panel_2,
            fg=P.text,
            activebackground=P.purple_dark,
            activeforeground=P.text,
            relief="flat",
            padx=16,
            pady=9,
            cursor="hand2",
        ).grid(row=0, column=3, sticky="e", padx=(10, 0))

        body = tk.Frame(self.brain_panel, bg=P.bg)
        body.grid(row=2, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, minsize=310, weight=0)
        body.grid_rowconfigure(0, weight=1)

        graph_card = tk.Frame(body, bg=P.panel, highlightbackground=P.border, highlightthickness=1)
        graph_card.grid(row=0, column=0, sticky="nsew")
        graph_card.grid_columnconfigure(0, weight=1)
        graph_card.grid_rowconfigure(0, weight=1)
        self.brain_canvas = tk.Canvas(graph_card, bg=P.panel, bd=0, highlightthickness=0, cursor="crosshair")
        self.brain_canvas.grid(row=0, column=0, sticky="nsew")
        self.brain_canvas.bind("<Configure>", lambda _event: self._draw_brain_graph(keep_positions=True))
        self.brain_canvas.bind("<MouseWheel>", self._brain_mousewheel)
        self.brain_canvas.bind("<ButtonPress-1>", self._brain_blank_click)
        self.brain_canvas.bind("<B1-Motion>", self._brain_pan_drag)
        self.brain_canvas.bind("<ButtonRelease-1>", self._brain_end_drag)

        details = tk.Frame(body, bg=P.panel_2, padx=18, pady=18, highlightbackground=P.border, highlightthickness=1)
        details.grid(row=0, column=1, sticky="nsew", padx=(16, 0))
        details.grid_columnconfigure(0, weight=1)
        tk.Label(details, text="Node Inspector", bg=P.panel_2, fg=P.gold, font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        self.brain_stats_label = tk.Label(details, text="", bg=P.panel_2, fg=P.muted, justify="left", font=self.font_small)
        self.brain_stats_label.grid(row=1, column=0, sticky="ew", pady=(12, 16))
        self.brain_detail_title = tk.Label(details, text="Hover over een node", bg=P.panel_2, fg=P.text, justify="left", font=self.font_body_bold, wraplength=270)
        self.brain_detail_title.grid(row=2, column=0, sticky="w")
        self.brain_detail_kind = tk.Label(details, text="", bg=P.panel_2, fg=P.purple, justify="left", font=self.font_small)
        self.brain_detail_kind.grid(row=3, column=0, sticky="w", pady=(3, 10))
        # Scrollable inspector body. This must be a Text widget, not a Label,
        # because _write_brain_detail() updates it with delete()/insert().
        inspector_body = tk.Frame(details, bg=P.panel_2)
        inspector_body.grid(row=4, column=0, sticky="nsew")
        inspector_body.grid_columnconfigure(0, weight=1)
        inspector_body.grid_rowconfigure(0, weight=1)
        details.grid_rowconfigure(4, weight=1)

        self.brain_detail_text = tk.Text(
            inspector_body,
            bg=P.panel_2,
            fg=P.muted,
            insertbackground=P.text,
            selectbackground=P.purple_dark,
            selectforeground=P.text,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            wrap="word",
            font=self.font_small,
            padx=0,
            pady=0,
            cursor="arrow",
        )
        self.brain_detail_scroll = tk.Scrollbar(inspector_body, orient="vertical", command=self.brain_detail_text.yview)
        self.brain_detail_text.configure(yscrollcommand=self.brain_detail_scroll.set)
        self.brain_detail_text.grid(row=0, column=0, sticky="nsew")
        self.brain_detail_scroll.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self._write_brain_detail(
            "Klik op Brain Nodes en M0N4C0 maakt van SQLite een visueel brein.\n\n"
            "• Hover voor snelle uitleg\n"
            "• Klik op een node voor volledige info\n"
            "• Sleep nodes om te ordenen\n"
            "• Sleep lege ruimte om over de map te bewegen\n"
            "• Scroll om te zoomen\n"
            "• Filter om onderwerpen te zoeken"
        )

    def _load_brain_graph(self) -> None:
        if self.brain_panel is None:
            return
        query = self.brain_search.get().strip() if hasattr(self, "brain_search") else ""
        self._emit_activity(f"Building Brain Graph from SQLite. filter='{query or 'all'}'", "STEP")
        self.brain_graph = self.brain_builder.build(query=query, limit=260, include_seed_if_empty=True)
        self.brain_positions.clear()
        self.brain_selected_node = None
        self.brain_hover_node = None
        self.brain_scale = 1.0
        self._update_brain_stats()
        self._draw_brain_graph(keep_positions=False)
        if self.brain_graph.seeded:
            self._set_status("Brain seeded / updated with expert knowledge packs", P.gold)
            self._emit_activity("Seed packs checked/added: football, general, markets.", "OK")
        else:
            self._set_status("Brain Nodes refreshed", P.purple)
        if self.brain_graph:
            self._emit_activity(f"Graph ready: {self.brain_graph.stats.get('nodes', 0)} nodes, {self.brain_graph.stats.get('edges', 0)} relations.", "OK")

    def _reset_brain_view(self) -> None:
        self.brain_positions.clear()
        self.brain_scale = 1.0
        self.brain_selected_node = None
        self.brain_hover_node = None
        self._draw_brain_graph(keep_positions=False)

    def _update_brain_stats(self) -> None:
        if not self.brain_graph:
            return
        s = self.brain_graph.stats
        seeded = "\nSeed: football + general + markets pack checked ✅" if self.brain_graph.seeded else ""
        self.brain_stats_label.configure(
            text=(
                f"Nodes: {s.get('nodes', 0)}\n"
                f"Relations: {s.get('edges', 0)}\n"
                f"Knowledge chunks: {s.get('knowledge_chunks', 0)}\n"
                f"Memory facts: {s.get('memory_facts', 0)}\n"
                f"Recent chat terms: {s.get('conversations', 0)}"
                f"{seeded}"
            )
        )

    def _draw_brain_graph(self, keep_positions: bool = True) -> None:
        if not getattr(self, "brain_canvas", None) or not self.brain_graph:
            return
        canvas = self.brain_canvas
        canvas.delete("all")
        self.brain_node_items.clear()
        self.brain_edge_items.clear()

        w = max(canvas.winfo_width(), 820)
        h = max(canvas.winfo_height(), 560)
        self._draw_brain_background(canvas, w, h)
        if not self.brain_graph.nodes:
            canvas.create_text(w / 2, h / 2, text="No brain data yet", fill=P.muted, font=self.font_body)
            return

        if not keep_positions or not self.brain_positions:
            self.brain_positions = self._calculate_brain_layout(w, h)

        # Edges first.
        node_lookup = {n.id: n for n in self.brain_graph.nodes}
        for edge in self.brain_graph.edges:
            if edge.source not in self.brain_positions or edge.target not in self.brain_positions:
                continue
            x1, y1 = self.brain_positions[edge.source]
            x2, y2 = self.brain_positions[edge.target]
            color = "#2d3447"
            if edge.source == self.brain_selected_node or edge.target == self.brain_selected_node:
                color = P.purple
            elif edge.source == self.brain_hover_node or edge.target == self.brain_hover_node:
                color = P.gold
            width = max(1, min(4, 0.7 + edge.weight * 0.6))
            item = canvas.create_line(x1, y1, x2, y2, fill=color, width=width, smooth=True, tags=("edge",))
            self.brain_edge_items.append((item, edge.source, edge.target))

        # Nodes on top.
        for node in self.brain_graph.nodes:
            if node.id not in self.brain_positions:
                continue
            x, y = self.brain_positions[node.id]
            r = self._node_radius(node)
            fill = NODE_COLORS.get(node.kind, P.text)
            outline = P.gold if node.id in {self.brain_selected_node, self.brain_hover_node} else "#0f1320"
            width = 3 if node.id in {self.brain_selected_node, self.brain_hover_node} else 1
            glow_r = r + 9
            glow = canvas.create_oval(x - glow_r, y - glow_r, x + glow_r, y + glow_r, fill="#151027", outline="", tags=("node", f"node:{node.id}"))
            oval = canvas.create_oval(x - r, y - r, x + r, y + r, fill=fill, outline=outline, width=width, tags=("node", f"node:{node.id}"))
            text_y = y + r + 13
            label = canvas.create_text(
                x,
                text_y,
                text=node.label,
                fill=P.text,
                font=("Segoe UI", 9, "bold" if node.kind in {"core", "topic", "memory"} else "normal"),
                width=120,
                justify="center",
                tags=("node_label", f"node:{node.id}"),
            )
            self.brain_node_items[node.id] = [glow, oval, label]
            tag = f"node:{node.id}"
            canvas.tag_bind(tag, "<Enter>", lambda _event, nid=node.id: self._brain_hover(nid))
            canvas.tag_bind(tag, "<Leave>", lambda _event: self._brain_unhover())
            canvas.tag_bind(tag, "<ButtonPress-1>", lambda event, nid=node.id: self._brain_start_drag(event, nid))
            canvas.tag_bind(tag, "<B1-Motion>", self._brain_drag)
            canvas.tag_bind(tag, "<ButtonRelease-1>", lambda event, nid=node.id: self._brain_select(nid))

        canvas.create_text(
            18,
            h - 24,
            anchor="w",
            text="Hover • click details • drag nodes • drag empty space to pan • scroll zoom • filter bovenin",
            fill=P.muted_2,
            font=("Segoe UI", 9),
        )

    def _draw_brain_background(self, canvas: tk.Canvas, w: int, h: int) -> None:
        # Subtle Obsidian-like grid and stars.
        step = 48
        for x in range(0, w, step):
            canvas.create_line(x, 0, x, h, fill="#0d1220", width=1)
        for y in range(0, h, step):
            canvas.create_line(0, y, w, y, fill="#0d1220", width=1)
        rnd = random.Random(42)
        for _ in range(85):
            x = rnd.randint(0, w)
            y = rnd.randint(0, h)
            canvas.create_oval(x, y, x + 1, y + 1, fill="#30374a", outline="")

    def _calculate_brain_layout(self, width: int, height: int) -> dict[str, tuple[float, float]]:
        assert self.brain_graph is not None
        nodes = self.brain_graph.nodes
        edges = self.brain_graph.edges
        positions: dict[str, list[float]] = {}
        rng = random.Random(1337)
        cx, cy = width / 2, height / 2
        radius = min(width, height) * 0.34

        by_id = {n.id: n for n in nodes}
        kind_rank = {
            "core": 0,
            "topic": 1,
            "memory": 2,
            "chunk": 3,
            "entity": 4,
            "keyword": 5,
            "conversation": 2,
            "conversation_term": 5,
        }
        sorted_nodes = sorted(nodes, key=lambda n: (kind_rank.get(n.kind, 6), -n.score, n.label))
        for i, node in enumerate(sorted_nodes):
            if node.kind == "core":
                positions[node.id] = [cx, cy]
                continue
            ring = kind_rank.get(node.kind, 5)
            ring_radius = min(radius * (0.33 + ring * 0.13), min(width, height) * 0.44)
            angle = (2 * math.pi * i / max(1, len(sorted_nodes))) + rng.uniform(-0.28, 0.28)
            positions[node.id] = [cx + math.cos(angle) * ring_radius, cy + math.sin(angle) * ring_radius]

        # Lightweight force pass: enough to make it feel graph-like without extra libs.
        node_ids = [n.id for n in nodes]
        for _ in range(130):
            disp = {nid: [0.0, 0.0] for nid in node_ids}
            for i, a in enumerate(node_ids):
                ax, ay = positions[a]
                for b in node_ids[i + 1 :]:
                    bx, by = positions[b]
                    dx, dy = ax - bx, ay - by
                    d2 = dx * dx + dy * dy + 0.01
                    force = 4200 / d2
                    dist = math.sqrt(d2)
                    ux, uy = dx / dist, dy / dist
                    disp[a][0] += ux * force
                    disp[a][1] += uy * force
                    disp[b][0] -= ux * force
                    disp[b][1] -= uy * force
            for edge in edges:
                if edge.source not in positions or edge.target not in positions:
                    continue
                sx, sy = positions[edge.source]
                tx, ty = positions[edge.target]
                dx, dy = tx - sx, ty - sy
                dist = math.sqrt(dx * dx + dy * dy) + 0.01
                target = 110 if by_id.get(edge.source, BrainNode("", "", "")).kind == "core" else 135
                force = (dist - target) * 0.018 * max(0.6, min(edge.weight, 3.0))
                ux, uy = dx / dist, dy / dist
                disp[edge.source][0] += ux * force
                disp[edge.source][1] += uy * force
                disp[edge.target][0] -= ux * force
                disp[edge.target][1] -= uy * force
            for nid in node_ids:
                if by_id[nid].kind == "core":
                    positions[nid] = [cx, cy]
                    continue
                positions[nid][0] += max(-7, min(7, disp[nid][0]))
                positions[nid][1] += max(-7, min(7, disp[nid][1]))
                positions[nid][0] = max(70, min(width - 70, positions[nid][0]))
                positions[nid][1] = max(70, min(height - 90, positions[nid][1]))

        if self.brain_scale != 1.0:
            for nid, (x, y) in list(positions.items()):
                positions[nid] = [cx + (x - cx) * self.brain_scale, cy + (y - cy) * self.brain_scale]
        return {k: (v[0], v[1]) for k, v in positions.items()}

    def _node_radius(self, node: BrainNode) -> float:
        base = 9
        if node.kind == "core":
            base = 23
        elif node.kind == "topic":
            base = 17
        elif node.kind in {"memory", "conversation"}:
            base = 14
        elif node.kind == "chunk":
            base = 12
        return min(28, base + math.log(max(node.score, 1), 2.2) * 2.3)

    def _node_by_id(self, node_id: str) -> BrainNode | None:
        if not self.brain_graph:
            return None
        for node in self.brain_graph.nodes:
            if node.id == node_id:
                return node
        return None

    def _brain_hover(self, node_id: str) -> None:
        # Moving between the glow/oval/text items of the same node can fire
        # multiple <Enter> events. Skip duplicate writes so the inspector stays
        # smooth with large graphs.
        if self.brain_hover_node == node_id:
            return
        self.brain_hover_node = node_id
        self._set_brain_detail(node_id, temporary=True)
        self._apply_brain_highlight()

    def _brain_unhover(self) -> None:
        self.brain_hover_node = None
        if self.brain_selected_node:
            self._set_brain_detail(self.brain_selected_node, temporary=False)
        self._apply_brain_highlight()

    def _brain_select(self, node_id: str) -> None:
        self.brain_selected_node = node_id
        self.brain_drag_node = None
        self._set_brain_detail(node_id, temporary=False)
        self._apply_brain_highlight()

    def _apply_brain_highlight(self) -> None:
        if not getattr(self, "brain_canvas", None):
            return
        canvas = self.brain_canvas
        active = {x for x in (self.brain_selected_node, self.brain_hover_node) if x}
        for item, src, tgt in self.brain_edge_items:
            if self.brain_selected_node and (src == self.brain_selected_node or tgt == self.brain_selected_node):
                canvas.itemconfigure(item, fill=P.purple, width=3)
            elif self.brain_hover_node and (src == self.brain_hover_node or tgt == self.brain_hover_node):
                canvas.itemconfigure(item, fill=P.gold, width=3)
            else:
                canvas.itemconfigure(item, fill="#2d3447", width=1)
        for nid, items in self.brain_node_items.items():
            if len(items) >= 2:
                canvas.itemconfigure(items[1], outline=P.gold if nid in active else "#0f1320", width=3 if nid in active else 1)

    def _set_brain_detail(self, node_id: str, temporary: bool = False) -> None:
        node = self._node_by_id(node_id)
        if node is None:
            return
        connected = []
        if self.brain_graph:
            for edge in self.brain_graph.edges:
                if edge.source == node_id:
                    other = self._node_by_id(edge.target)
                    if other:
                        connected.append(f"→ {edge.label}: {other.label}")
                elif edge.target == node_id:
                    other = self._node_by_id(edge.source)
                    if other:
                        connected.append(f"← {edge.label}: {other.label}")
        connected_text = "\n".join(connected[:18]) if connected else "Geen directe relaties zichtbaar in deze filter."
        marker = "hover" if temporary else "selected"
        self.brain_detail_title.configure(text=node.label)
        self.brain_detail_kind.configure(text=f"{marker.upper()} • {node.kind} • score {node.score:.1f} • sources {node.source_count}")
        body = self._brain_detail_body(node, connected_text, full=not temporary)
        self._write_brain_detail(body)

    def _write_brain_detail(self, text: str) -> None:
        widget = getattr(self, "brain_detail_text", None)
        if widget is None:
            return
        # New versions use tk.Text. This fallback keeps older/half-built widgets
        # from crashing if Tkinter reuses state while switching views.
        try:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
            widget.see("1.0")
            widget.configure(state="disabled")
        except (AttributeError, tk.TclError):
            try:
                widget.configure(text=text)
            except tk.TclError:
                pass

    def _brain_detail_body(self, node: BrainNode, connected_text: str, full: bool = True) -> str:
        lines: list[str] = []
        lines.append(node.preview or "Geen preview.")
        lines.append("")
        if node.metadata:
            meta_bits = []
            for key in ("topic", "title", "url", "created_at", "chunk_id"):
                value = node.metadata.get(key)
                if value:
                    meta_bits.append(f"{key}: {value}")
            if meta_bits:
                lines.append("METADATA")
                lines.extend(meta_bits)
                lines.append("")
        if full and node.kind == "chunk" and node.metadata.get("chunk_id"):
            chunk = self._load_chunk_detail(int(node.metadata["chunk_id"]))
            if chunk:
                if chunk.get("summary"):
                    lines.append("SUMMARY")
                    lines.append(str(chunk["summary"]))
                    lines.append("")
                if chunk.get("keywords"):
                    lines.append("KEYWORDS")
                    lines.append(", ".join(chunk["keywords"]))
                    lines.append("")
                lines.append("FULL LOCAL KNOWLEDGE")
                lines.append(str(chunk.get("content") or ""))
                lines.append("")
        elif full and node.kind == "topic":
            chunks = self._load_topic_detail(node.label)
            if chunks:
                lines.append("LOCAL CHUNKS IN THIS TOPIC")
                for idx, ch in enumerate(chunks, start=1):
                    summary = ch["summary"] or str(ch["content"])[:220]
                    lines.append(f"{idx}. {ch['title']} — {summary}")
                lines.append("")
        elif full and node.kind in {"memory", "entity"}:
            facts = self._load_memory_detail(node.label)
            if facts:
                lines.append("MATCHING MEMORY FACTS")
                for fact in facts:
                    lines.append(f"- {fact['subject']} {fact['predicate']} {fact['object']}  (confidence={fact['confidence']})")
                lines.append("")
        lines.append("RELATIONS")
        lines.append(connected_text)
        return "\n".join(lines)

    def _load_chunk_detail(self, chunk_id: int) -> dict[str, Any] | None:
        try:
            with self.router.db.connect() as conn:
                row = conn.execute("SELECT * FROM knowledge_chunks WHERE id=?", (chunk_id,)).fetchone()
                if not row:
                    return None
                keywords = []
                try:
                    keywords = list(__import__("json").loads(row["keywords_json"] or "[]"))
                except Exception:
                    keywords = []
                return {"title": row["title"], "topic": row["topic"], "summary": row["summary"], "content": row["content"], "keywords": keywords, "url": row["url"], "created_at": row["created_at"]}
        except Exception as exc:
            return {"content": f"Kon chunk niet laden: {type(exc).__name__}: {exc}"}

    def _load_topic_detail(self, topic: str) -> list[Any]:
        try:
            with self.router.db.connect() as conn:
                return conn.execute(
                    "SELECT title, summary, content FROM knowledge_chunks WHERE topic LIKE ? ORDER BY quality_score DESC, id DESC LIMIT 12",
                    (f"%{topic}%",),
                ).fetchall()
        except Exception:
            return []

    def _load_memory_detail(self, label: str) -> list[Any]:
        try:
            with self.router.db.connect() as conn:
                return conn.execute(
                    "SELECT subject,predicate,object,confidence FROM memory_facts WHERE subject LIKE ? OR object LIKE ? ORDER BY confidence DESC LIMIT 12",
                    (f"%{label}%", f"%{label}%"),
                ).fetchall()
        except Exception:
            return []

    def _brain_blank_click(self, event: tk.Event) -> None:
        current = self.brain_canvas.find_withtag("current") if getattr(self, "brain_canvas", None) else ()
        # Empty-space press starts map panning, like Obsidian canvas.
        if not current:
            self.brain_pan_active = True
            self.brain_pan_last = (event.x, event.y)
            self.brain_canvas.configure(cursor="fleur")
            self.brain_selected_node = None
            self.brain_detail_title.configure(text="Brain map")
            self.brain_detail_kind.configure(text="PAN MODE • empty space drag")
            self._write_brain_detail(
                "Je zit op lege ruimte. Houd links ingedrukt en sleep om over de brain map te bewegen.\n\n"
                "Klik op een node voor de volledige opgeslagen info. Nieuwe research/learning wordt na afloop automatisch zichtbaar via refresh of live als Brain Nodes open staat."
            )
            self._apply_brain_highlight()

    def _brain_start_drag(self, event: tk.Event, node_id: str) -> str:
        self.brain_pan_active = False
        self.brain_pan_last = None
        self.brain_drag_node = node_id
        x, y = self.brain_positions.get(node_id, (event.x, event.y))
        self.brain_drag_offset = (x - event.x, y - event.y)
        self.brain_canvas.configure(cursor="hand2")
        return "break"

    def _brain_drag(self, event: tk.Event) -> str:
        if not self.brain_drag_node:
            return "break"
        dx, dy = self.brain_drag_offset
        self.brain_positions[self.brain_drag_node] = (event.x + dx, event.y + dy)
        self._draw_brain_graph(keep_positions=True)
        return "break"

    def _brain_pan_drag(self, event: tk.Event) -> str:
        if not self.brain_pan_active or not self.brain_pan_last or self.brain_drag_node:
            return ""
        last_x, last_y = self.brain_pan_last
        dx, dy = event.x - last_x, event.y - last_y
        self.brain_pan_last = (event.x, event.y)
        if self.brain_positions:
            for nid, (x, y) in list(self.brain_positions.items()):
                self.brain_positions[nid] = (x + dx, y + dy)
            self._draw_brain_graph(keep_positions=True)
        return "break"

    def _brain_end_drag(self, _event: tk.Event) -> None:
        self.brain_drag_node = None
        self.brain_pan_active = False
        self.brain_pan_last = None
        if getattr(self, "brain_canvas", None):
            self.brain_canvas.configure(cursor="crosshair")

    def _brain_mousewheel(self, event: tk.Event) -> str:
        old_scale = self.brain_scale
        self.brain_scale = max(0.55, min(1.75, self.brain_scale + (0.08 if event.delta > 0 else -0.08)))
        if self.brain_positions and old_scale != self.brain_scale:
            canvas = self.brain_canvas
            cx, cy = canvas.winfo_width() / 2, canvas.winfo_height() / 2
            factor = self.brain_scale / old_scale
            for nid, (x, y) in list(self.brain_positions.items()):
                self.brain_positions[nid] = (cx + (x - cx) * factor, cy + (y - cy) * factor)
        self._draw_brain_graph(keep_positions=True)
        return "break"

    # ---------- chat widgets ----------
    def _add_message(self, role: str, text: str, replace_widget: tk.Widget | None = None) -> tk.Frame:
        if replace_widget is not None:
            replace_widget.destroy()

        row = tk.Frame(self.messages, bg=P.bg, pady=9)
        row.pack(fill="x", anchor="e" if role == "user" else "w")
        anchor = "e" if role == "user" else "w"
        bubble_color = P.bubble_user if role == "user" else P.bubble_ai
        border_color = P.bubble_user_border if role == "user" else P.border

        bubble = tk.Frame(row, bg=bubble_color, padx=18, pady=14, highlightbackground=border_color, highlightthickness=1)
        bubble.pack(anchor=anchor, padx=(240, 8) if role == "user" else (8, 240))

        if role == "assistant":
            top = tk.Frame(bubble, bg=bubble_color)
            top.pack(fill="x", pady=(0, 6))
            tk.Label(top, text="♛  M0N4C0", bg=bubble_color, fg=P.gold, font=self.font_small).pack(side="left")
        elif role == "system":
            tk.Label(bubble, text="SYSTEM", bg=bubble_color, fg=P.muted, font=self.font_small).pack(anchor="w", pady=(0, 6))

        label = tk.Label(
            bubble,
            text=text,
            bg=bubble_color,
            fg=P.text if role != "system" else P.muted,
            justify="left",
            anchor="w",
            wraplength=max(440, min(820, self.root.winfo_width() - 620)),
            font=self.font_body if role != "system" else self.font_small,
        )
        label.pack(fill="both")
        self.root.after(30, self._scroll_to_bottom)
        return row

    def _add_user_message(self, text: str) -> tk.Frame:
        return self._add_message("user", text)

    def _add_assistant_message(self, text: str, replace_widget: tk.Widget | None = None) -> tk.Frame:
        # GUI-safe continuation: if a local model returns a very large answer,
        # display it as multiple clean bubbles instead of one huge label that can
        # appear cut off mid-sentence on Windows/Tk. Telegram uses the same
        # splitter with a stricter limit.
        parts = split_telegram(str(text or ""), max_len=5200, add_part_numbers=True)
        first: tk.Frame | None = None
        current_replace = replace_widget
        for part in parts:
            row = self._add_message("assistant", part, replace_widget=current_replace)
            if first is None:
                first = row
            current_replace = None
        return first or self._add_message("assistant", "", replace_widget=replace_widget)

    def _add_system_message(self, text: str) -> tk.Frame:
        return self._add_message("system", text)

    # ---------- actions ----------
    def _send_quick(self, text: str) -> None:
        if self.current_view != "chat":
            self._show_chat_view()
        if not self.busy:
            self._start_request(text)

    def _send_current(self) -> None:
        text = self.input.get("1.0", "end").strip()
        if not text or self.busy:
            return
        self.input.delete("1.0", "end")
        self._start_request(text)

    def _enter_send(self, event: tk.Event) -> str:
        if event.state & 0x0001:  # Shift pressed; keep newline behavior.
            return ""
        self._send_current()
        return "break"

    def _start_request(self, text: str) -> None:
        model_role = (self.chat_model_role_var.get() if self.chat_model_role_var is not None else "Auto").strip().lower()
        self.busy = True
        self._set_status("M0N4C0 is thinking / researching…", P.purple)
        self.send_button.configure(state="disabled")
        self._emit_activity(f"Prompt received: {text}", "STEP")
        self._emit_activity(f"Model route selected: {model_role}", "INFO")
        self._emit_activity("Routing through CommandRouter + local SQLite memory.", "INFO")
        self._add_user_message(text)
        placeholder = self._add_assistant_message("Researching… ik draai dit lokaal door de bot-core.")
        thread = threading.Thread(target=self._worker, args=(text, placeholder, model_role), daemon=True)
        thread.start()

    def _worker(self, text: str, placeholder: tk.Widget, model_role: str = "auto") -> None:
        previous_role = getattr(self.settings, "llm_forced_model_role", "auto")
        try:
            self.settings.llm_forced_model_role = model_role if model_role in {"chat", "code", "coding", "research", "telegram", "image", "trading"} else "auto"
            if hasattr(self.router, "set_activity_callback"):
                self.router.set_activity_callback(lambda message, level="INFO": self._emit_activity(str(message), str(level)))
            self._emit_activity("Worker thread started.", "STEP")
            response = self.router.handle(text, self.ctx)
            self._emit_activity("Router finished. Response queued for GUI.", "OK")
            self.pending_queue.put(("ok", response, placeholder))
        except Exception as exc:  # router catches most errors, but GUI must never crash.
            self._emit_activity(f"Worker error: {type(exc).__name__}: {exc}", "ERR")
            self.pending_queue.put(("error", f"GUI/worker fout: {type(exc).__name__}: {exc}", placeholder))
        finally:
            self.settings.llm_forced_model_role = previous_role

    def _poll_queue(self) -> None:
        try:
            while True:
                level, message = self.activity_queue.get_nowait()
                self._append_activity_line(level, message)
        except queue.Empty:
            pass
        try:
            while True:
                kind, response, placeholder = self.pending_queue.get_nowait()
                if kind == "ok":
                    self._add_assistant_message(str(response), replace_widget=placeholder)
                    self._set_status("Local GUI ready", P.success)
                else:
                    self._add_assistant_message(str(response), replace_widget=placeholder)
                    self._set_status("Error opgeslagen / zichtbaar", P.danger)
                self.busy = False
                self.send_button.configure(state="normal")
                self._emit_activity("Conversation + answer stored in SQLite.", "OK")
                if self.current_view == "brain" and self.brain_panel is not None:
                    self._emit_activity("Brain Nodes open: refreshing graph from SQLite.", "STEP")
                    self._load_brain_graph()
                if self.current_view == "research" and self.research_panel is not None:
                    self._refresh_research_jobs()
        except queue.Empty:
            pass
        if self.current_view == "research" and self.research_panel is not None:
            try:
                self._refresh_research_jobs()
            except Exception:
                pass
        if self.current_view == "telegram" and self.telegram_panel is not None:
            try:
                self._telegram_refresh_status()
            except Exception:
                pass
        slow_views = {"research", "telegram", "database", "performance", "logs", "memory", "idle"}
        self.root.after(1200 if self.current_view in slow_views else 120, self._poll_queue)

    def _set_status(self, text: str, color: str) -> None:
        self.status_dot.configure(fg=color)
        self.status_text.configure(text=f" {text}")

    # ---------- scrolling/window ----------
    def _on_messages_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfig(self.messages_id, width=event.width)

    def _on_mousewheel(self, event: tk.Event) -> None:
        if self.current_view != "chat":
            return
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except tk.TclError:
            pass

    def _scroll_to_bottom(self) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.canvas.yview_moveto(1.0)

    def _on_close(self) -> None:
        self.root.destroy()


def run_gui(settings: Settings, router: CommandRouter, telegram_controller: Any | None = None, safe_mode: bool = False) -> None:
    MonacoGUI(settings, router, telegram_controller=telegram_controller, safe_mode=safe_mode).run()
