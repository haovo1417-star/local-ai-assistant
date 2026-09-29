"""
knowledge_service.py - Project Knowledge & File RAG Service.
Provides:
- Incremental folder & file scanning
- File change detection (mtime + size + SHA-256 hash)
- Structure-aware text/code chunking with line metadata
- PDF text extraction via pypdf
- Chunk embeddings via Ollama nomic-embed-text
- Project-isolated top-K semantic retrieval
- Source reference generation for grounded answers
"""
import os
import sys
import hashlib
import json
import re
import time

from config import (
    MAX_INDEX_FILE_SIZE_MB,
    INDEX_BATCH_SIZE,
    CHUNK_TARGET_CHARS,
    CHUNK_OVERLAP_CHARS,
    KNOWLEDGE_RESULTS_LIMIT,
    MAX_KNOWLEDGE_CONTEXT_CHARS,
    SUPPORTED_FILE_EXTENSIONS,
    IGNORED_DIRECTORIES,
    SIMILARITY_THRESHOLD
)
import database
import ollama_client

# Check for pypdf
try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


# ============================================================
# HASH & FILE CONTENT EXTRACTION (STEPS 8 & 11)
# ============================================================

def compute_file_sha256(file_path):
    """Compute SHA-256 hash of file contents in 64KB blocks."""
    hasher = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        print(f"[Hash Error] {file_path}: {e}")
        return None


def extract_file_content(file_path, extension):
    """
    Extract text content from file.
    Supports code/text and text-based PDFs.
    Returns (content_str, error_or_status).
    """
    ext = extension.lower()

    if ext == ".pdf":
        if not PYPDF_AVAILABLE:
            return None, "pypdf_not_installed"
        try:
            reader = pypdf.PdfReader(file_path)
            extracted_pages = []
            for idx, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    extracted_pages.append(f"--- Trang {idx + 1} ---\n" + page_text)
            full_text = "\n\n".join(extracted_pages).strip()
            if not full_text:
                return None, "no_extractable_text"
            return full_text, None
        except Exception as e:
            return None, f"pdf_error: {e}"

    # Text / Code / Config files
    encodings_to_try = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
    for enc in encodings_to_try:
        try:
            with open(file_path, "r", encoding=enc) as f:
                content = f.read()
            return content, None
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return None, f"read_error: {e}"

    return None, "unsupported_encoding"


# ============================================================
# CHUNKING STRATEGY WITH LINE METADATA (STEPS 9 & 10)
# ============================================================

CODE_STRUCTURE_REGEX = re.compile(
    r"^\s*(public|private|protected|internal|class|def|function|interface|namespace|struct|enum|record|async|export)\b",
    re.MULTILINE
)

def chunk_text_or_code(text, relative_path, file_name, extension):
    """
    Structure-aware chunking preserving accurate line ranges (start_line, end_line).
    Returns list of chunk dicts.
    """
    if not text or not text.strip():
        return []

    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    chunks = []

    current_chunk_lines = []
    current_chunk_chars = 0
    start_line = 1

    ext = extension.lower()
    is_code = ext in {".cs", ".py", ".ts", ".tsx", ".js", ".jsx", ".java", ".cpp", ".c", ".h", ".go", ".rs", ".sql"}

    for idx, line in enumerate(lines, start=1):
        line_len = len(line)

        # Check if line looks like a major structure boundary in code
        looks_like_boundary = bool(is_code and CODE_STRUCTURE_REGEX.match(line))

        # Check if chunk target reached
        if current_chunk_chars >= CHUNK_TARGET_CHARS and (looks_like_boundary or current_chunk_chars >= (CHUNK_TARGET_CHARS + 400)):
            chunk_content = "".join(current_chunk_lines).strip()
            if chunk_content:
                chunks.append({
                    "content": chunk_content,
                    "start_line": start_line,
                    "end_line": idx - 1,
                    "relative_path": relative_path,
                    "file_name": file_name,
                    "extension": extension,
                    "token_estimate": len(chunk_content) // 4
                })

            # Overlap: keep last few lines (~CHUNK_OVERLAP_CHARS)
            overlap_lines = []
            overlap_chars = 0
            for prev_line in reversed(current_chunk_lines):
                if overlap_chars + len(prev_line) > CHUNK_OVERLAP_CHARS:
                    break
                overlap_lines.insert(0, prev_line)
                overlap_chars += len(prev_line)

            current_chunk_lines = list(overlap_lines)
            current_chunk_chars = overlap_chars
            start_line = idx - len(overlap_lines)

        current_chunk_lines.append(line)
        current_chunk_chars += line_len

    # Final trailing chunk
    if current_chunk_lines:
        chunk_content = "".join(current_chunk_lines).strip()
        if chunk_content:
            chunks.append({
                "content": chunk_content,
                "start_line": start_line,
                "end_line": total_lines,
                "relative_path": relative_path,
                "file_name": file_name,
                "extension": extension,
                "token_estimate": len(chunk_content) // 4
            })

    return chunks


# ============================================================
# INCREMENTAL SCANNING & BATCH INDEXING (STEPS 7, 12, 13, 14, 32, 34)
# ============================================================

def notify_progress(cb, msg, idx=None, total=None, fn=None):
    if not cb:
        return
    try:
        if idx is not None and total is not None and fn is not None:
            try:
                cb(idx, total, fn)
                return
            except TypeError:
                pass
        cb(msg)
    except Exception:
        pass


def scan_and_index_source(project_id, source_id, progress_callback=None):
    """
    Scan folder or file source incrementally:
    - Checks mtime + size first
    - Checks SHA-256 hash if modified
    - Skips unchanged files (0 re-embeddings!)
    - Re-chunks & re-embeds changed files
    - Deletes stale chunks for removed files
    """
    conn = database.db_connect()
    cur = conn.cursor()
    cur.execute("SELECT root_path, source_type FROM project_sources WHERE id = ? AND project_id = ?", (source_id, project_id))
    src_row = cur.fetchone()
    conn.close()

    if not src_row:
        return {"error": "Source not found."}

    root_path, source_type = src_row
    root_path = os.path.normpath(root_path)

    if not os.path.exists(root_path):
        return {"error": f"Path '{root_path}' does not exist on disk."}

    files_to_process = []
    if source_type == "file":
        rel_path = os.path.basename(root_path)
        files_to_process.append((root_path, rel_path))
    else:
        # Walk folder skipping IGNORED_DIRECTORIES
        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRECTORIES and not d.startswith(".")]
            for fn in filenames:
                abs_p = os.path.normpath(os.path.join(dirpath, fn))
                rel_p = os.path.relpath(abs_p, root_path).replace("\\", "/")
                files_to_process.append((abs_p, rel_p))

    scanned_count = len(files_to_process)
    active_abs_paths = set(abs_p for abs_p, _ in files_to_process)

    # Clean up files deleted on disk
    existing_db_files = database.get_project_files_by_source(source_id)
    deleted_count = 0
    for fid, fpath, _, _, _, _ in existing_db_files:
        if fpath not in active_abs_paths:
            database.delete_project_file_and_chunks(fid)
            deleted_count += 1

    indexed_count = 0
    unchanged_count = 0
    skipped_count = 0
    total_new_chunks = 0

    max_size_bytes = MAX_INDEX_FILE_SIZE_MB * 1024 * 1024

    for idx, (abs_p, rel_p) in enumerate(files_to_process, start=1):
        if progress_callback:
            notify_progress(progress_callback, f"Đang quét file {idx} / {scanned_count}: {os.path.basename(abs_p)}", idx, scanned_count, os.path.basename(abs_p))

        fn = os.path.basename(abs_p)
        ext = os.path.splitext(fn)[1].lower()

        try:
            stat = os.stat(abs_p)
            f_size = stat.st_size
            f_mtime = stat.st_mtime
        except Exception:
            continue

        # Check supported file types
        if ext not in SUPPORTED_FILE_EXTENSIONS:
            database.upsert_project_file(
                project_id=project_id,
                source_id=source_id,
                file_path=abs_p,
                relative_path=rel_p,
                file_name=fn,
                extension=ext,
                file_size=f_size,
                modified_time=f_mtime,
                file_hash="",
                indexing_status="unsupported"
            )
            skipped_count += 1
            continue

        # Check file size limit
        if f_size > max_size_bytes:
            database.upsert_project_file(
                project_id=project_id,
                source_id=source_id,
                file_path=abs_p,
                relative_path=rel_p,
                file_name=fn,
                extension=ext,
                file_size=f_size,
                modified_time=f_mtime,
                file_hash=None,
                indexing_status="skipped_large"
            )
            skipped_count += 1
            continue

        # Check existing file metadata in DB
        db_file = database.get_project_file(project_id, abs_p)
        file_id = None
        needs_indexing = False

        if db_file:
            file_id = db_file[0]
            db_size = db_file[5]
            db_mtime = db_file[6]
            db_hash = db_file[7]
            db_status = db_file[8]

            # Fast path: mtime and size unchanged
            if db_mtime == f_mtime and db_size == f_size and db_status == "indexed":
                unchanged_count += 1
                continue

            # Modified or not yet indexed: compute SHA-256 hash
            curr_hash = compute_file_sha256(abs_p)
            if curr_hash == db_hash and db_status == "indexed":
                # Hash unchanged, just update mtime
                database.upsert_project_file(
                    project_id=project_id,
                    source_id=source_id,
                    file_path=abs_p,
                    relative_path=rel_p,
                    file_name=fn,
                    extension=ext,
                    file_size=f_size,
                    modified_time=f_mtime,
                    file_hash=curr_hash,
                    indexing_status="indexed"
                )
                unchanged_count += 1
                continue
            else:
                needs_indexing = True
                new_hash = curr_hash
        else:
            needs_indexing = True
            new_hash = compute_file_sha256(abs_p)

        if needs_indexing:
            text, err = extract_file_content(abs_p, ext)
            if err:
                database.upsert_project_file(
                    project_id=project_id,
                    source_id=source_id,
                    file_path=abs_p,
                    relative_path=rel_p,
                    file_name=fn,
                    extension=ext,
                    file_size=f_size,
                    modified_time=f_mtime,
                    file_hash=new_hash,
                    indexing_status=err
                )
                skipped_count += 1
                continue

            # Upsert file record
            file_id = database.upsert_project_file(
                project_id=project_id,
                source_id=source_id,
                file_path=abs_p,
                relative_path=rel_p,
                file_name=fn,
                extension=ext,
                file_size=f_size,
                modified_time=f_mtime,
                file_hash=new_hash,
                indexing_status="pending"
            )

            # Chunking with line metadata
            chunks = chunk_text_or_code(text, rel_p, fn, ext)

            # Delete old chunks for this file inside transaction before inserting new
            database.delete_file_chunks(file_id)

            # Generate embeddings and save chunks
            for c_idx, c_info in enumerate(chunks):
                if progress_callback:
                    progress_callback(f"Embedding {rel_p} (chunk {c_idx + 1}/{len(chunks)})...")

                emb = ollama_client.get_embedding(c_info["content"])
                database.save_project_chunk(
                    project_id=project_id,
                    file_id=file_id,
                    chunk_index=c_idx,
                    content=c_info["content"],
                    embedding=emb,
                    metadata_json={
                        "relative_path": c_info["relative_path"],
                        "file_name": c_info["file_name"],
                        "extension": c_info["extension"],
                        "start_line": c_info["start_line"],
                        "end_line": c_info["end_line"]
                    },
                    token_estimate=c_info["token_estimate"]
                )
                total_new_chunks += 1

            database.mark_file_indexed(file_id, "indexed")
            indexed_count += 1

    return {
        "scanned_files": scanned_count,
        "indexed_files": indexed_count,
        "unchanged_files": unchanged_count,
        "skipped_unchanged": unchanged_count,
        "skipped_files": skipped_count,
        "deleted_files": deleted_count,
        "total_new_chunks": total_new_chunks,
        "indexed_chunks": total_new_chunks
    }


def index_changed_files_for_project(project_id, progress_callback=None):
    """Scan and index all sources attached to project_id."""
    sources = database.get_project_sources(project_id)
    if not sources:
        return {"scanned_files": 0, "indexed_files": 0, "unchanged_files": 0, "skipped_files": 0, "total_new_chunks": 0}

    total_stats = {
        "scanned_files": 0,
        "indexed_files": 0,
        "unchanged_files": 0,
        "skipped_unchanged": 0,
        "skipped_files": 0,
        "deleted_files": 0,
        "total_new_chunks": 0,
        "indexed_chunks": 0
    }

    for src in sources:
        src_id = src[0]
        enabled = src[5]
        if enabled:
            res = scan_and_index_source(project_id, src_id, progress_callback=progress_callback)
            for k in total_stats:
                total_stats[k] += res.get(k, 0)

    return total_stats


# ============================================================
# PROJECT ISOLATED KNOWLEDGE RETRIEVAL (STEPS 17, 18, 19, 20)
# ============================================================

def search_project_knowledge(project_id, query_embedding, limit=KNOWLEDGE_RESULTS_LIMIT):
    """
    Project-isolated semantic search on indexed chunks.
    Only retrieves chunks WHERE project_id = ? at the SQL level.
    Returns list of dicts with content and line metadata.
    """
    if not query_embedding or not project_id:
        return []

    if isinstance(query_embedding, str):
        try:
            query_embedding = ollama_client.get_embedding(query_embedding)
        except Exception:
            return []

    rows = database.get_project_chunks_for_search(project_id)
    scored = []

    for c_id, f_id, c_idx, content, emb_json, meta_str, rel_path, f_name in rows:
        try:
            emb = json.loads(emb_json)
            score = ollama_client.cosine_similarity(query_embedding, emb)
            if score >= SIMILARITY_THRESHOLD:
                meta = json.loads(meta_str) if meta_str else {}
                scored.append({
                    "score": score,
                    "chunk_id": c_id,
                    "file_id": f_id,
                    "content": content,
                    "relative_path": rel_path or meta.get("relative_path", "unknown"),
                    "file_name": f_name or meta.get("file_name", "unknown"),
                    "start_line": meta.get("start_line", 1),
                    "end_line": meta.get("end_line", 1)
                })
        except Exception:
            continue

    scored.sort(reverse=True, key=lambda x: x["score"])
    return scored[:limit]


def format_knowledge_context(knowledge_results, max_chars=MAX_KNOWLEDGE_CONTEXT_CHARS):
    """Format retrieved knowledge chunks with clear line citations within character budget."""
    if not knowledge_results:
        return ""

    sections = []
    total_chars = 0

    for item in knowledge_results:
        header = f"[Tài liệu/Mã nguồn: {item['relative_path']} | Dòng: {item['start_line']}–{item['end_line']}]"
        chunk_text = f"{header}\n{item['content']}"

        if total_chars + len(chunk_text) > max_chars:
            remaining = max_chars - total_chars
            if remaining > 200:
                truncated = chunk_text[:remaining] + "\n[...Đoạn mã được cắt ngắn để đảm bảo giới hạn ngữ cảnh...]"
                sections.append(truncated)
            break

        sections.append(chunk_text)
        total_chars += len(chunk_text)

    return "\n\n".join(sections)


# Direct alias
index_changed_files = index_changed_files_for_project
