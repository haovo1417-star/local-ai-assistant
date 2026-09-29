# LocalAI - Local AI Project Assistant & Code Intelligence

Ứng dụng trợ lý AI chạy hoàn toàn offline / local trên máy tính với giao diện Desktop Tkinter hiện đại, hỗ trợ RAG (Truy xuất tài liệu dự án), Web Search, Quản lý bộ nhớ dự án, và Giao thức Xác nhận Hành động An toàn (Human-in-the-Loop Approval).

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-orange.svg)
![SQLite](https://img.shields.io/badge/Database-SQLite-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

---

## 🌟 Điểm nổi bật & Tính năng chính

### 1. 🤖 Mô hình chạy hoàn toàn Local (Không rò rỉ dữ liệu)
- Tích hợp cục bộ với **Ollama** (`http://localhost:11434`).
- Mặc định sử dụng model chat: `qwen3:4b-q4_K_M` và embedding: `nomic-embed-text`.
- Không gửi code hoặc dữ liệu dự án lên cloud bên ngoài.

### 2. ⚡ Streaming & Dừng tức thì (Instant Stop)
- Streaming phản hồi từng token mượt mà theo thời gian thực.
- Nút **Stop ⏹** ngắt socket HTTP ngay lập tức để giải phóng tài nguyên GPU CUDA.

### 3. 🛡️ Giao thức Xác nhận Hành động An toàn (Human-in-the-Loop)
- AI được huấn luyện theo giao thức an toàn: **Bắt buộc phải hỏi ý kiến và giải thích rõ ràng** trước khi muốn thực hiện các thao tác quan trọng, khó hoặc không thể khôi phục (xoá file, ghi đè code, chạy lệnh terminal nguy hiểm, drop database, git reset...).
- Giao diện xuất hiện thẻ cảnh báo tương tác trực quan với 2 nút:
  - **✖ Cancel**: Từ chối hành động, AI tự động đổi sang giải pháp an toàn khác.
  - **✔ Apply**: Chấp thuận hành động để tiếp tục tiến trình.

### 4. 📚 Project Knowledge (Local RAG)
- Nạp thư mục hoặc từng file mã nguồn/tài liệu (`.py`, `.js`, `.ts`, `.html`, `.css`, `.json`, `.md`, `.txt`, `.pdf`).
- Chunking thông minh và lưu vector embedding cục bộ trong SQLite.
- Tự động trích xuất các đoạn mã liên quan nhất kèm điểm tương đồng Cosine khi bạn hỏi bài toán lập trình.

### 5. 🔍 Minh bạch Ngữ cảnh (Context Inspector & Source Viewer)
- Nút `🔍 Xem Context` dưới mỗi câu trả lời của AI giúp xem 100% ngữ cảnh AI đã nhận được (tên dự án, memory facts, nguồn tài liệu RAG, trạng thái web search).
- Xem trực tiếp nội dung file nguồn trên ổ đĩa kèm số dòng đánh dấu.

### 6. 🌐 Tích hợp Công cụ Web (Web Search & Fetch)
- Tự động tra cứu internet khi gặp câu hỏi về thông tin mới, phiên bản thư viện hoặc tài liệu trực tuyến của bên thứ ba.
- Cơ chế cache SQLite tránh tra cứu lặp lại.

### 7. 💾 Quản trị Dữ liệu & Cơ sở dữ liệu SQLite
- **Project Memory Manager**: Quản lý các sự thật kiến trúc (facts) của dự án.
- **Sao lưu & Phục hồi Online**: Backup và Restore `local_ai.db` trực tiếp ngay trong app.
- **Tối ưu hóa Database**: Dọn dẹp cache hết hạn, dọn RAG chunks mồ côi và chạy `VACUUM`.
- **Tìm kiếm Lịch sử Chat & Xuất Markdown**: Tìm kiếm tin nhắn theo từ khóa và xuất cuộc trò chuyện ra file `.md`.

---

## 🖥️ Yêu cầu Hệ thống

- **Hệ điều hành:** Windows 10/11, Linux, hoặc macOS.
- **Python:** 3.10 trở lên (khuyên dùng Python 3.11).
- **Phần cứng đề xuất:** CPU 4+ cores, RAM 16 GB, GPU NVIDIA 4 GB VRAM trở lên (hoặc chạy CPU).
- **Ollama:** Đã cài đặt và đang chạy tại cổng mặc định `11434`.

---

## 🚀 Hướng dẫn Cài đặt & Chạy ứng dụng

### Bước 1: Tải các model cần thiết trên Ollama
Mở terminal và chạy lệnh:
```bash
ollama pull qwen3:4b-q4_K_M
ollama pull nomic-embed-text
```

### Bước 2: Cài đặt thư viện Python
Trong thư mục dự án, chạy:
```bash
pip install -r requirements.txt
```

### Bước 3: Khởi chạy ứng dụng
```bash
python app.py
```

---

## 📁 Cấu trúc Dự án

```
C:/LocalAI/
├── app.py                     # Giao diện chính Tkinter, xử lý bong bóng chat & tương tác
├── config.py                  # Cấu hình model, theme màu sắc, đường dẫn & system prompt
├── database.py                # Quản lý SQLite, migration, project/convo CRUD, backup & vacuum
├── knowledge_service.py       # Quét file, chunking, trích xuất text PDF/code, index embeddings
├── memory_service.py          # Quản lý sự thật kiến trúc & bộ nhớ dài hạn của dự án
├── ollama_client.py           # Kết nối Ollama API, streaming token, tool calling, embeddings
├── retrieval_service.py       # Thuật toán tìm kiếm cosine similarity, xếp hạng & dựng context
├── web_service.py             # Tìm kiếm DuckDuckGo HTML & trích xuất văn bản web an toàn
├── requirements.txt           # Danh sách gói phụ thuộc (siêu nhẹ)
└── README.md                  # Hướng dẫn chi tiết dự án
```

---

## 📜 Giấy phép
Dự án được phân phối dưới giấy phép [MIT License](LICENSE).
