APP_NAME = "ino"
"""
config.py - Central configuration constants for Local AI Assistant.
Optimized for Intel i5-9300H, 16GB RAM, NVIDIA GTX 1650 4GB.
"""
import os

# ============================================================
# OLLAMA CONFIGURATION
# ============================================================
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_EMBED_URL = "http://localhost:11434/api/embed"

CHAT_MODEL = "qwen3:4b-q4_K_M"
EMBED_MODEL = "nomic-embed-text"

# ============================================================
# PATHS
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "local_ai.db")

# ============================================================
# PERFORMANCE & CONTEXT LIMITS (CRITICAL FOR LONG-TERM SCALABILITY)
# ============================================================
UI_MESSAGE_PAGE_SIZE = 40          # Keyset pagination page size for UI chat view
RECENT_MESSAGES_LIMIT = 10         # Immediate conversation messages sent to Qwen (8-12)
RELATED_CONVERSATIONS_LIMIT = 3    # Stage 1 semantic search: max related conversations
SEMANTIC_RESULTS_LIMIT = 4         # Stage 2 semantic search: max relevant historical message pairs
MEMORY_RESULTS_LIMIT = 3           # Max project memories injected into AI context
CONTEXT_LENGTH = 8192              # Context window size in Ollama

# Semantic similarity threshold
SIMILARITY_THRESHOLD = 0.40

# Sidebar conversation limit per project before "Load more"
SIDEBAR_CONVERSATIONS_LIMIT = 30

# Default project name for migrations and initial state
DEFAULT_PROJECT_NAME = "General"

# Supported Project Summary Categories
SUMMARY_CATEGORIES = [
    "general",
    "architecture",
    "backend",
    "frontend",
    "mobile",
    "database",
    "routing",
    "ai",
    "project_management",
]

# ============================================================
# WEB SEARCH & TOOL CALLING CONFIGURATION
# ============================================================
WEB_SEARCH_ENABLED = True
WEB_SEARCH_RESULTS_LIMIT = 5
WEB_SEARCH_TIMEOUT = 8                  # Seconds
WEB_FETCH_TIMEOUT = 10                  # Seconds
WEB_FETCH_MAX_CHARS = 12000             # Maximum characters returned from page
WEB_SEARCH_CACHE_TTL_MINUTES = 15       # 15 minutes TTL for search results
WEB_FETCH_CACHE_TTL_MINUTES = 60        # 60 minutes TTL for page fetch cache
MAX_TOOL_CALLS_PER_USER_MESSAGE = 3     # Strict bound preventing infinite tool loops

# ============================================================
# PROJECT KNOWLEDGE / FILE RAG CONFIGURATION (STEPS 4, 5, 6, 9, 20, 31)
# ============================================================
PROJECT_KNOWLEDGE_ENABLED = True
MAX_INDEX_FILE_SIZE_MB = 5
INDEX_BATCH_SIZE = 10
CHUNK_TARGET_CHARS = 1800
CHUNK_OVERLAP_CHARS = 200
KNOWLEDGE_RESULTS_LIMIT = 5
MAX_KNOWLEDGE_CONTEXT_CHARS = 12000

SUPPORTED_FILE_EXTENSIONS = {
    # Code & Config
    ".py", ".cs", ".java", ".js", ".ts", ".tsx", ".jsx",
    ".cpp", ".c", ".h", ".hpp", ".go", ".rs", ".php", ".rb",
    ".swift", ".kt", ".kts", ".sql", ".md", ".txt", ".json",
    ".yaml", ".yml", ".xml", ".html", ".css", ".scss",
    ".ini", ".toml", ".env", ".config", ".csproj", ".sln",
    ".props", ".targets", ".csv",
    # Documents
    ".pdf",
}

IGNORED_DIRECTORIES = {
    ".git", ".vs", ".idea", ".vscode",
    "node_modules", "bin", "obj", "dist", "build",
    "coverage", "packages", "vendor", "__pycache__",
    ".next", ".nuxt", "target",
}

SYSTEM_PROMPT_TEMPLATE = """Bạn là trợ lý AI quản lý dự án nội bộ (Local AI Project Assistant & Code Intelligence).
Mô hình chạy local: {chat_model}.

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
   - Khi câu trả lời dựa trên mã nguồn/tài liệu dự án, hãy trích dẫn ngắn gọn ở cuối dạng:
     Nguồn dự án:
     - [Đường dẫn file] — lines X–Y

5. GIAO THỨC HỎI Ý KIẾN VÀ XÁC NHẬN HÀNH ĐỘNG QUAN TRỌNG (HUMAN-IN-THE-LOOP ACTION CONFIRMATION PROTOCOL):
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

"""
