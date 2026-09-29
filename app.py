"""
app.py - Upgraded Local AI Application (Phase 1 + Phase 2 + Phase 3)
Features:
- Left/Right Bubble Cards with Gentle Tokyo Night Dark Palette.
- Token-by-token streaming with active socket Stop/Cancel (freeing compute).
- Interactive Copy Code, Copy Response, Edit & Resend, and Regenerate.
- Project & Conversation Rename / Delete with cascading database cleanup.
- Interactive Project Memory Manager modal & Database Backup, Restore, VACUUM.
- PHASE 3:
  1. Context Inspector ("Context used" / "🔍 Ngữ cảnh sử dụng"): Full XAI breakdown.
  2. Source Viewer Modal: Click RAG sources to inspect actual code with line highlights.
  3. Search Chat History: Keyword search across messages with quick jump.
  4. Export Conversation to Markdown (.md): Complete clean transcript export.
"""
import os
import sys
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog, scrolledtext

import config
from config import (
    DEFAULT_PROJECT_NAME,
    RECENT_MESSAGES_LIMIT,
    UI_MESSAGE_PAGE_SIZE,
    WEB_SEARCH_ENABLED,
    CHAT_MODEL
)
import database
import retrieval_service
import memory_service
import ollama_client
import web_service
import knowledge_service

WINDOW_TITLE = "Local AI — Project Assistant & Knowledge RAG"
WINDOW_SIZE = "1180x760"

# ============================================================
# DESIGN SYSTEM: GENTLE ON THE EYES DARK PALETTE & PURE WHITE TEXT
# ============================================================
THEME = {
    # Base background layers (gentle matte slate, avoids eye strain)
    "bg_root": "#13141f",         # Deep night matte backdrop
    "bg_chat": "#161724",         # Soft dark chat canvas
    "bg_sidebar": "#10111a",      # Slightly darker sidebar for visual depth
    "bg_header": "#171826",       # Top header banner
    "bg_card": "#1b1c2b",         # Floating card & sections
    "bg_input": "#181928",        # Input text box
    
    # Message Bubble Colors (Distinct Left/Right contrast)
    "bubble_user": "#282a3f",     # Soft twilight slate-blue for User (Right)
    "border_user": "#3c3f5c",     # Subtle border for user bubble
    
    "bubble_ai": "#1c1d2b",       # Gentle dark obsidian for AI (Left)
    "border_ai": "#2d2f44",       # Subtle border for AI bubble
    
    "bg_code": "#11121d",         # Deep syntax code block background
    "border_code": "#25273b",     # Code block divider
    
    # Dividers & Borders
    "border_subtle": "#252738",   # Subtle card divider
    "border_btn": "#32354c",      # Button border
    
    # Text Typography
    "text_white": "#ffffff",      # Pure crisp white for headings & messages
    "text_bright": "#f8fafc",     # High-contrast bright text
    "text_muted": "#94a3b8",      # Secondary silver-slate text
    "text_dim": "#64748b",        # Timestamps & captions
    
    # Accent Colors
    "primary": "#6366f1",         # Electric Indigo
    "primary_hover": "#4f46e5",   # Deeper Indigo
    "accent_blue": "#38bdf8",     # Cyan / Sky Blue
    "accent_indigo": "#a5b4fc",   # Soft Periwinkle for User
    "accent_emerald": "#34d399",  # Mint Emerald for AI
    "accent_amber": "#f59e0b",    # Amber for Regenerate / Warning
    
    # Utility Buttons
    "btn_dark": "#202234",        # Dark utility button
    "btn_dark_hover": "#2e314a",  # Dark utility hover
    
    # Status Indicators
    "status_ready": "#10b981",    # Emerald green
    "status_busy": "#f59e0b",     # Glowing amber
    "status_err": "#ef4444"       # Coral red
}

def add_hover_effect(widget, default_bg, hover_bg):
    """Add smooth mouse hover background transition to any Tkinter widget."""
    widget.bind("<Enter>", lambda e: widget.config(bg=hover_bg) if widget["state"] != tk.DISABLED else None)
    widget.bind("<Leave>", lambda e: widget.config(bg=default_bg) if widget["state"] != tk.DISABLED else None)


class LocalAIApp:
    def __init__(self, root):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.configure(bg=THEME["bg_root"])
        self.root.minsize(980, 680)

        # Set Application Icon
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app_icon.ico')
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        # Thread-safe UI update queue
        self.ui_queue = queue.Queue()
        self.root.after(50, self.process_ui_queue)

        # State tracking
        self.current_project_id = None
        self.current_conversation_id = None
        self.oldest_loaded_message_id = None
        self.is_processing = False
        self._is_selecting = False
        self.cancel_event = threading.Event()
        self._action_counter = 0

        # Initialize backend database
        database.init_db()

        # Build Layout
        self._setup_styles()
        self._build_header()
        self._build_main_layout()

        # Keyboard shortcuts
        self.root.bind("<Escape>", self._on_escape_pressed)

        # Load initial project & conversation
        self.load_initial_data()

    def _next_action_id(self):
        self._action_counter += 1
        return self._action_counter

    def _on_escape_pressed(self, event):
        """Allow user to quickly stop generation by pressing Escape."""
        if self.is_processing:
            self.cancel_generation()

    # ============================================================
    # STYLES & FONTS
    # ============================================================

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        # Treeview styling (Projects & Conversations)
        style.configure(
            "Treeview",
            background=THEME["bg_sidebar"],
            foreground=THEME["text_white"],
            fieldbackground=THEME["bg_sidebar"],
            font=("Segoe UI", 10),
            rowheight=32,
            borderwidth=0
        )
        style.map(
            "Treeview",
            background=[("selected", THEME["primary"])],
            foreground=[("selected", THEME["text_white"])]
        )
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background=THEME["bg_card"], foreground=THEME["text_white"])

    # ============================================================
    # HEADER SECTION
    # ============================================================

    def _build_header(self):
        self.header_frame = tk.Frame(self.root, bg=THEME["bg_header"], height=62, padx=20, pady=12)
        self.header_frame.pack(side=tk.TOP, fill=tk.X)
        self.header_frame.pack_propagate(False)

        # App Brand & Icon
        brand_frame = tk.Frame(self.header_frame, bg=THEME["bg_header"])
        brand_frame.pack(side=tk.LEFT, fill=tk.Y)

        app_icon = tk.Label(brand_frame, text="⚡", bg=THEME["bg_header"], fg=THEME["primary"], font=("Segoe UI Emoji", 16))
        app_icon.pack(side=tk.LEFT, padx=(0, 8))

        app_title = tk.Label(brand_frame, text="LOCAL AI", bg=THEME["bg_header"], fg=THEME["text_white"], font=("Segoe UI", 14, "bold"))
        app_title.pack(side=tk.LEFT)

        app_badge = tk.Label(brand_frame, text="v2.5", bg=THEME["primary"], fg=THEME["text_white"], font=("Segoe UI", 8, "bold"), padx=6, pady=1)
        app_badge.pack(side=tk.LEFT, padx=(8, 16))

        # Header Tools: Memory Manager & Database Maintenance
        tools_frame = tk.Frame(self.header_frame, bg=THEME["bg_header"])
        tools_frame.pack(side=tk.LEFT, fill=tk.Y)

        self.btn_memory_mgr = tk.Button(
            tools_frame,
            text="🧠 Bộ nhớ Dự án",
            command=self.open_memory_manager,
            bg=THEME["btn_dark"],
            fg=THEME["text_bright"],
            activebackground=THEME["btn_dark_hover"],
            activeforeground=THEME["text_white"],
            font=("Segoe UI", 8, "bold"),
            relief=tk.FLAT,
            bd=0,
            padx=10,
            pady=3,
            cursor="hand2"
        )
        self.btn_memory_mgr.pack(side=tk.LEFT, padx=(0, 6))
        add_hover_effect(self.btn_memory_mgr, THEME["btn_dark"], THEME["btn_dark_hover"])

        self.btn_db_mgr = tk.Button(
            tools_frame,
            text="💾 Backup & Bảo trì DB",
            command=self.open_database_maintenance,
            bg=THEME["btn_dark"],
            fg=THEME["text_bright"],
            activebackground=THEME["btn_dark_hover"],
            activeforeground=THEME["text_white"],
            font=("Segoe UI", 8, "bold"),
            relief=tk.FLAT,
            bd=0,
            padx=10,
            pady=3,
            cursor="hand2"
        )
        self.btn_db_mgr.pack(side=tk.LEFT)
        add_hover_effect(self.btn_db_mgr, THEME["btn_dark"], THEME["btn_dark_hover"])

        # Status & Model Badge (Right)
        status_frame = tk.Frame(self.header_frame, bg=THEME["bg_header"])
        status_frame.pack(side=tk.RIGHT, fill=tk.Y)

        self.status_dot = tk.Label(status_frame, text="●", bg=THEME["bg_header"], fg=THEME["status_ready"], font=("Segoe UI", 12))
        self.status_dot.pack(side=tk.LEFT, padx=(0, 6))

        self.status_label = tk.Label(status_frame, text="Sẵn sàng", bg=THEME["bg_header"], fg=THEME["text_muted"], font=("Segoe UI", 9, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=(0, 16))

        model_badge = tk.Label(
            status_frame,
            text=f"Model: {CHAT_MODEL}",
            bg=THEME["btn_dark"],
            fg=THEME["text_bright"],
            font=("Consolas", 9),
            padx=10,
            pady=4,
            relief=tk.FLAT
        )
        model_badge.pack(side=tk.LEFT)

    # ============================================================
    # MAIN WORKSPACE LAYOUT
    # ============================================================

    def _build_main_layout(self):
        divider = tk.Frame(self.root, bg=THEME["border_subtle"], height=1)
        divider.pack(side=tk.TOP, fill=tk.X)

        self.paned_window = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=THEME["bg_root"], bd=0, sashwidth=4, sashpad=0)
        self.paned_window.pack(fill=tk.BOTH, expand=True)

        # Left Column: Sidebar
        self.sidebar_frame = tk.Frame(self.paned_window, bg=THEME["bg_sidebar"], width=300)
        self.sidebar_frame.pack_propagate(False)
        self.paned_window.add(self.sidebar_frame)

        # Right Column: Main Chat & Knowledge
        self.content_frame = tk.Frame(self.paned_window, bg=THEME["bg_root"])
        self.paned_window.add(self.content_frame)

        self._build_sidebar_content()
        self._build_chat_workspace()

    # ============================================================
    # SIDEBAR: PROJECTS, CONVERSATIONS, SEARCH & KNOWLEDGE
    # ============================================================

    def _build_sidebar_content(self):
        # Section 1: Action Buttons
        actions_frame = tk.Frame(self.sidebar_frame, bg=THEME["bg_sidebar"], padx=14, pady=14)
        actions_frame.pack(fill=tk.X)

        self.btn_new_project = tk.Button(
            actions_frame,
            text="📁  Tạo Dự án Mới",
            command=self.on_new_project_dialog,
            bg=THEME["btn_dark"],
            fg=THEME["text_white"],
            activebackground=THEME["btn_dark_hover"],
            activeforeground=THEME["text_white"],
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            bd=0,
            pady=7,
            cursor="hand2"
        )
        self.btn_new_project.pack(fill=tk.X, pady=(0, 6))
        add_hover_effect(self.btn_new_project, THEME["btn_dark"], THEME["btn_dark_hover"])

        self.btn_new_convo = tk.Button(
            actions_frame,
            text="💬  Đoạn Chat Mới",
            command=self.on_new_conversation,
            bg=THEME["primary"],
            fg=THEME["text_white"],
            activebackground=THEME["primary_hover"],
            activeforeground=THEME["text_white"],
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            bd=0,
            pady=7,
            cursor="hand2"
        )
        self.btn_new_convo.pack(fill=tk.X)
        add_hover_effect(self.btn_new_convo, THEME["primary"], THEME["primary_hover"])

        # Section 2: Phase 3 Chat Search Bar
        search_frame = tk.Frame(self.sidebar_frame, bg=THEME["bg_sidebar"], padx=14, pady=4)
        search_frame.pack(fill=tk.X)

        search_inner = tk.Frame(search_frame, bg=THEME["bg_input"], highlightthickness=1, highlightbackground=THEME["border_subtle"])
        search_inner.pack(fill=tk.X)

        self.search_entry = tk.Entry(
            search_inner,
            bg=THEME["bg_input"],
            fg=THEME["text_white"],
            insertbackground=THEME["text_white"],
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            bd=0
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 4), pady=4)
        self.search_entry.insert(0, "🔍 Tìm kiếm tin nhắn...")
        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)
        self.search_entry.bind("<Return>", self._execute_chat_search)

        btn_run_search = tk.Label(search_inner, text="➔", bg=THEME["bg_input"], fg=THEME["text_muted"], font=("Segoe UI", 9, "bold"), cursor="hand2")
        btn_run_search.pack(side=tk.RIGHT, padx=(0, 6))
        btn_run_search.bind("<Button-1>", lambda e: self._execute_chat_search(None))

        # Section 3: Projects & Conversations Tree
        tree_container = tk.Frame(self.sidebar_frame, bg=THEME["bg_sidebar"], padx=14)
        tree_container.pack(fill=tk.BOTH, expand=True)

        tree_header = tk.Label(
            tree_container,
            text="DỰ ÁN & HỘI THOẠI (Chuột phải để sửa/xoá)",
            bg=THEME["bg_sidebar"],
            fg=THEME["text_dim"],
            font=("Segoe UI", 8, "bold")
        )
        tree_header.pack(anchor="w", pady=(4, 4))

        self.tree = ttk.Treeview(tree_container, selectmode="browse", show="tree")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Button-3>", self._on_tree_right_click)

        tree_scroll = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Context Menu for Project / Conversation Tree Items
        self.tree_proj_menu = tk.Menu(self.tree, tearoff=0, bg=THEME["bg_card"], fg=THEME["text_white"], activebackground=THEME["primary"], activeforeground=THEME["text_white"], bd=0)
        self.tree_proj_menu.add_command(label="✏️ Đổi tên dự án", command=self.on_rename_project)
        self.tree_proj_menu.add_command(label="🧠 Quản lý bộ nhớ dự án", command=self.open_memory_manager)
        self.tree_proj_menu.add_separator()
        self.tree_proj_menu.add_command(label="🗑️ Xoá dự án (kèm dữ liệu)", command=self.on_delete_project)

        self.tree_convo_menu = tk.Menu(self.tree, tearoff=0, bg=THEME["bg_card"], fg=THEME["text_white"], activebackground=THEME["primary"], activeforeground=THEME["text_white"], bd=0)
        self.tree_convo_menu.add_command(label="✏️ Đổi tên cuộc trò chuyện", command=self.on_rename_conversation)
        self.tree_convo_menu.add_command(label="📄 Xuất Markdown (.md)", command=self.on_export_chat)
        self.tree_convo_menu.add_separator()
        self.tree_convo_menu.add_command(label="🗑️ Xoá cuộc trò chuyện", command=self.on_delete_conversation)

        # Section 4: Project Knowledge & RAG Tools
        knowledge_frame = tk.Frame(self.sidebar_frame, bg=THEME["bg_card"], padx=12, pady=12, highlightthickness=1, highlightbackground=THEME["border_subtle"])
        knowledge_frame.pack(fill=tk.X, padx=12, pady=12)

        rag_title = tk.Label(knowledge_frame, text="📚 TÀI LIỆU DỰ ÁN (RAG)", bg=THEME["bg_card"], fg=THEME["text_bright"], font=("Segoe UI", 9, "bold"))
        rag_title.pack(anchor="w", pady=(0, 6))

        rag_btns_frame = tk.Frame(knowledge_frame, bg=THEME["bg_card"])
        rag_btns_frame.pack(fill=tk.X)

        self.btn_add_folder = tk.Button(
            rag_btns_frame,
            text="+ Thư mục",
            command=self.on_add_knowledge_folder,
            bg=THEME["btn_dark"],
            fg=THEME["text_white"],
            activebackground=THEME["btn_dark_hover"],
            activeforeground=THEME["text_white"],
            font=("Segoe UI", 8, "bold"),
            relief=tk.FLAT,
            bd=0,
            pady=4,
            cursor="hand2"
        )
        self.btn_add_folder.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        add_hover_effect(self.btn_add_folder, THEME["btn_dark"], THEME["btn_dark_hover"])

        self.btn_add_file = tk.Button(
            rag_btns_frame,
            text="+ Tệp tin",
            command=self.on_add_knowledge_file,
            bg=THEME["btn_dark"],
            fg=THEME["text_white"],
            activebackground=THEME["btn_dark_hover"],
            activeforeground=THEME["text_white"],
            font=("Segoe UI", 8, "bold"),
            relief=tk.FLAT,
            bd=0,
            pady=4,
            cursor="hand2"
        )
        self.btn_add_file.pack(side=tk.LEFT, fill=tk.X, expand=True)
        add_hover_effect(self.btn_add_file, THEME["btn_dark"], THEME["btn_dark_hover"])

        self.btn_reindex_knowledge = tk.Button(
            knowledge_frame,
            text="⚡ Index Knowledge (RAG)",
            command=self.on_reindex_knowledge,
            bg=THEME["btn_dark"],
            fg=THEME["text_bright"],
            activebackground=THEME["btn_dark_hover"],
            activeforeground=THEME["text_white"],
            font=("Segoe UI", 8, "bold"),
            relief=tk.FLAT,
            bd=0,
            pady=5,
            cursor="hand2"
        )
        self.btn_reindex_knowledge.pack(fill=tk.X, pady=(6, 4))
        add_hover_effect(self.btn_reindex_knowledge, THEME["btn_dark"], THEME["btn_dark_hover"])
        self.btn_reindex = self.btn_reindex_knowledge

        self.knowledge_stats_label = tk.Label(
            knowledge_frame,
            text="0 tài liệu | 0 chunks",
            bg=THEME["bg_card"],
            fg=THEME["text_dim"],
            font=("Segoe UI", 8)
        )
        self.knowledge_stats_label.pack(anchor="w")

    def _on_search_focus_in(self, event):
        if self.search_entry.get() == "🔍 Tìm kiếm tin nhắn...":
            self.search_entry.delete(0, tk.END)

    def _on_search_focus_out(self, event):
        if not self.search_entry.get().strip():
            self.search_entry.delete(0, tk.END)
            self.search_entry.insert(0, "🔍 Tìm kiếm tin nhắn...")

    def _on_tree_right_click(self, event):
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        self.tree.selection_set(item_id)
        if item_id.startswith("proj_"):
            self.tree_proj_menu.tk_popup(event.x_root, event.y_root)
        elif item_id.startswith("convo_"):
            self.tree_convo_menu.tk_popup(event.x_root, event.y_root)

    # ============================================================
    # CHAT WORKSPACE & CONVERSATION VIEW (BUBBLE CARDS)
    # ============================================================

    def _build_chat_workspace(self):
        self.chat_frame = tk.Frame(self.content_frame, bg=THEME["bg_root"])
        self.chat_frame.pack(fill=tk.BOTH, expand=True)

        # Chat Header: Title & Actions
        chat_header = tk.Frame(self.chat_frame, bg=THEME["bg_root"], padx=20, pady=12)
        chat_header.pack(fill=tk.X)

        self.title_label = tk.Label(
            chat_header,
            text="Chọn hoặc tạo một cuộc trò chuyện",
            bg=THEME["bg_root"],
            fg=THEME["text_white"],
            font=("Segoe UI", 13, "bold"),
            anchor="w"
        )
        self.title_label.pack(side=tk.LEFT)

        header_right = tk.Frame(chat_header, bg=THEME["bg_root"])
        header_right.pack(side=tk.RIGHT)

        self.btn_export = tk.Button(
            header_right,
            text="📄 Xuất Chat (.md)",
            command=self.on_export_chat,
            bg=THEME["btn_dark"],
            fg=THEME["text_bright"],
            activebackground=THEME["btn_dark_hover"],
            activeforeground=THEME["text_white"],
            font=("Segoe UI", 8, "bold"),
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=3,
            cursor="hand2"
        )
        self.btn_export.pack(side=tk.LEFT, padx=(0, 10))
        add_hover_effect(self.btn_export, THEME["btn_dark"], THEME["btn_dark_hover"])

        self.active_project_badge = tk.Label(
            header_right,
            text="📁 Dự án: Mặc định",
            bg=THEME["bg_card"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 9),
            padx=10,
            pady=4,
            relief=tk.FLAT
        )
        self.active_project_badge.pack(side=tk.LEFT)

        # Load older messages button (Keyset pagination)
        self.btn_load_older = tk.Button(
            self.chat_frame,
            text="⬆  Tải thêm tin nhắn cũ hơn",
            command=self.on_load_older_messages,
            bg=THEME["bg_card"],
            fg=THEME["text_muted"],
            activebackground=THEME["btn_dark"],
            activeforeground=THEME["text_white"],
            font=("Segoe UI", 8),
            relief=tk.FLAT,
            bd=0,
            pady=4,
            cursor="hand2"
        )
        self.btn_load_older.pack(fill=tk.X, padx=20, pady=(0, 6))
        add_hover_effect(self.btn_load_older, THEME["bg_card"], THEME["btn_dark"])

        # Main Chat Canvas / Text Box for Bubble Cards
        self.chat_box = scrolledtext.ScrolledText(
            self.chat_frame,
            wrap=tk.WORD,
            font=("Segoe UI", 10),
            bg=THEME["bg_chat"],
            fg=THEME["text_white"],
            insertbackground=THEME["text_white"],
            selectbackground=THEME["primary"],
            selectforeground=THEME["text_white"],
            padx=14,
            pady=14,
            relief=tk.FLAT,
            bd=0,
            state=tk.DISABLED
        )
        self.chat_box.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))

        # Alignment Tags for Bubble Windows
        self.chat_box.tag_configure("align_right", justify="right")
        self.chat_box.tag_configure("align_left", justify="left")
        self.chat_box.tag_configure("align_center", justify="center")

        # Right-Click Context Menu
        self.context_menu = tk.Menu(
            self.chat_box,
            tearoff=0,
            bg=THEME["bg_card"],
            fg=THEME["text_white"],
            activebackground=THEME["primary"],
            activeforeground=THEME["text_white"],
            bd=0
        )
        self.context_menu.add_command(label="📋 Sao chép phần chọn", command=self._copy_selection)
        self.context_menu.add_command(label="📋 Sao chép toàn bộ hội thoại", command=self._copy_all_chat)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🔄 Tạo lại câu trả lời (Regenerate)", command=self.on_regenerate)
        self.context_menu.add_command(label="📄 Xuất cuộc trò chuyện (.md)", command=self.on_export_chat)
        self.chat_box.bind("<Button-3>", self._show_context_menu)

        # Input Frame (Card Container)
        self.input_frame = tk.Frame(self.chat_frame, bg=THEME["bg_card"], padx=12, pady=10, highlightthickness=1, highlightbackground=THEME["border_subtle"])
        self.input_frame.pack(fill=tk.X, padx=18, pady=(0, 14))

        input_inner = tk.Frame(self.input_frame, bg=THEME["bg_input"], highlightthickness=1, highlightbackground=THEME["border_btn"])
        input_inner.pack(fill=tk.X)

        self.input_box = tk.Text(
            input_inner,
            height=3,
            font=("Segoe UI", 11),
            bg=THEME["bg_input"],
            fg=THEME["text_white"],
            insertbackground=THEME["text_white"],
            selectbackground=THEME["primary"],
            selectforeground=THEME["text_white"],
            padx=12,
            pady=10,
            relief=tk.FLAT,
            bd=0
        )
        self.input_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.input_box.bind("<Return>", self.on_enter_pressed)
        self.input_box.bind("<Shift-Return>", self.on_shift_enter)

        # Action Buttons Container (Send & Stop)
        self.btn_action_frame = tk.Frame(input_inner, bg=THEME["bg_input"])
        self.btn_action_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=8, pady=8)

        self.send_button = tk.Button(
            self.btn_action_frame,
            text="Gửi ➔",
            command=self.send_message,
            bg=THEME["primary"],
            fg=THEME["text_white"],
            activebackground=THEME["primary_hover"],
            activeforeground=THEME["text_white"],
            font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT,
            bd=0,
            width=8,
            cursor="hand2"
        )
        self.send_button.pack(fill=tk.BOTH, expand=True)
        add_hover_effect(self.send_button, THEME["primary"], THEME["primary_hover"])

        self.stop_button = tk.Button(
            self.btn_action_frame,
            text="Dừng ⏹",
            command=self.cancel_generation,
            bg=THEME["status_err"],
            fg=THEME["text_white"],
            activebackground="#dc2626",
            activeforeground=THEME["text_white"],
            font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT,
            bd=0,
            width=8,
            cursor="hand2"
        )
        add_hover_effect(self.stop_button, THEME["status_err"], "#dc2626")

        # Helper hint under input
        hint_label = tk.Label(
            self.input_frame,
            text="Mẹo: Nhấn Enter để gửi  •  Shift+Enter để xuống dòng  •  Escape để Dừng  •  Gõ '/nho <nội dung>' để lưu ghi nhớ dự án",
            bg=THEME["bg_card"],
            fg=THEME["text_dim"],
            font=("Segoe UI", 8),
            anchor="w"
        )
        hint_label.pack(anchor="w", pady=(6, 0))

    # ============================================================
    # CONTEXT MENU & CLIPBOARD HELPERS
    # ============================================================

    def _show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _copy_selection(self):
        try:
            selected_text = self.chat_box.get(tk.SEL_FIRST, tk.SEL_LAST)
            if selected_text:
                self.copy_to_clipboard(selected_text)
        except Exception:
            pass

    def _copy_all_chat(self):
        all_text = self.chat_box.get("1.0", tk.END).strip()
        if all_text:
            self.copy_to_clipboard(all_text)

    def copy_to_clipboard(self, text):
        """Thread-safe clipboard copy with subtle user notification."""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()
        self.set_ui_status("📋 Đã sao chép vào bộ nhớ tạm!", THEME["status_ready"])

    def edit_message(self, content):
        """Load a previous user prompt into input box for fast tweaking and resending."""
        self.input_box.delete("1.0", tk.END)
        self.input_box.insert(tk.END, content)
        self.input_box.focus_set()
        self.input_box.mark_set(tk.INSERT, tk.END)
        self.set_ui_status("✏️ Đã nạp lại câu hỏi vào ô soạn thảo. Bạn có thể sửa và gửi lại.", THEME["status_ready"])

    # ============================================================
    # MESSAGE BUBBLE RENDERING (RIGHT / LEFT ALIGNMENT)
    # ============================================================

    def _render_message_chunk(self, role, content, msg_id=None, append_at_top=False, context_meta=None):
        """
        Renders a message bubble card:
        - User message on the RIGHT in a twilight slate bubble.
        - AI message on the LEFT in a gentle obsidian bubble with code block support.
        """
        if role == "user":
            bubble_frame = self._create_user_bubble(content)
            tag_align = "align_right"
        else:
            bubble_frame = self._create_ai_bubble(content, context_meta=context_meta)
            tag_align = "align_left"

        insert_pos = "1.0" if append_at_top else tk.END

        # Add window to ScrolledText
        start_index = self.chat_box.index(insert_pos)
        self.chat_box.window_create(insert_pos, window=bubble_frame)
        self.chat_box.insert(insert_pos, "\n\n")
        end_index = self.chat_box.index(insert_pos)
        self.chat_box.tag_add(tag_align, start_index, end_index)

        return bubble_frame

    def _create_user_bubble(self, content):
        """Create a distinct, eye-friendly User bubble card on the RIGHT."""
        card = tk.Frame(
            self.chat_box,
            bg=THEME["bubble_user"],
            padx=14,
            pady=10,
            highlightthickness=1,
            highlightbackground=THEME["border_user"]
        )

        # Header Row
        hdr = tk.Frame(card, bg=THEME["bubble_user"])
        hdr.pack(fill=tk.X, pady=(0, 6))

        tk.Label(
            hdr,
            text="👤 Bạn",
            bg=THEME["bubble_user"],
            fg=THEME["accent_indigo"],
            font=("Segoe UI", 9, "bold")
        ).pack(side=tk.LEFT)

        btn_copy = tk.Label(
            hdr,
            text="[📋 Copy]",
            bg=THEME["bubble_user"],
            fg=THEME["text_muted"],
            font=("Segoe UI", 8),
            cursor="hand2"
        )
        btn_copy.pack(side=tk.RIGHT, padx=(4, 0))
        btn_copy.bind("<Button-1>", lambda e, c=content: self.copy_to_clipboard(c))

        btn_edit = tk.Label(
            hdr,
            text="[✏️ Sửa]",
            bg=THEME["bubble_user"],
            fg=THEME["accent_blue"],
            font=("Segoe UI", 8, "bold"),
            cursor="hand2"
        )
        btn_edit.pack(side=tk.RIGHT)
        btn_edit.bind("<Button-1>", lambda e, c=content: self.edit_message(c))

        # Content Text
        body = tk.Label(
            card,
            text=content,
            bg=THEME["bubble_user"],
            fg=THEME["text_white"],
            font=("Segoe UI", 10),
            justify=tk.LEFT,
            wraplength=640
        )
        body.pack(anchor="w")

        return card

    def _create_ai_bubble(self, content, is_streaming=False, context_meta=None):
        """Create a gentle, eye-friendly AI Assistant bubble card on the LEFT."""
        card = tk.Frame(
            self.chat_box,
            bg=THEME["bubble_ai"],
            padx=16,
            pady=12,
            highlightthickness=1,
            highlightbackground=THEME["border_ai"]
        )
        card._context_meta = context_meta

        # Header Row
        hdr = tk.Frame(card, bg=THEME["bubble_ai"])
        hdr.pack(fill=tk.X, pady=(0, 6))

        tk.Label(
            hdr,
            text="🤖 AI Assistant",
            bg=THEME["bubble_ai"],
            fg=THEME["accent_emerald"],
            font=("Segoe UI", 10, "bold")
        ).pack(side=tk.LEFT)

        # Check for web badge
        if "[Web Tra cứu]" in content or getattr(self, "_used_web_flag", False):
            badge = tk.Label(
                hdr,
                text="🌐 [Web Tra cứu]",
                bg=THEME["bubble_ai"],
                fg=THEME["accent_blue"],
                font=("Segoe UI", 8, "bold")
            )
            badge.pack(side=tk.LEFT, padx=(8, 0))

        content_container = tk.Frame(card, bg=THEME["bubble_ai"])
        content_container.pack(fill=tk.X)
        card._content_container = content_container

        # Render content parts or code blocks
        if not is_streaming and "```" in content:
            parts = content.split("```")
            for i, part in enumerate(parts):
                if i % 2 == 1:
                    code_lines = part.split("\n", 1)
                    lang_name = code_lines[0].strip() or "Code"
                    code_body = code_lines[1] if len(code_lines) > 1 else code_lines[0]
                    if lang_name.lower() in ('action_proposal', 'action', 'proposal', 'confirm_action'):
                        self._render_action_proposal_card(content_container, code_body)
                    else:
                        self._render_code_card(content_container, lang_name, code_body)
                else:
                    clean_text = part.strip()
                    if clean_text:
                        self._render_text_with_source_links(content_container, clean_text)
        else:
            if not is_streaming:
                self._render_text_with_source_links(content_container, content)
            else:
                lbl_body = tk.Label(
                    content_container,
                    text=content,
                    bg=THEME["bubble_ai"],
                    fg=THEME["text_bright"],
                    font=("Segoe UI", 10),
                    justify=tk.LEFT,
                    wraplength=700
                )
                lbl_body.pack(anchor="w")
                card._lbl_body = lbl_body

        # Action Footer
        if not is_streaming:
            footer = tk.Frame(card, bg=THEME["bubble_ai"])
            footer.pack(fill=tk.X, pady=(8, 0))

            btn_copy = tk.Label(
                footer,
                text="[📋 Sao chép]",
                bg=THEME["bubble_ai"],
                fg=THEME["accent_indigo"],
                font=("Segoe UI", 8, "bold"),
                cursor="hand2"
            )
            btn_copy.pack(side=tk.LEFT, padx=(0, 10))
            btn_copy.bind("<Button-1>", lambda e, c=content: self.copy_to_clipboard(c))

            btn_regen = tk.Label(
                footer,
                text="[🔄 Tạo lại]",
                bg=THEME["bubble_ai"],
                fg=THEME["accent_amber"],
                font=("Segoe UI", 8, "bold"),
                cursor="hand2"
            )
            btn_regen.pack(side=tk.LEFT, padx=(0, 10))
            btn_regen.bind("<Button-1>", lambda e: self.on_regenerate())

            # Phase 3: Context Inspector button
            btn_inspector = tk.Label(
                footer,
                text="[🔍 Ngữ cảnh sử dụng]",
                bg=THEME["bubble_ai"],
                fg=THEME["accent_blue"],
                font=("Segoe UI", 8, "bold"),
                cursor="hand2"
            )
            btn_inspector.pack(side=tk.LEFT)
            btn_inspector.bind("<Button-1>", lambda e, meta=card._context_meta: self.open_context_inspector(meta))

        return card

    def _render_text_with_source_links(self, parent, text_str):
        """Render text and make RAG source citations clickable to open Source Viewer."""
        # Check if text contains source citations like: - [path] — lines X–Y
        lines = text_str.split("\n")
        normal_buffer = []

        def flush_normal():
            if normal_buffer:
                chunk = "\n".join(normal_buffer)
                tk.Label(
                    parent,
                    text=chunk,
                    bg=THEME["bubble_ai"],
                    fg=THEME["text_bright"],
                    font=("Segoe UI", 10),
                    justify=tk.LEFT,
                    wraplength=700
                ).pack(anchor="w", pady=(0, 4))
                normal_buffer.clear()

        for line in lines:
            line_strip = line.strip()
            if line_strip.startswith("- [") and ("lines" in line_strip or "line" in line_strip):
                flush_normal()
                # Parse relative path and line numbers
                try:
                    rel_path = line_strip.split("[")[1].split("]")[0]
                    # Extract lines
                    after_bracket = line_strip.split("]")[1]
                    s_line, e_line = 1, 20
                    for token in after_bracket.replace("—", "-").replace("–", "-").split():
                        if "-" in token:
                            parts = token.split("-")
                            s_line = int("".join(filter(str.isdigit, parts[0])))
                            e_line = int("".join(filter(str.isdigit, parts[1])))
                            break

                    link_frame = tk.Frame(parent, bg=THEME["bubble_ai"])
                    link_frame.pack(anchor="w", pady=2)

                    tk.Label(link_frame, text="  📎 Nguồn: ", bg=THEME["bubble_ai"], fg=THEME["text_muted"], font=("Segoe UI", 9)).pack(side=tk.LEFT)
                    btn_link = tk.Label(
                        link_frame,
                        text=f"[{rel_path} — dòng {s_line}–{e_line}] (Click xem mã)",
                        bg=THEME["bubble_ai"],
                        fg=THEME["accent_blue"],
                        font=("Segoe UI", 9, "bold", "underline"),
                        cursor="hand2"
                    )
                    btn_link.pack(side=tk.LEFT)
                    btn_link.bind("<Button-1>", lambda e, rp=rel_path, sl=s_line, el=e_line: self.open_source_viewer(rp, sl, el))
                except Exception:
                    normal_buffer.append(line)
            else:
                normal_buffer.append(line)

        flush_normal()

    def _render_action_proposal_card(self, parent, code_body):
        """
        Render an interactive Action Confirmation Card with Cancel and Apply buttons.
        For critical, irreversible, or high-risk operations.
        """
        import json
        proposal = {}
        try:
            proposal = json.loads(code_body.strip())
        except Exception:
            for line in code_body.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k_c = k.strip().lower()
                    v_c = v.strip()
                    if any(x in k_c for x in ("tên", "title", "hành động")):
                        proposal["title"] = v_c
                    elif any(x in k_c for x in ("loại", "type")):
                        proposal["action_type"] = v_c
                    elif any(x in k_c for x in ("mục tiêu", "target", "đối tượng")):
                        proposal["target"] = v_c
                    elif any(x in k_c for x in ("lý do", "reason", "giải thích")):
                        proposal["reason"] = v_c
                    elif any(x in k_c for x in ("nguy cơ", "rủi ro", "risk")):
                        proposal["risk"] = v_c
                    elif any(x in k_c for x in ("lệnh", "payload")):
                        proposal["payload"] = v_c

        title = proposal.get("title", "Yêu cầu thực thi hành động quan trọng")
        action_type = proposal.get("action_type", "critical_operation")
        target = proposal.get("target", "Hệ thống / Dự án")
        reason = proposal.get("reason", "Cần thực hiện thao tác này để tiếp tục.")
        risk = proposal.get("risk", "Thao tác có rủi ro cao hoặc không thể hoàn tác!")
        payload = proposal.get("payload", "")

        card = tk.Frame(
            parent,
            bg="#211825",
            padx=14,
            pady=12,
            highlightthickness=1,
            highlightbackground="#f59e0b"
        )
        card.pack(fill=tk.X, pady=8)

        # Header Badge
        hdr_frame = tk.Frame(card, bg="#211825")
        hdr_frame.pack(fill=tk.X, pady=(0, 6))

        tk.Label(
            hdr_frame,
            text="⚠️ YÊU CẦU XÁC NHẬN HÀNH ĐỘNG (ACTION APPROVAL REQUIRED)",
            bg="#3b251a",
            fg="#fbbf24",
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=3
        ).pack(side=tk.LEFT)

        tk.Label(
            hdr_frame,
            text=f"[{action_type.upper()}]",
            bg="#211825",
            fg="#94a3b8",
            font=("Consolas", 8, "bold")
        ).pack(side=tk.RIGHT)

        # Title
        tk.Label(
            card,
            text=f"📌 {title}",
            bg="#211825",
            fg="#f8fafc",
            font=("Segoe UI", 11, "bold"),
            anchor="w",
            justify=tk.LEFT
        ).pack(fill=tk.X, pady=(4, 4))

        # Details Frame
        detail_frame = tk.Frame(card, bg="#1a141e", padx=10, pady=8)
        detail_frame.pack(fill=tk.X, pady=4)

        tk.Label(
            detail_frame,
            text=f"🎯 Đối tượng / Mục tiêu: {target}",
            bg="#1a141e",
            fg="#38bdf8",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
            justify=tk.LEFT
        ).pack(fill=tk.X, pady=(0, 3))

        tk.Label(
            detail_frame,
            text=f"💡 Giải thích & Lý do: {reason}",
            bg="#1a141e",
            fg="#e2e8f0",
            font=("Segoe UI", 9),
            anchor="w",
            justify=tk.LEFT,
            wraplength=480
        ).pack(fill=tk.X, pady=(2, 4))

        risk_frame = tk.Frame(detail_frame, bg="#2d161a", padx=8, pady=4)
        risk_frame.pack(fill=tk.X, pady=(4, 2))

        tk.Label(
            risk_frame,
            text=f"⚡ CẢNH BÁO RỦI RO: {risk}",
            bg="#2d161a",
            fg="#f87171",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
            justify=tk.LEFT,
            wraplength=460
        ).pack(fill=tk.X)

        if payload and payload.strip():
            p_box = tk.Frame(card, bg="#13141f", padx=8, pady=4)
            p_box.pack(fill=tk.X, pady=4)
            tk.Label(
                p_box,
                text=f"> {payload.strip()}",
                bg="#13141f",
                fg="#a7f3d0",
                font=("Consolas", 8),
                anchor="w",
                justify=tk.LEFT
            ).pack(fill=tk.X)

        status_lbl = tk.Label(
            card,
            text="❓ Đang chờ bạn đưa ra quyết định...",
            bg="#211825",
            fg="#94a3b8",
            font=("Segoe UI", 8, "italic")
        )
        status_lbl.pack(fill=tk.X, pady=(4, 6))

        btn_box = tk.Frame(card, bg="#211825")
        btn_box.pack(fill=tk.X, pady=(4, 2))

        btn_cancel = tk.Button(
            btn_box,
            text="✖  Cancel (Từ chối)",
            bg="#374151",
            fg="#f9fafb",
            activebackground="#4b5563",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            bd=0,
            padx=14,
            pady=6,
            cursor="hand2"
        )
        btn_cancel.pack(side=tk.LEFT, padx=(0, 10))

        btn_apply = tk.Button(
            btn_box,
            text="✔  Apply (Đồng ý thực hiện)",
            bg="#059669",
            fg="#ffffff",
            activebackground="#10b981",
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            bd=0,
            padx=16,
            pady=6,
            cursor="hand2"
        )
        btn_apply.pack(side=tk.LEFT)

        def on_user_cancel():
            btn_cancel.config(state=tk.DISABLED, bg="#1f2937", fg="#6b7280")
            btn_apply.config(state=tk.DISABLED, bg="#1f2937", fg="#6b7280")
            status_lbl.config(
                text="❌ BẠN ĐÃ TỪ CHỐI HÀNH ĐỘNG NÀY (Đã huỷ bỏ).",
                fg="#f87171"
            )
            card.config(highlightbackground="#ef4444")
            reject_msg = f"Tôi đã TỪ CHỐI hành động: '{title}'. Vui lòng không thực hiện và hãy đề xuất phương án an toàn khác."
            self.input_box.delete("1.0", tk.END)
            self.input_box.insert("1.0", reject_msg)
            self.send_message()

        def on_user_apply():
            btn_cancel.config(state=tk.DISABLED, bg="#1f2937", fg="#6b7280")
            btn_apply.config(state=tk.DISABLED, bg="#1f2937", fg="#6b7280")
            status_lbl.config(
                text="✅ BẠN ĐÃ CHẤP THUẬN (Đang thực hiện...).",
                fg="#34d399"
            )
            card.config(highlightbackground="#10b981")
            approve_msg = f"Tôi đã ĐỒNG Ý / CHẤP THUẬN thực hiện hành động: '{title}'. Hãy tiến hành thực hiện."
            self.input_box.delete("1.0", tk.END)
            self.input_box.insert("1.0", approve_msg)
            self.send_message()

        btn_cancel.config(command=on_user_cancel)
        btn_apply.config(command=on_user_apply)

    def _render_code_card(self, parent, lang_name, code_body):
        """Render a distinct, syntax-formatted code card with a Copy Code button."""
        code_frame = tk.Frame(
            parent,
            bg=THEME["bg_code"],
            padx=10,
            pady=8,
            highlightthickness=1,
            highlightbackground=THEME["border_code"]
        )
        code_frame.pack(fill=tk.X, pady=6)

        chdr = tk.Frame(code_frame, bg=THEME["bg_code"])
        chdr.pack(fill=tk.X, pady=(0, 4))

        tk.Label(
            chdr,
            text=f"[{lang_name}]",
            bg=THEME["bg_code"],
            fg=THEME["text_muted"],
            font=("Consolas", 8, "bold")
        ).pack(side=tk.LEFT)

        btn_copy_code = tk.Label(
            chdr,
            text="[📋 Copy Code]",
            bg=THEME["bg_code"],
            fg=THEME["accent_blue"],
            font=("Consolas", 8, "bold"),
            cursor="hand2"
        )
        btn_copy_code.pack(side=tk.RIGHT)
        btn_copy_code.bind("<Button-1>", lambda e, cb=code_body: self.copy_to_clipboard(cb))

        lines_count = min(max(code_body.count("\n") + 1, 1), 22)
        code_txt = tk.Text(
            code_frame,
            font=("Consolas", 9),
            bg=THEME["bg_code"],
            fg="#e2e8f0",
            relief=tk.FLAT,
            bd=0,
            height=lines_count,
            wrap=tk.NONE
        )
        code_txt.insert(tk.END, code_body)
        code_txt.config(state=tk.DISABLED)
        code_txt.pack(fill=tk.BOTH, expand=True)

    # ============================================================
    # PHASE 3: CONTEXT INSPECTOR & SOURCE VIEWER MODALS
    # ============================================================

    def open_context_inspector(self, context_meta):
        """Open Explainable AI Context Inspector Modal."""
        modal = tk.Toplevel(self.root)
        modal.title("Ngữ cảnh đã sử dụng (Context Inspector)")
        modal.geometry("700x520")
        modal.configure(bg=THEME["bg_root"])
        modal.transient(self.root)
        modal.grab_set()

        top_frame = tk.Frame(modal, bg=THEME["bg_header"], padx=20, pady=12)
        top_frame.pack(fill=tk.X)
        tk.Label(top_frame, text="🔍 BẢNG GIẢI THÍCH NGỮ CẢNH TRUY XUẤT (CONTEXT INSPECTOR)", bg=THEME["bg_header"], fg=THEME["text_white"], font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)

        canvas = tk.Canvas(modal, bg=THEME["bg_root"], bd=0, highlightthickness=0)
        scroll = ttk.Scrollbar(modal, orient=tk.VERTICAL, command=canvas.yview)
        body = tk.Frame(canvas, bg=THEME["bg_root"], padx=20, pady=14)

        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        if not context_meta:
            tk.Label(body, text="Không có thông tin ngữ cảnh chi tiết cho tin nhắn này (được tải từ lịch sử cũ).", bg=THEME["bg_root"], fg=THEME["text_muted"], font=("Segoe UI", 10)).pack(pady=20)
            return

        proj_name = context_meta.get("project_name", "Mặc định")
        memories = context_meta.get("memories", [])
        rag_sources = context_meta.get("rag_sources", [])
        hist_count = context_meta.get("historical_count", 0)
        summaries = context_meta.get("summaries", [])
        used_web = context_meta.get("used_web", False)
        web_queries = context_meta.get("web_queries", [])

        # Card 1: Project & Recent Messages
        c1 = tk.Frame(body, bg=THEME["bg_card"], padx=14, pady=10, highlightthickness=1, highlightbackground=THEME["border_subtle"])
        c1.pack(fill=tk.X, pady=(0, 10))
        tk.Label(c1, text=f"📁 Dự án: {proj_name}", bg=THEME["bg_card"], fg=THEME["text_white"], font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(c1, text=f"💬 Tin nhắn hội thoại gần đây được nạp: {RECENT_MESSAGES_LIMIT} tin", bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 9)).pack(anchor="w")

        # Card 2: Project Memory
        c2 = tk.Frame(body, bg=THEME["bg_card"], padx=14, pady=10, highlightthickness=1, highlightbackground=THEME["border_subtle"])
        c2.pack(fill=tk.X, pady=(0, 10))
        tk.Label(c2, text=f"🧠 Ghi nhớ dự án (Project Memory): {len(memories)} facts", bg=THEME["bg_card"], fg=THEME["accent_emerald"], font=("Segoe UI", 10, "bold")).pack(anchor="w")
        if memories:
            for m in memories:
                tk.Label(c2, text=f"  • {m['content']}  (Score: {m.get('score', 'N/A')}, Độ quan trọng: {m.get('importance', 5)})", bg=THEME["bg_card"], fg=THEME["text_bright"], font=("Segoe UI", 9), wraplength=620, justify=tk.LEFT).pack(anchor="w", pady=2)
        else:
            tk.Label(c2, text="  (Không có ghi nhớ nào khớp với câu hỏi)", bg=THEME["bg_card"], fg=THEME["text_dim"], font=("Segoe UI", 9)).pack(anchor="w")

        # Card 3: RAG Knowledge Sources
        c3 = tk.Frame(body, bg=THEME["bg_card"], padx=14, pady=10, highlightthickness=1, highlightbackground=THEME["border_subtle"])
        c3.pack(fill=tk.X, pady=(0, 10))
        tk.Label(c3, text=f"📚 Tài liệu & Mã nguồn RAG (Project Knowledge): {len(rag_sources)} chunks", bg=THEME["bg_card"], fg=THEME["accent_blue"], font=("Segoe UI", 10, "bold")).pack(anchor="w")
        if rag_sources:
            for s in rag_sources:
                rp = s.get("relative_path", "unknown")
                sl = s.get("start_line", 1)
                el = s.get("end_line", 1)
                sc = s.get("score", 0.0)

                s_row = tk.Frame(c3, bg=THEME["bg_card"])
                s_row.pack(fill=tk.X, pady=3)
                tk.Label(s_row, text=f"  ▶ {rp} (Dòng {sl}–{el}) • Score: {sc}", bg=THEME["bg_card"], fg=THEME["text_bright"], font=("Segoe UI", 9)).pack(side=tk.LEFT)

                btn_view = tk.Label(s_row, text="[📖 Xem mã]", bg=THEME["bg_card"], fg=THEME["accent_blue"], font=("Segoe UI", 9, "bold", "underline"), cursor="hand2")
                btn_view.pack(side=tk.RIGHT)
                btn_view.bind("<Button-1>", lambda e, path=rp, start=sl, end=el: self.open_source_viewer(path, start, end))
        else:
            tk.Label(c3, text="  (Không có đoạn mã nào cần truy xuất cho câu hỏi này)", bg=THEME["bg_card"], fg=THEME["text_dim"], font=("Segoe UI", 9)).pack(anchor="w")

        # Card 4: Historical Chat & Web Search
        c4 = tk.Frame(body, bg=THEME["bg_card"], padx=14, pady=10, highlightthickness=1, highlightbackground=THEME["border_subtle"])
        c4.pack(fill=tk.X)
        tk.Label(c4, text="🌐 Tra cứu & Lịch sử bổ trợ", bg=THEME["bg_card"], fg=THEME["accent_amber"], font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(c4, text=f"  • Lịch sử thảo luận tương đồng: {hist_count} cặp tin nhắn cũ", bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 9)).pack(anchor="w")
        
        web_info = f"Đã tra cứu web: {', '.join(web_queries)}" if used_web and web_queries else ("Đã gọi công cụ tra cứu web" if used_web else "Không sử dụng")
        tk.Label(c4, text=f"  • Tra cứu Web thời gian thực: {web_info}", bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 9)).pack(anchor="w")

    def open_source_viewer(self, relative_path, start_line=1, end_line=1):
        """Open Source Viewer Modal showing actual code with highlighted lines."""
        if not self.current_project_id:
            return
        abs_path = database.get_file_path_by_relative_path(self.current_project_id, relative_path)
        if not abs_path or not os.path.isfile(abs_path):
            messagebox.showwarning("Thông báo", f"Không tìm thấy tệp gốc trên đĩa:\n{relative_path}", parent=self.root)
            return

        modal = tk.Toplevel(self.root)
        modal.title(f"Xem mã nguồn: {relative_path}")
        modal.geometry("820x560")
        modal.configure(bg=THEME["bg_root"])
        modal.transient(self.root)
        modal.grab_set()

        top_frame = tk.Frame(modal, bg=THEME["bg_header"], padx=20, pady=12)
        top_frame.pack(fill=tk.X)
        tk.Label(top_frame, text=f"📖 {relative_path} (Dòng {start_line} đến {end_line})", bg=THEME["bg_header"], fg=THEME["text_white"], font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)

        def open_external():
            try:
                os.startfile(abs_path)
            except Exception:
                pass

        tk.Button(top_frame, text="📂 Mở tệp ngoài", command=open_external, bg=THEME["btn_dark"], fg=THEME["text_white"], font=("Segoe UI", 8), relief=tk.FLAT, padx=8, pady=3, cursor="hand2").pack(side=tk.RIGHT)

        # Code viewer text with Consolas font
        code_view = scrolledtext.ScrolledText(
            modal,
            font=("Consolas", 10),
            bg=THEME["bg_code"],
            fg="#e2e8f0",
            wrap=tk.NONE,
            padx=14,
            pady=10,
            bd=0
        )
        code_view.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)

        code_view.tag_configure("highlight_line", background="#2a273b", foreground="#38bdf8")
        code_view.tag_configure("line_num", foreground=THEME["text_dim"])

        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            for idx, line in enumerate(lines, 1):
                num_str = f"{idx:4d} | "
                is_target = (start_line <= idx <= end_line)
                tag = "highlight_line" if is_target else "normal"

                code_view.insert(tk.END, num_str, "line_num")
                code_view.insert(tk.END, line, tag)

            # Scroll to start_line
            code_view.see(f"{max(1, start_line - 3)}.0")
        except Exception as e:
            code_view.insert(tk.END, f"Không thể đọc nội dung tệp: {e}")

        code_view.config(state=tk.DISABLED)

    # ============================================================
    # PHASE 3: SEARCH CHAT HISTORY & EXPORT MARKDOWN
    # ============================================================

    def _execute_chat_search(self, event):
        query = self.search_entry.get().strip()
        if not query or query == "🔍 Tìm kiếm tin nhắn...":
            return

        results = database.search_chat_history(query, self.current_project_id)
        if not results:
            messagebox.showinfo("Kết quả tìm kiếm", f"Không tìm thấy tin nhắn nào chứa từ khóa:\n'{query}'", parent=self.root)
            return

        modal = tk.Toplevel(self.root)
        modal.title(f"Kết quả tìm kiếm: '{query}' ({len(results)} kết quả)")
        modal.geometry("680x440")
        modal.configure(bg=THEME["bg_root"])
        modal.transient(self.root)
        modal.grab_set()

        hdr = tk.Frame(modal, bg=THEME["bg_header"], padx=18, pady=10)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text=f"🔍 TÌM THẤY {len(results)} TIN NHẮN CHỨA: '{query}'", bg=THEME["bg_header"], fg=THEME["text_white"], font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)

        tree = ttk.Treeview(modal, columns=("convo", "snippet", "time"), show="headings", selectmode="browse")
        tree.heading("convo", text="Cuộc trò chuyện")
        tree.heading("snippet", text="Đoạn trích nội dung")
        tree.heading("time", text="Thời gian")

        tree.column("convo", width=160)
        tree.column("snippet", width=360)
        tree.column("time", width=120, anchor="center")

        tree.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        for r in results:
            tree.insert("", tk.END, values=(r["conversation_title"], r["snippet"], r["created_at"][:19]), tags=(str(r["conversation_id"]),))

        def jump_to_convo():
            sel = tree.selection()
            if not sel:
                return
            c_id = int(tree.item(sel[0])["tags"][0])
            modal.destroy()
            self.select_conversation(c_id)

        tree.bind("<Double-1>", lambda e: jump_to_convo())

        btn_jump = tk.Button(modal, text="Chuyển đến cuộc trò chuyện ➔", command=jump_to_convo, bg=THEME["primary"], fg=THEME["text_white"], font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=12, pady=6, cursor="hand2")
        btn_jump.pack(pady=(0, 12))

    def on_export_chat(self):
        """Export current conversation to formatted Markdown file."""
        if not self.current_conversation_id:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn một cuộc trò chuyện để xuất!")
            return

        conv = database.get_conversation(self.current_conversation_id)
        if not conv:
            return

        title_clean = "".join(c for c in conv[2] if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
        default_file = f"chat_{title_clean}.md"

        dest = filedialog.asksaveasfilename(
            title="Lưu tài liệu cuộc trò chuyện (.md)",
            initialfile=default_file,
            defaultextension=".md",
            filetypes=[("Markdown Document", "*.md"), ("Text File", "*.txt"), ("All Files", "*.*")],
            parent=self.root
        )
        if not dest:
            return

        try:
            database.export_conversation_markdown(self.current_conversation_id, destination_path=dest)
            messagebox.showinfo("Xuất tài liệu thành công", f"Đã xuất toàn bộ cuộc trò chuyện ra tệp Markdown:\n{dest}", parent=self.root)
            self.set_ui_status("Đã xuất cuộc trò chuyện ra Markdown.", THEME["status_ready"])
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể xuất file: {e}")

    # ============================================================
    # PHASE 2: DATA MANAGEMENT & PROJECT MEMORY MANAGER
    # ============================================================

    def on_rename_project(self):
        if not self.current_project_id:
            return
        proj = database.get_project(self.current_project_id)
        if not proj:
            return
        current_name = proj[1]
        new_name = simpledialog.askstring("Đổi tên dự án", "Nhập tên mới cho dự án:", initialvalue=current_name, parent=self.root)
        if not new_name or not new_name.strip() or new_name.strip() == current_name:
            return
        try:
            database.rename_project(self.current_project_id, new_name.strip())
            self.refresh_sidebar()
            self.active_project_badge.config(text=f"📁 Dự án: {new_name.strip()}")
            self.set_ui_status(f"Đã đổi tên dự án thành: {new_name.strip()}", THEME["status_ready"])
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể đổi tên dự án: {e}")

    def on_delete_project(self):
        if not self.current_project_id:
            return
        proj = database.get_project(self.current_project_id)
        if not proj:
            return
        proj_name = proj[1]
        confirm = messagebox.askyesno(
            "Xác nhận xoá dự án",
            f"Bạn có chắc chắn muốn xoá vĩnh viễn dự án '{proj_name}'?\n\nToàn bộ hội thoại, ghi nhớ và tệp tài liệu RAG của dự án này sẽ bị xoá an toàn khỏi cơ sở dữ liệu.",
            parent=self.root
        )
        if not confirm:
            return
        try:
            database.delete_project(self.current_project_id)
            self.set_ui_status(f"Đã xoá dự án '{proj_name}' thành công.", THEME["status_ready"])
            self.load_initial_data()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể xoá dự án: {e}")

    def on_rename_conversation(self):
        selected = self.tree.selection()
        if not selected or not selected[0].startswith("convo_"):
            c_id = self.current_conversation_id
        else:
            c_id = int(selected[0].split("_")[1])
        if not c_id:
            return
        conv = database.get_conversation(c_id)
        if not conv:
            return
        current_title = conv[2]
        new_title = simpledialog.askstring("Đổi tên cuộc trò chuyện", "Nhập tên mới:", initialvalue=current_title, parent=self.root)
        if not new_title or not new_title.strip() or new_title.strip() == current_title:
            return
        try:
            database.rename_conversation(c_id, new_title.strip())
            self.refresh_sidebar()
            if self.current_conversation_id == c_id:
                self.title_label.config(text=new_title.strip())
            self.set_ui_status("Đã cập nhật tên cuộc trò chuyện.", THEME["status_ready"])
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể đổi tên cuộc trò chuyện: {e}")

    def on_delete_conversation(self):
        selected = self.tree.selection()
        if not selected or not selected[0].startswith("convo_"):
            c_id = self.current_conversation_id
        else:
            c_id = int(selected[0].split("_")[1])
        if not c_id:
            return
        conv = database.get_conversation(c_id)
        if not conv:
            return
        title = conv[2]
        confirm = messagebox.askyesno(
            "Xác nhận xoá hội thoại",
            f"Bạn có chắc muốn xoá cuộc trò chuyện '{title}'?",
            parent=self.root
        )
        if not confirm:
            return
        try:
            database.delete_conversation(c_id)
            self.set_ui_status("Đã xoá cuộc trò chuyện.", THEME["status_ready"])
            self.refresh_sidebar()
            convos = database.get_conversations(self.current_project_id)
            if convos:
                self.select_conversation(convos[0][0])
            else:
                new_id = database.create_conversation(self.current_project_id, "Trò chuyện mới")
                self.refresh_sidebar()
                self.select_conversation(new_id)
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể xoá cuộc trò chuyện: {e}")

    def open_memory_manager(self):
        """Open Modern Project Memory Manager Modal."""
        if not self.current_project_id:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn một dự án trước!")
            return

        proj = database.get_project(self.current_project_id)
        proj_name = proj[1] if proj else "Hiện tại"

        modal = tk.Toplevel(self.root)
        modal.title(f"Quản lý Bộ nhớ Dự án: {proj_name}")
        modal.geometry("740x500")
        modal.configure(bg=THEME["bg_root"])
        modal.transient(self.root)
        modal.grab_set()

        top_frame = tk.Frame(modal, bg=THEME["bg_header"], padx=18, pady=12)
        top_frame.pack(fill=tk.X)
        tk.Label(top_frame, text=f"🧠 BỘ NHỚ DÀI HẠN — [{proj_name}]", bg=THEME["bg_header"], fg=THEME["text_white"], font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)

        content_frame = tk.Frame(modal, bg=THEME["bg_root"], padx=18, pady=14)
        content_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("id", "content", "importance", "created_at")
        tree = ttk.Treeview(content_frame, columns=cols, show="headings", selectmode="browse")
        tree.heading("id", text="ID")
        tree.heading("content", text="Nội dung ghi nhớ")
        tree.heading("importance", text="Độ quan trọng (1-10)")
        tree.heading("created_at", text="Thời gian")

        tree.column("id", width=45, anchor="center")
        tree.column("content", width=420)
        tree.column("importance", width=110, anchor="center")
        tree.column("created_at", width=130, anchor="center")

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        m_scroll = ttk.Scrollbar(content_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=m_scroll.set)
        m_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        def reload_memories():
            for it in tree.get_children():
                tree.delete(it)
            mems = database.get_project_memories(self.current_project_id)
            for m in mems:
                tree.insert("", tk.END, values=(m["id"], m["content"], m["importance"], m["created_at"][:19]))

        reload_memories()

        act_frame = tk.Frame(modal, bg=THEME["bg_card"], padx=18, pady=10)
        act_frame.pack(fill=tk.X)

        def add_mem():
            new_text = simpledialog.askstring("Thêm ghi nhớ", "Nhập thông tin quan trọng cần ghi nhớ:", parent=modal)
            if not new_text or not new_text.strip():
                return
            database.save_project_memory(self.current_project_id, new_text.strip(), importance=7)
            reload_memories()

        def edit_mem():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Cảnh báo", "Vui lòng chọn 1 dòng ghi nhớ để sửa.", parent=modal)
                return
            vals = tree.item(sel[0])["values"]
            mem_id = vals[0]
            current_text = vals[1]
            edited = simpledialog.askstring("Sửa ghi nhớ", "Cập nhật nội dung ghi nhớ:", initialvalue=current_text, parent=modal)
            if not edited or not edited.strip():
                return
            database.update_project_memory(mem_id, edited.strip(), importance=vals[2])
            reload_memories()

        def del_mem():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("Cảnh báo", "Vui lòng chọn 1 dòng ghi nhớ để xoá.", parent=modal)
                return
            mem_id = tree.item(sel[0])["values"][0]
            if messagebox.askyesno("Xác nhận", "Xoá thông tin ghi nhớ này?", parent=modal):
                database.delete_project_memory(mem_id)
                reload_memories()

        btn_add = tk.Button(act_frame, text="➕ Thêm mới", command=add_mem, bg=THEME["primary"], fg=THEME["text_white"], font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=12, pady=5, cursor="hand2")
        btn_add.pack(side=tk.LEFT, padx=(0, 6))

        btn_edit = tk.Button(act_frame, text="✏️ Chỉnh sửa", command=edit_mem, bg=THEME["btn_dark"], fg=THEME["text_white"], font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=12, pady=5, cursor="hand2")
        btn_edit.pack(side=tk.LEFT, padx=(0, 6))

        btn_del = tk.Button(act_frame, text="🗑️ Xoá", command=del_mem, bg=THEME["btn_dark"], fg=THEME["status_err"], font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=12, pady=5, cursor="hand2")
        btn_del.pack(side=tk.LEFT)

        btn_close = tk.Button(act_frame, text="Đóng", command=modal.destroy, bg=THEME["btn_dark"], fg=THEME["text_muted"], font=("Segoe UI", 9), relief=tk.FLAT, padx=12, pady=5, cursor="hand2")
        btn_close.pack(side=tk.RIGHT)

    def open_database_maintenance(self):
        """Open Safe Database Backup, Restore & VACUUM Maintenance Modal."""
        modal = tk.Toplevel(self.root)
        modal.title("Sao lưu & Bảo trì Cơ sở Dữ liệu")
        modal.geometry("640x460")
        modal.configure(bg=THEME["bg_root"])
        modal.transient(self.root)
        modal.grab_set()

        header = tk.Frame(modal, bg=THEME["bg_header"], padx=20, pady=12)
        header.pack(fill=tk.X)
        tk.Label(header, text="💾 SAO LƯU & BẢO TRÌ DATABASE (SQLITE)", bg=THEME["bg_header"], fg=THEME["text_white"], font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)

        body = tk.Frame(modal, bg=THEME["bg_root"], padx=20, pady=18)
        body.pack(fill=tk.BOTH, expand=True)

        card1 = tk.Frame(body, bg=THEME["bg_card"], padx=14, pady=12, highlightthickness=1, highlightbackground=THEME["border_subtle"])
        card1.pack(fill=tk.X, pady=(0, 12))
        tk.Label(card1, text="1. SAO LƯU AN TOÀN (ONLINE BACKUP)", bg=THEME["bg_card"], fg=THEME["accent_emerald"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(card1, text="Tạo bản sao lưu chuẩn SQLite (không lo xung đột lock tệp ngay cả khi đang trò chuyện).", bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 8))

        def do_backup():
            try:
                b_path = database.backup_database()
                messagebox.showinfo("Thành công", f"Đã sao lưu Database thành công vào:\n{b_path}", parent=modal)
                self.set_ui_status("Đã sao lưu database an toàn.", THEME["status_ready"])
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không thể sao lưu: {e}", parent=modal)

        def open_backup_folder():
            b_dir = os.path.join(os.path.dirname(os.path.abspath(database.DB_PATH)), "backups")
            os.makedirs(b_dir, exist_ok=True)
            try:
                os.startfile(b_dir)
            except Exception:
                pass

        b_btn_frame = tk.Frame(card1, bg=THEME["bg_card"])
        b_btn_frame.pack(fill=tk.X)
        tk.Button(b_btn_frame, text="📦 Sao lưu ngay", command=do_backup, bg=THEME["primary"], fg=THEME["text_white"], font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=10, pady=5, cursor="hand2").pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(b_btn_frame, text="📂 Mở thư mục Backups", command=open_backup_folder, bg=THEME["btn_dark"], fg=THEME["text_white"], font=("Segoe UI", 9), relief=tk.FLAT, padx=10, pady=5, cursor="hand2").pack(side=tk.LEFT)

        card2 = tk.Frame(body, bg=THEME["bg_card"], padx=14, pady=12, highlightthickness=1, highlightbackground=THEME["border_subtle"])
        card2.pack(fill=tk.X, pady=(0, 12))
        tk.Label(card2, text="2. PHỤC HỒI DỮ LIỆU (RESTORE)", bg=THEME["bg_card"], fg=THEME["accent_amber"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(card2, text="Khôi phục dữ liệu từ tệp .db sao lưu. Tự động kiểm tra tính toàn vẹn trước khi nạp.", bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 8))

        def do_restore():
            file_selected = filedialog.askopenfilename(
                title="Chọn tệp cơ sở dữ liệu sao lưu (.db)",
                filetypes=[("SQLite DB", "*.db"), ("All files", "*.*")],
                parent=modal
            )
            if not file_selected:
                return
            if not messagebox.askyesno("Cảnh báo phục hồi", "Phục hồi database sẽ thay thế dữ liệu hiện tại bằng dữ liệu của file sao lưu.\n(Bản hiện tại sẽ được tự động lưu lại vào .bak_before_restore).\n\nBạn có muốn tiếp tục?", parent=modal):
                return
            try:
                database.restore_database(file_selected)
                messagebox.showinfo("Thành công", "Đã phục hồi cơ sở dữ liệu thành công! Ứng dụng sẽ nạp lại dữ liệu.", parent=modal)
                modal.destroy()
                self.load_initial_data()
            except Exception as e:
                messagebox.showerror("Lỗi phục hồi", f"Không thể phục hồi database: {e}", parent=modal)

        tk.Button(card2, text="📥 Phục hồi từ file Backup", command=do_restore, bg=THEME["btn_dark"], fg=THEME["accent_amber"], font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=10, pady=5, cursor="hand2").pack(anchor="w")

        card3 = tk.Frame(body, bg=THEME["bg_card"], padx=14, pady=12, highlightthickness=1, highlightbackground=THEME["border_subtle"])
        card3.pack(fill=tk.X)
        tk.Label(card3, text="3. TỐI ƯU HÓA & DỌN DẸP (VACUUM)", bg=THEME["bg_card"], fg=THEME["accent_blue"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        tk.Label(card3, text="Dọn sạch cache web hết hạn, dọn các chunks mồ côi và chạy VACUUM để thu nhỏ file database.", bg=THEME["bg_card"], fg=THEME["text_muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 8))

        def do_optimize():
            try:
                res = database.optimize_database()
                b_kb = round(res["before_bytes"] / 1024, 1)
                a_kb = round(res["after_bytes"] / 1024, 1)
                f_kb = round(res["freed_bytes"] / 1024, 1)
                messagebox.showinfo(
                    "Hoàn tất Tối ưu Database",
                    f"Tối ưu hoàn tất!\n- Dung lượng trước: {b_kb} KB\n- Dung lượng sau: {a_kb} KB\n- Đã thu hồi: {f_kb} KB không gian đĩa.",
                    parent=modal
                )
                self.set_ui_status("Đã tối ưu hóa Database hoàn tất.", THEME["status_ready"])
            except Exception as e:
                messagebox.showerror("Lỗi tối ưu", f"Lỗi tối ưu database: {e}", parent=modal)

        tk.Button(card3, text="⚡ Chạy Tối ưu Database (VACUUM)", command=do_optimize, bg=THEME["btn_dark"], fg=THEME["text_bright"], font=("Segoe UI", 9, "bold"), relief=tk.FLAT, padx=10, pady=5, cursor="hand2").pack(anchor="w")

    # ============================================================
    # PROJECT KNOWLEDGE UI HANDLERS
    # ============================================================

    def on_add_knowledge_folder(self):
        if not self.current_project_id:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn hoặc tạo một dự án trước!")
            return

        folder_selected = filedialog.askdirectory(title="Chọn thư mục mã nguồn/tài liệu cho dự án", parent=self.root)
        if not folder_selected:
            return

        try:
            source_id = database.add_project_source(self.current_project_id, "folder", folder_selected)
            self.set_ui_status(f"Đã thêm thư mục nguồn #{source_id}. Bấm 'Index Knowledge' để quét.", THEME["status_ready"])
            self.refresh_knowledge_stats()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể thêm thư mục: {e}")

    def on_add_knowledge_file(self):
        if not self.current_project_id:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn hoặc tạo một dự án trước!")
            return

        file_selected = filedialog.askopenfilename(
            title="Chọn tệp tài liệu cho dự án",
            filetypes=[("Supported files", "*.cs;*.py;*.js;*.ts;*.sql;*.md;*.txt;*.json;*.pdf"), ("All files", "*.*")],
            parent=self.root
        )
        if not file_selected:
            return

        try:
            source_id = database.add_project_source(self.current_project_id, "file", file_selected)
            self.set_ui_status(f"Đã thêm tệp nguồn #{source_id}. Bấm 'Index Knowledge' để quét.", THEME["status_ready"])
            self.refresh_knowledge_stats()
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể thêm tệp: {e}")

    def on_reindex_knowledge(self):
        if not self.current_project_id:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn hoặc tạo một dự án trước!")
            return

        if self.is_processing:
            messagebox.showinfo("Thông báo", "Ứng dụng đang xử lý một tác vụ khác. Vui lòng đợi!")
            return

        self.is_processing = True
        self.btn_reindex_knowledge.config(state=tk.DISABLED)
        self.set_ui_status("⚡ Đang quét & lập chỉ mục Knowledge RAG...", THEME["status_busy"])

        project_id = self.current_project_id

        def worker():
            try:
                def progress(current, total, filename):
                    msg = f"Đang index ({current}/{total}): {filename[:25]}..."
                    self.run_on_ui_thread(lambda: self.set_ui_status(msg, THEME["status_busy"]))

                stats = knowledge_service.sync_project_sources(project_id, progress_callback=progress)

                def on_done():
                    self.refresh_knowledge_stats()
                    scanned = stats.get("scanned_files", 0)
                    indexed = stats.get("indexed_files", 0)
                    chunks = stats.get("indexed_chunks", 0)
                    skipped = stats.get("skipped_unchanged", 0)
                    msg = f"Hoàn tất Index: {scanned} tệp, {indexed} mới ({chunks} chunks), {skipped} giữ nguyên."
                    self.set_ui_status(msg, THEME["status_ready"])
                    self.btn_reindex_knowledge.config(state=tk.NORMAL)
                    self.is_processing = False

                self.run_on_ui_thread(on_done)
            except Exception as e:
                def on_err():
                    self.set_ui_status(f"Lỗi index: {e}", THEME["status_err"])
                    self.btn_reindex_knowledge.config(state=tk.NORMAL)
                    self.is_processing = False
                self.run_on_ui_thread(on_err)

        threading.Thread(target=worker, daemon=True).start()

    def refresh_knowledge_stats(self):
        if not self.current_project_id:
            self.knowledge_stats_label.config(text="0 tài liệu | 0 chunks")
            return

        try:
            stats = database.get_project_knowledge_stats(self.current_project_id)
            files = stats.get("active_files", 0)
            chunks = stats.get("active_chunks", 0)
            self.knowledge_stats_label.config(text=f"{files} tệp | {chunks} chunks đã index")
        except Exception:
            self.knowledge_stats_label.config(text="Chưa có dữ liệu RAG")

    # ============================================================
    # UI QUEUE & THREADING
    # ============================================================

    def run_on_ui_thread(self, callback):
        self.ui_queue.put(callback)

    def process_ui_queue(self):
        try:
            while not self.ui_queue.empty():
                callback = self.ui_queue.get_nowait()
                try:
                    callback()
                except Exception as e:
                    print(f"[UI Queue Error]: {e}")
        finally:
            self.root.after(40, self.process_ui_queue)

    def set_ui_status(self, text, dot_color=THEME["status_ready"]):
        self.status_label.config(text=text)
        self.status_dot.config(fg=dot_color)

    # ============================================================
    # SIDEBAR REFRESH & NAVIGATION
    # ============================================================

    def load_initial_data(self):
        proj_id = database.get_or_create_default_project()
        self.current_project_id = proj_id

        convos = database.get_conversations(proj_id)
        if not convos:
            convo_id = database.create_conversation(proj_id, "Trò chuyện mới")
        else:
            convo_id = convos[0][0]

        self.refresh_sidebar(keep_current_open=False)
        self.select_conversation(convo_id)

    def refresh_sidebar(self, keep_current_open=False):
        for item in self.tree.get_children():
            self.tree.delete(item)

        projects = database.get_projects()
        for proj in projects:
            p_id, p_name = proj[0], proj[1]
            p_node = f"proj_{p_id}"
            # Keep projects collapsed (open=False) by default so conversations don't spill out
            should_open = bool(keep_current_open and p_id == self.current_project_id)
            self.tree.insert("", tk.END, p_node, text=f"📁  {p_name}", open=should_open)

            convos = database.get_conversations(p_id)
            for conv in convos:
                c_id, c_title = conv[0], conv[2]
                c_node = f"convo_{c_id}"
                self.tree.insert(p_node, tk.END, c_node, text=f"  💬  {c_title}")

    def on_tree_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        node_id = selected[0]

        if node_id.startswith("convo_"):
            c_id = int(node_id.split("_")[1])
            self.select_conversation(c_id)
        elif node_id.startswith("proj_"):
            p_id = int(node_id.split("_")[1])
            self.current_project_id = p_id
            cur_proj = database.get_project(p_id)
            if cur_proj:
                self.active_project_badge.config(text=f"📁 Dự án: {cur_proj[1]}")
            self.refresh_knowledge_stats()
            # Toggle project open/close when clicking the project header
            is_open = self.tree.item(node_id, "open")
            self.tree.item(node_id, open=not is_open)

    # ============================================================
    # CONVERSATION LOADING & RENDERING
    # ============================================================

    def select_conversation(self, conversation_id):
        if self._is_selecting:
            return
        self._is_selecting = True
        try:
            conv = database.get_conversation(conversation_id)
            if not conv:
                return

            self.current_conversation_id = conversation_id
            self.current_project_id = conv[1]

            self.title_label.config(text=conv[2])
            cur_proj = database.get_project(self.current_project_id)
            if cur_proj:
                self.active_project_badge.config(text=f"📁 Dự án: {cur_proj[1]}")
            self.refresh_knowledge_stats()

            messages = database.get_messages_latest(conversation_id, limit=UI_MESSAGE_PAGE_SIZE)

            self.chat_box.config(state=tk.NORMAL)
            self.chat_box.delete("1.0", tk.END)

            if messages:
                self.oldest_loaded_message_id = messages[0][0]
                for msg in messages:
                    self._render_message_chunk(msg[1], msg[2], msg_id=msg[0])
            else:
                self.oldest_loaded_message_id = None
                self.chat_box.insert(tk.END, "💡 Cuộc trò chuyện mới. Hãy nhập câu hỏi bên dưới để bắt đầu!\n\n")
                self.chat_box.tag_add("align_center", "1.0", "end")

            if len(messages) < UI_MESSAGE_PAGE_SIZE:
                self.btn_load_older.config(state=tk.DISABLED, text="Đã hiển thị toàn bộ tin nhắn")
            else:
                self.btn_load_older.config(state=tk.NORMAL, text="⬆  Tải thêm tin nhắn cũ hơn")

            self.chat_box.config(state=tk.DISABLED)
            self.chat_box.see(tk.END)
            self.input_box.focus_set()
        finally:
            self._is_selecting = False

    def on_load_older_messages(self):
        if not self.current_conversation_id or self.oldest_loaded_message_id is None:
            return

        older_messages = database.get_messages_before(
            self.current_conversation_id,
            self.oldest_loaded_message_id,
            limit=UI_MESSAGE_PAGE_SIZE
        )

        if not older_messages:
            self.btn_load_older.config(state=tk.DISABLED, text="Đã hiển thị toàn bộ tin nhắn")
            return

        self.oldest_loaded_message_id = older_messages[0][0]

        self.chat_box.config(state=tk.NORMAL)
        for msg in reversed(older_messages):
            self._render_message_chunk(msg[1], msg[2], msg_id=msg[0], append_at_top=True)

        self.chat_box.config(state=tk.DISABLED)

        if len(older_messages) < UI_MESSAGE_PAGE_SIZE:
            self.btn_load_older.config(state=tk.DISABLED, text="Đã hiển thị toàn bộ tin nhắn")

    # ============================================================
    # CREATION & MANAGEMENT HANDLERS
    # ============================================================

    def on_new_project_dialog(self):
        name = simpledialog.askstring("Tạo dự án mới", "Nhập tên dự án:", parent=self.root)
        if not name or not name.strip():
            return

        desc = simpledialog.askstring("Mô tả dự án", "Nhập mô tả dự án (tùy chọn):", parent=self.root) or ""
        try:
            proj_id = database.create_project(name.strip(), desc.strip())
            self.current_project_id = proj_id
            convo_id = database.create_conversation(proj_id, "Trò chuyện mới")
            self.refresh_sidebar()
            self.select_conversation(convo_id)
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể tạo dự án: {e}")

    def on_new_conversation(self):
        if not self.current_project_id:
            self.current_project_id = database.get_or_create_default_project()

        convo_id = database.create_conversation(self.current_project_id, "Trò chuyện mới")
        self.refresh_sidebar(keep_current_open=True)
        self.select_conversation(convo_id)

    # ============================================================
    # CHAT EXECUTION, STREAMING & CANCEL
    # ============================================================

    def on_enter_pressed(self, event):
        self.send_message()
        return "break"

    def on_shift_enter(self, event):
        self.input_box.insert(tk.INSERT, "\n")
        return "break"

    def cancel_generation(self):
        """Immediately abort generation, closing the active socket to stop GPU/CUDA."""
        if not self.is_processing:
            return
        self.set_ui_status("⏹ Đang dừng phản hồi...", THEME["status_busy"])
        self.cancel_event.set()

    def on_regenerate(self):
        """Regenerate the last assistant response."""
        if self.is_processing:
            return
        convo_id = self.current_conversation_id
        if not convo_id:
            return

        last_user = database.get_last_user_message(convo_id)
        if not last_user:
            messagebox.showinfo("Thông báo", "Chưa có câu hỏi nào trong cuộc trò chuyện này để tạo lại.")
            return

        database.delete_last_assistant_message(convo_id)
        self.select_conversation(convo_id)
        self.send_message(retry_query=last_user[1])

    def send_message(self, retry_query=None):
        if self.is_processing:
            return

        if retry_query:
            text = retry_query.strip()
        else:
            text = self.input_box.get("1.0", tk.END).strip()
            if not text:
                return
            self.input_box.delete("1.0", tk.END)

        if text.startswith("/nho ") or text.startswith("/ghi_nho "):
            memory_content = text.split(" ", 1)[1].strip()
            if memory_content:
                self._handle_memory_command(text, memory_content)
                return

        # Enter processing state
        self.is_processing = True
        self.cancel_event.clear()

        # Swap Send -> Stop button
        self.send_button.pack_forget()
        self.stop_button.pack(fill=tk.BOTH, expand=True)

        self.set_ui_status("Đang chuẩn bị ngữ cảnh...", THEME["status_busy"])

        convo_id = self.current_conversation_id
        project_id = self.current_project_id

        # Insert User Message on the RIGHT if not a retry
        if not retry_query:
            self.chat_box.config(state=tk.NORMAL)
            self._render_message_chunk("user", text)
            self.chat_box.config(state=tk.DISABLED)
            self.chat_box.see(tk.END)

        # Prepare AI Bubble on the LEFT for streaming
        self.chat_box.config(state=tk.NORMAL)
        streaming_bubble = self._create_ai_bubble("...", is_streaming=True)
        start_idx = self.chat_box.index(tk.END)
        self.chat_box.window_create(tk.END, window=streaming_bubble)
        self.chat_box.insert(tk.END, "\n\n")
        end_idx = self.chat_box.index(tk.END)
        self.chat_box.tag_add("align_left", start_idx, end_idx)
        self.chat_box.config(state=tk.DISABLED)
        self.chat_box.see(tk.END)

        # Worker Thread
        def worker():
            accumulated_stream = []
            has_started_stream = [False]
            web_queries_called = []

            try:
                user_text = text
                query_emb = None
                if ollama_client.should_embed_message(user_text):
                    query_emb = ollama_client.get_embedding(user_text)

                if not retry_query:
                    database.save_message(convo_id, "user", user_text, embedding=query_emb)

                # Auto-title conversation on first message
                conv_row = database.get_conversation(convo_id)
                if conv_row and conv_row[2] == "Trò chuyện mới":
                    short_title = user_text[:28] + ("..." if len(user_text) > 28 else "")
                    database.update_conversation_title(convo_id, short_title)
                    self.run_on_ui_thread(lambda: self.title_label.config(text=short_title))
                    convo_iid = f"convo_{convo_id}"
                    self.run_on_ui_thread(lambda: self.tree.item(convo_iid, text=f"  💬  {short_title}") if self.tree.exists(convo_iid) else None)

                # Phase 3: Build Grounded Context with Metadata for Context Inspector
                smart_context, context_meta = retrieval_service.build_ai_context_full(
                    project_id=project_id,
                    conversation_id=convo_id,
                    user_query=user_text,
                    query_embedding=query_emb
                )

                system_prompt = f"""Bạn là trợ lý AI quản lý dự án nội bộ (Local AI Project Assistant & Code Intelligence).
Mô hình chạy local: {CHAT_MODEL}.

Trách nhiệm chính:
- Hiểu và phân tích mã nguồn, tài liệu dự án (Project Knowledge / File RAG)
- Quản lý dự án, tracking quyết định & kiến trúc hệ thống
- Hỗ trợ lập trình, sửa lỗi và nghiên cứu kỹ thuật

QUY TẮC CỐT LÕI VỀ NGUỒN VÀ ĐỘ TIN CẬY (CODE VERSION PRIORITY):
1. Trả lời bằng tiếng Việt làm ngôn ngữ chính.
2. THỨ TỰ ƯU TIÊN VỀ HIỆN TRẠNG KỸ THUẬT CỦA DỰ ÁN:
   Mã nguồn/Tài liệu dự án hiện tại (Project Knowledge) > Ghi nhớ nội bộ (Project Memory) > Tóm tắt dự án > Lịch sử trò chuyện cũ > Kiến thức chung của mô hình.
3. Khi câu hỏi liên quan đến mã nguồn hoặc logic dự án:
   - LUÔN căn cứ vào phần DỮ LIỆU TÀI LIỆU & MÃ NGUỒN DỰ ÁN (PROJECT KNOWLEDGE) được cung cấp.
   - Tuyệt đối không tự suy diễn hoặc bịa đặt mã nguồn không có trong ngữ cảnh. Nếu mã nguồn chưa đủ, hãy nói rõ.
   - Nếu mã nguồn hiện tại mâu thuẫn với thảo luận trong lịch sử chat cũ, HÃY ƯU TIÊN mã nguồn hiện tại.
4. TRÍCH DẪN NGUỒN DỰ ÁN:
   - Khi câu trả lời dựa trên mã nguồn/tài liệu dự án, hãy trích dẫn ngắn gọn ở cuối dòng:
     Nguồn dự án:
     - [Đường dẫn file] — lines X–Y
5. QUY TẮC WEB SEARCH:
   - CHỈ gọi `web_search` khi câu hỏi yêu cầu thông tin mới nhất hiện nay, phiên bản phần mềm ngoài đời thực, hoặc tài liệu trực tuyến của bên thứ ba.
   - KHÔNG gọi `web_search` cho các câu hỏi về mã nguồn/nội bộ dự án của tôi.

6. GIAO THỨC HỎI Ý KIẾN VÀ XÁC NHẬN HÀNH ĐỘNG QUAN TRỌNG (HUMAN-IN-THE-LOOP ACTION CONFIRMATION PROTOCOL):
   Bạn là trợ lý AI an toàn, minh bạch và có trách nhiệm.
   BẠN BẮT BUỘC PHẢI GIẢI THÍCH VÀ HỎI Ý KIẾN XÁC NHẬN TỪ NGƯỜI DÙNG trước khi thực hiện hoặc đề xuất thực hiện bất kỳ hành động nào thuộc các trường hợp quan trọng, khó, hoặc KHÔNG THỂ KHÔI PHỤC sau đây:
   - NHÓM 1 (TỆP TIN & MÃ NGUỒN): Xoá tệp tin, xoá thư mục, ghi đè (overwrite) code hoặc file cấu hình quan trọng (.env, database, config...) làm mất dữ liệu cũ.
   - NHÓM 2 (LỆNH TERMINAL & SHELL HỆ THỐNG): Các lệnh nguy hiểm như xoá dữ liệu (rm, del), format ổ đĩa, sửa registry Windows, kill tiến trình/service hệ thống, gỡ bỏ thư viện toàn cục (pip uninstall).
   - NHÓM 3 (GIT & QUẢN LÝ PHIÊN BẢN): Các lệnh git gây mất code như `git reset --hard`, `git clean -fd`, `git push --force`, xoá nhánh (`git branch -D`).
   - NHÓM 4 (CƠ SỞ DỮ LIỆU & DATABASE): DROP TABLE, TRUNCATE, DELETE toàn bộ bảng, reset database hoặc xoá toàn bộ bộ nhớ dự án (Project Memory Wipe).
   - NHÓM 5 (BẢO MẬT & DỮ LIỆU NHẠY CẢM): Gửi mật khẩu, API keys, token hoặc source code bí mật ra các dịch vụ bên thứ ba.
   - NHÓM 6 (TÀI NGUYÊN HỆ THỐNG NẶNG): Các tác vụ chiếm dụng 100% CPU/GPU kéo dài như train lại toàn bộ kho tài liệu lớn hoặc chạy benchmark phần cứng.

   ĐỐI VỚI CÁC TRƯỜNG HỢP TRÊN, BẠN KHÔNG ĐƯỢC TỰ Ý THỰC HIỆN. BẠN BẮT BUỘC PHẢI:
   1. Giải thích rõ cho người dùng: Bạn muốn làm gì, tại sao cần làm, và mức độ rủi ro ra sao (không thể khôi phục).
   2. Xuất một khối `action_proposal` theo ĐÚNG ĐỊNH DẠNG JSON SAU để giao diện tự động hiển thị 2 nút [Cancel] và [Apply]:
   ```action_proposal
   {
     "title": "Tên ngắn gọn hành động (Ví dụ: Xoá tệp tin cấu hình cũ config_old.json)",
     "action_type": "file_delete | file_overwrite | run_command | git_destructive | db_delete | security_sensitive | resource_heavy",
     "target": "Đường dẫn file, lệnh terminal hoặc đối tượng tác động",
     "reason": "Giải thích chi tiết lý do tại sao cần làm việc này và lợi ích cho dự án",
     "risk": "Cảnh báo cụ thể về mức độ rủi ro (Ví dụ: NGUY HIỂM - Không thể hoàn tác sau khi xoá!)",
     "payload": "Lệnh hoặc nội dung thực thi cụ thể"
   }
   ```
   LƯU Ý: Việc thường ngày (đọc file, giải thích code, gợi ý lập trình, tra cứu web...) thì TRẢ LỜI BÌNH THƯỜNG, KHÔNG TẠO action_proposal.


NGỮ CẢNH DỰ ÁN ĐƯỢC TRUY XUẤT:
{smart_context if smart_context else "Chưa có ghi nhớ hoặc mã nguồn liên quan."}
"""

                recent_msgs = database.get_recent_messages_for_ai(convo_id, limit=RECENT_MESSAGES_LIMIT)
                messages_for_ai = [{"role": "system", "content": system_prompt}]
                for role, content in recent_msgs:
                    messages_for_ai.append({"role": role, "content": content})

                def tool_executor(name, args):
                    if name == "web_search":
                        query = args.get("query", "")
                        web_queries_called.append(query)
                        results = web_service.web_search(query, project_id=project_id, conversation_id=convo_id)
                        return json.dumps(results, ensure_ascii=False)
                    elif name == "web_fetch":
                        url = args.get("url", "")
                        page_data = web_service.web_fetch(url, project_id=project_id, conversation_id=convo_id)
                        return json.dumps(page_data, ensure_ascii=False)
                    return json.dumps({"error": f"Công cụ '{name}' không tồn tại."})

                def on_tool_status(name, args):
                    if name == "web_search":
                        q = args.get("query", "")[:35]
                        self.run_on_ui_thread(lambda: self.set_ui_status(f"🌐 Đang tìm web: {q}...", THEME["status_busy"]))
                    elif name == "web_fetch":
                        u = args.get("url", "")[:35]
                        self.run_on_ui_thread(lambda: self.set_ui_status(f"🌐 Đang đọc trang: {u}...", THEME["status_busy"]))
                    elif name == "synthesize":
                        self.run_on_ui_thread(lambda: self.set_ui_status("Đang tổng hợp kết quả...", THEME["status_busy"]))

                def on_token_received(token):
                    accumulated_stream.append(token)
                    def update_stream():
                        if not has_started_stream[0]:
                            has_started_stream[0] = True
                            self.set_ui_status("Đang trả lời...", THEME["status_busy"])
                        
                        full_curr = "".join(accumulated_stream)
                        if hasattr(streaming_bubble, "_lbl_body"):
                            streaming_bubble._lbl_body.config(text=full_curr)
                        self.chat_box.see(tk.END)

                    self.run_on_ui_thread(update_stream)

                tools_to_pass = ollama_client.TOOLS_SPEC if WEB_SEARCH_ENABLED else None

                # Execute bounded streaming tool calling
                answer, used_web = ollama_client.run_chat_with_tools_streaming(
                    messages=messages_for_ai,
                    tool_executor=tool_executor,
                    tools=tools_to_pass,
                    on_token_callback=on_token_received,
                    on_tool_status_callback=on_tool_status,
                    cancel_event=self.cancel_event
                )

                self._used_web_flag = used_web
                context_meta["used_web"] = used_web
                context_meta["web_queries"] = web_queries_called

                database.save_message(convo_id, "assistant", answer)

                def on_success():
                    try:
                        streaming_bubble.destroy()
                    except Exception:
                        pass
                    
                    self.chat_box.config(state=tk.NORMAL)
                    final_bubble = self._render_message_chunk("assistant", answer, context_meta=context_meta)
                    self.chat_box.config(state=tk.DISABLED)
                    self.chat_box.see(tk.END)
                    self._finish_processing()

                self.run_on_ui_thread(on_success)

            except ollama_client.GenerationCancelled:
                def on_cancel():
                    partial_text = "".join(accumulated_stream)
                    if hasattr(streaming_bubble, "_lbl_body"):
                        streaming_bubble._lbl_body.config(text=(partial_text + "\n\n[⏹ Đã dừng phản hồi bởi người dùng]"), fg="#f87171")
                    if partial_text:
                        database.save_message(convo_id, "assistant", partial_text + " [Đã dừng]")
                    self._finish_processing()
                    self.set_ui_status("Đã dừng phản hồi.", THEME["status_ready"])
                self.run_on_ui_thread(on_cancel)

            except Exception as e:
                def on_error():
                    if hasattr(streaming_bubble, "_lbl_body"):
                        streaming_bubble._lbl_body.config(text=f"❌ [Lỗi]: {e}", fg=THEME["status_err"])
                    self._finish_processing()
                    self.set_ui_status("Có lỗi xảy ra", THEME["status_err"])
                self.run_on_ui_thread(on_error)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_processing(self):
        """Restore buttons and idle state after processing."""
        self.stop_button.pack_forget()
        self.send_button.pack(fill=tk.BOTH, expand=True)
        self.is_processing = False
        self.set_ui_status("Sẵn sàng", THEME["status_ready"])
        self.input_box.focus_set()

    def _handle_memory_command(self, full_command, memory_text):
        self.chat_box.config(state=tk.NORMAL)
        self._render_message_chunk("user", full_command)
        self.chat_box.config(state=tk.DISABLED)
        self.chat_box.see(tk.END)

        self.set_ui_status("Đang ghi nhớ...", THEME["status_busy"])
        project_id = self.current_project_id

        def mem_worker():
            try:
                memory_service.save_memory(project_id, memory_text)
                cur_proj = database.get_project(project_id)
                proj_name = cur_proj[1] if cur_proj else "hiện tại"

                def finish_mem():
                    self.chat_box.config(state=tk.NORMAL)
                    self._render_message_chunk("assistant", f"Đã ghi nhớ thông tin vào dự án [{proj_name}]:\n`{memory_text}`")
                    self.chat_box.config(state=tk.DISABLED)
                    self.chat_box.see(tk.END)
                    self.set_ui_status("Sẵn sàng", THEME["status_ready"])

                self.run_on_ui_thread(finish_mem)
            except Exception as e:
                self.run_on_ui_thread(lambda: self.set_ui_status(f"Lỗi ghi nhớ: {e}", THEME["status_err"]))

        threading.Thread(target=mem_worker, daemon=True).start()


def main():
    root = tk.Tk()
    app = LocalAIApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
