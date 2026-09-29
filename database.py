"""
database.py - SQLite database layer for Local AI.
Supports Projects, Project Memories, Project Summaries, Conversations, Messages,
Web Cache, Web Retrieval Audit Log, and Project Knowledge (Sources, Files, Chunks).
"""
import os
import sqlite3
import json
from config import (
    DB_PATH,
    DEFAULT_PROJECT_NAME,
    UI_MESSAGE_PAGE_SIZE,
    WEB_SEARCH_CACHE_TTL_MINUTES,
    WEB_FETCH_CACHE_TTL_MINUTES
)

def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """
    Initialize database schema, apply migrations safely, and create indexes.
    Preserves all existing data across all tables.
    """
    conn = db_connect()
    cur = conn.cursor()

    # 1. Projects table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Ensure default project exists
    cur.execute("SELECT id FROM projects WHERE name = ?", (DEFAULT_PROJECT_NAME,))
    default_proj = cur.fetchone()
    if not default_proj:
        cur.execute(
            "INSERT INTO projects (name, description) VALUES (?, ?)",
            (DEFAULT_PROJECT_NAME, "Không gian làm việc mặc định")
        )
        default_project_id = cur.lastrowid
    else:
        default_project_id = default_proj[0]

    # 2. Conversations table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            embedding TEXT,
            embedding_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("PRAGMA table_info(conversations)")
    conv_cols = [c[1] for c in cur.fetchall()]
    if "project_id" not in conv_cols:
        print("[Migration] Adding project_id column to conversations table...")
        cur.execute("ALTER TABLE conversations ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE")
        cur.execute(
            "UPDATE conversations SET project_id = ? WHERE project_id IS NULL",
            (default_project_id,)
        )

    # 3. Messages table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        )
    """)

    # 4. Project Memories table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS project_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT,
            importance INTEGER DEFAULT 5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)

    # 5. Project Summaries table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS project_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, category),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)

    # 6. Web Cache table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS web_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cache_key TEXT NOT NULL UNIQUE,
            cache_type TEXT NOT NULL,
            url TEXT,
            query TEXT,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        )
    """)

    # 7. Web Retrieval Audit Log
    cur.execute("""
        CREATE TABLE IF NOT EXISTS web_retrieval_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER,
            project_id INTEGER,
            query TEXT,
            url TEXT,
            source_title TEXT,
            retrieved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 8. Project Knowledge: Sources table (Step 2)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS project_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            source_type TEXT NOT NULL,
            root_path TEXT NOT NULL,
            display_name TEXT,
            enabled INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)

    # 9. Project Knowledge: Files table (Step 2)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS project_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            extension TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            modified_time REAL NOT NULL,
            file_hash TEXT,
            indexing_status TEXT DEFAULT 'pending',
            last_indexed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, file_path),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(source_id) REFERENCES project_sources(id) ON DELETE CASCADE
        )
    """)

    # 10. Project Knowledge: Chunks table (Step 2)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS project_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            file_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT,
            metadata_json TEXT,
            token_estimate INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(file_id, chunk_index),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(file_id) REFERENCES project_files(id) ON DELETE CASCADE
        )
    """)

    # 11. Database Indexes (Step 3)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_convo_id ON messages(conversation_id, id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_conversations_proj_updated ON conversations(project_id, updated_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_project_memories_proj ON project_memories(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_project_summaries_proj_cat ON project_summaries(project_id, category)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_web_cache_key ON web_cache(cache_key)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_web_cache_expires ON web_cache(expires_at)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_web_log_proj ON web_retrieval_log(project_id)")

    # Knowledge indexes (Step 3)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_project_sources_proj ON project_sources(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_project_files_proj_src ON project_files(project_id, source_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_project_files_proj_path ON project_files(project_id, file_path)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_project_chunks_proj_file ON project_chunks(project_id, file_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_project_chunks_file_idx ON project_chunks(file_id, chunk_index)")

    conn.commit()
    conn.close()


# ============================================================
# PROJECT OPERATIONS
# ============================================================

def create_project(name, description=""):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO projects (name, description, created_at, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (name.strip(), description.strip()))
    proj_id = cur.lastrowid
    conn.commit()
    conn.close()
    return proj_id


def get_projects():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, description, created_at, updated_at
        FROM projects
        ORDER BY updated_at DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_project(project_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT id, name, description, created_at, updated_at FROM projects WHERE id = ?", (project_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_or_create_default_project():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM projects WHERE name = ?", (DEFAULT_PROJECT_NAME,))
    row = cur.fetchone()
    if row:
        proj_id = row[0]
    else:
        cur.execute("INSERT INTO projects (name, description) VALUES (?, ?)", (DEFAULT_PROJECT_NAME, "Không gian mặc định"))
        proj_id = cur.lastrowid
        conn.commit()
    conn.close()
    return proj_id


# ============================================================
# CONVERSATION OPERATIONS
# ============================================================

def create_conversation(project_id, title="Trò chuyện mới"):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO conversations (project_id, title, embedding_count, created_at, updated_at)
        VALUES (?, ?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (project_id, title))
    conversation_id = cur.lastrowid
    cur.execute("UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()
    return conversation_id


def get_conversations(project_id, limit=30, offset=0):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, updated_at
        FROM conversations
        WHERE project_id = ?
        ORDER BY updated_at DESC
        LIMIT ? OFFSET ?
    """, (project_id, limit, offset))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_conversation_count(project_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM conversations WHERE project_id = ?", (project_id,))
    count = cur.fetchone()[0]
    conn.close()
    return count


def get_conversation(conversation_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, project_id, title, embedding, embedding_count, updated_at
        FROM conversations
        WHERE id = ?
    """, (conversation_id,))
    row = cur.fetchone()
    conn.close()
    return row


def update_conversation_title(conversation_id, first_message):
    title = first_message.strip().replace("\n", " ")
    if len(title) > 45:
        title = title[:45] + "..."
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        UPDATE conversations
        SET title = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (title, conversation_id))
    conn.commit()
    conn.close()


def update_conversation_embedding_db(conversation_id, averaged_embedding, new_count):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        UPDATE conversations
        SET embedding = ?, embedding_count = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (json.dumps(averaged_embedding), new_count, conversation_id))
    conn.commit()
    conn.close()


# ============================================================
# MESSAGE OPERATIONS (KEYSET PAGINATION)
# ============================================================

def save_message(conversation_id, role, content, embedding=None):
    conn = db_connect()
    cur = conn.cursor()
    embedding_json = json.dumps(embedding) if embedding is not None else None
    cur.execute("""
        INSERT INTO messages (conversation_id, role, content, embedding, created_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (conversation_id, role, content, embedding_json))
    msg_id = cur.lastrowid
    cur.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (conversation_id,))
    cur.execute("""
        UPDATE projects
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = (SELECT project_id FROM conversations WHERE id = ?)
    """, (conversation_id,))
    conn.commit()
    conn.close()
    return msg_id


def get_messages_latest(conversation_id, limit=UI_MESSAGE_PAGE_SIZE):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, role, content
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (conversation_id, limit))
    rows = cur.fetchall()
    conn.close()
    rows.reverse()
    return rows


def get_messages_before(conversation_id, before_message_id, limit=UI_MESSAGE_PAGE_SIZE):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, role, content
        FROM messages
        WHERE conversation_id = ? AND id < ?
        ORDER BY id DESC
        LIMIT ?
    """, (conversation_id, before_message_id, limit))
    rows = cur.fetchall()
    conn.close()
    rows.reverse()
    return rows


def get_recent_messages_for_ai(conversation_id, limit=10):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT role, content
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (conversation_id, limit))
    rows = cur.fetchall()
    conn.close()
    rows.reverse()
    return rows


# ============================================================
# PROJECT MEMORY OPERATIONS
# ============================================================

def save_project_memory(project_id, content, embedding=None, importance=5):
    conn = db_connect()
    cur = conn.cursor()
    emb_json = json.dumps(embedding) if embedding else None
    cur.execute("""
        INSERT INTO project_memories (project_id, content, embedding, importance, created_at, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (project_id, content, emb_json, importance))
    mem_id = cur.lastrowid
    conn.commit()
    conn.close()
    return mem_id


def get_project_memories_raw(project_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, content, embedding, importance
        FROM project_memories
        WHERE project_id = ? AND embedding IS NOT NULL
    """, (project_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ============================================================
# PROJECT SUMMARY OPERATIONS
# ============================================================

def get_project_summary(project_id, category):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT content
        FROM project_summaries
        WHERE project_id = ? AND category = ?
    """, (project_id, category))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def save_project_summary(project_id, category, content):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO project_summaries (project_id, category, content, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(project_id, category) DO UPDATE SET
            content = excluded.content,
            updated_at = CURRENT_TIMESTAMP
    """, (project_id, category, content.strip()))
    conn.commit()
    conn.close()


def get_all_project_summaries(project_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT category, content, updated_at
        FROM project_summaries
        WHERE project_id = ?
        ORDER BY category ASC
    """, (project_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ============================================================
# WEB CACHE & RETRIEVAL LOG OPERATIONS
# ============================================================

def get_web_cache(cache_key, *args, **kwargs):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT content
        FROM web_cache
        WHERE cache_key = ? AND expires_at > CURRENT_TIMESTAMP
    """, (cache_key,))
    row = cur.fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row[0])
        except Exception:
            return row[0]
    return None


def set_web_cache(cache_key, cache_type, content, ttl_minutes=60, url=None, query=None, **kwargs):
    if "ttl_hours" in kwargs:
        ttl_minutes = int(kwargs["ttl_hours"] * 60)
    conn = db_connect()
    cur = conn.cursor()
    content_str = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content
    cur.execute("""
        INSERT INTO web_cache (cache_key, cache_type, url, query, content, created_at, expires_at)
        VALUES (
            ?, ?, ?, ?, ?,
            CURRENT_TIMESTAMP,
            datetime(CURRENT_TIMESTAMP, '+' || ? || ' minutes')
        )
        ON CONFLICT(cache_key) DO UPDATE SET
            content = excluded.content,
            created_at = CURRENT_TIMESTAMP,
            expires_at = datetime(CURRENT_TIMESTAMP, '+' || ? || ' minutes')
    """, (cache_key, cache_type, url, query, content_str, ttl_minutes, ttl_minutes))
    conn.commit()
    conn.close()


def log_web_retrieval(project_id, conversation_id, query=None, url=None, source_title=None):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO web_retrieval_log (conversation_id, project_id, query, url, source_title, retrieved_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (conversation_id, project_id, query, url, source_title))
    conn.commit()
    conn.close()


# ============================================================
# PROJECT KNOWLEDGE / FILE RAG OPERATIONS (STEPS 2, 3, 32, 34)
# ============================================================

def add_project_source(project_id, source_type, root_path, display_name=None):
    conn = db_connect()
    cur = conn.cursor()
    disp = display_name or os.path.basename(os.path.normpath(root_path))
    cur.execute("""
        INSERT INTO project_sources (project_id, source_type, root_path, display_name, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (project_id, source_type, os.path.normpath(root_path), disp))
    src_id = cur.lastrowid
    conn.commit()
    conn.close()
    return src_id


def get_project_sources(project_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, project_id, source_type, root_path, display_name, enabled, updated_at
        FROM project_sources
        WHERE project_id = ?
        ORDER BY id ASC
    """, (project_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def remove_project_source(source_id):
    conn = db_connect()
    cur = conn.cursor()
    # Cascades will delete associated project_files and project_chunks
    cur.execute("DELETE FROM project_sources WHERE id = ?", (source_id,))
    conn.commit()
    conn.close()


def upsert_project_file(
    project_id, source_id, file_path, relative_path, file_name,
    extension, file_size, modified_time, file_hash, indexing_status='pending'
):
    conn = db_connect()
    cur = conn.cursor()
    norm_path = os.path.normpath(file_path)
    cur.execute("""
        INSERT INTO project_files (
            project_id, source_id, file_path, relative_path, file_name,
            extension, file_size, modified_time, file_hash, indexing_status,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(project_id, file_path) DO UPDATE SET
            source_id = excluded.source_id,
            relative_path = excluded.relative_path,
            file_name = excluded.file_name,
            extension = excluded.extension,
            file_size = excluded.file_size,
            modified_time = excluded.modified_time,
            file_hash = excluded.file_hash,
            indexing_status = excluded.indexing_status,
            updated_at = CURRENT_TIMESTAMP
    """, (
        project_id, source_id, norm_path, relative_path, file_name,
        extension, file_size, modified_time, file_hash, indexing_status
    ))
    # Fetch file_id
    cur.execute("SELECT id FROM project_files WHERE project_id = ? AND file_path = ?", (project_id, norm_path))
    file_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return file_id


def get_project_file(project_id, file_path):
    conn = db_connect()
    cur = conn.cursor()
    norm_path = os.path.normpath(file_path)
    cur.execute("""
        SELECT id, project_id, source_id, file_path, relative_path, file_size, modified_time, file_hash, indexing_status
        FROM project_files
        WHERE project_id = ? AND file_path = ?
    """, (project_id, norm_path))
    row = cur.fetchone()
    conn.close()
    return row


def get_project_files_by_source(source_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, file_path, modified_time, file_size, file_hash, indexing_status
        FROM project_files
        WHERE source_id = ?
    """, (source_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_project_file_and_chunks(file_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM project_chunks WHERE file_id = ?", (file_id,))
    cur.execute("DELETE FROM project_files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()


def delete_file_chunks(file_id):
    """Delete chunks for file inside a transaction before inserting fresh chunks (Step 34)."""
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM project_chunks WHERE file_id = ?", (file_id,))
    conn.commit()
    conn.close()


def save_project_chunk(project_id, file_id, chunk_index, content, embedding, metadata_json, token_estimate=0):
    conn = db_connect()
    cur = conn.cursor()
    emb_json = json.dumps(embedding) if embedding else None
    meta_str = json.dumps(metadata_json, ensure_ascii=False) if isinstance(metadata_json, dict) else metadata_json
    cur.execute("""
        INSERT INTO project_chunks (
            project_id, file_id, chunk_index, content, embedding, metadata_json, token_estimate, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(file_id, chunk_index) DO UPDATE SET
            content = excluded.content,
            embedding = excluded.embedding,
            metadata_json = excluded.metadata_json,
            token_estimate = excluded.token_estimate,
            updated_at = CURRENT_TIMESTAMP
    """, (project_id, file_id, chunk_index, content, emb_json, meta_str, token_estimate))
    chunk_id = cur.lastrowid
    conn.commit()
    conn.close()
    return chunk_id


def mark_file_indexed(file_id, status='indexed'):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        UPDATE project_files
        SET indexing_status = ?, last_indexed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (status, file_id))
    conn.commit()
    conn.close()


def get_project_chunks_for_search(project_id):
    """
    Project-isolated chunk retrieval (Step 17 & 18).
    Strictly scoped to project_id at the SQL level before scoring.
    """
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.id, c.file_id, c.chunk_index, c.content, c.embedding, c.metadata_json, f.relative_path, f.file_name
        FROM project_chunks c
        JOIN project_files f ON c.file_id = f.id
        WHERE c.project_id = ? AND c.embedding IS NOT NULL
    """, (project_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_knowledge_summary_stats(project_id):
    """Retrieve quick stats: total files, indexed files, total chunks, skipped files."""
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM project_files WHERE project_id = ?", (project_id,))
    total_files = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM project_files WHERE project_id = ? AND indexing_status = 'indexed'", (project_id,))
    indexed_files = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM project_files WHERE project_id = ? AND indexing_status LIKE 'skipped%'", (project_id,))
    skipped_files = cur.fetchone()[0]

    cur.execute("SELECT count(*) FROM project_chunks WHERE project_id = ?", (project_id,))
    total_chunks = cur.fetchone()[0]

    conn.close()
    return {
        "total_files": total_files,
        "indexed_files": indexed_files,
        "skipped_files": skipped_files,
        "total_chunks": total_chunks
    }


# Helper alias
add_message = save_message

def add_project_memory(project_id, *args, **kwargs):
    content = ""
    if len(args) == 2:
        content = f"[{args[0]}] {args[1]}"
    elif len(args) == 1:
        content = args[0]
    elif "content" in kwargs:
        content = kwargs["content"]

    embedding = kwargs.get("embedding")
    if not embedding and content:
        try:
            import ollama_client
            embedding = ollama_client.get_embedding(content)
        except Exception:
            embedding = [0.0] * 768

    importance = kwargs.get("importance", 5)
    return save_project_memory(project_id, content, embedding=embedding, importance=importance)

def get_project_memories(project_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, content, importance, created_at
        FROM project_memories
        WHERE project_id = ?
    """, (project_id,))
    rows = cur.fetchall()
    conn.close()
    return [{"id": r[0], "content": r[1], "importance": r[2], "created_at": r[3]} for r in rows]

get_all_projects = get_projects


def delete_last_assistant_message(conversation_id):
    """Delete the most recent assistant message in conversation if user wants to regenerate."""
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM messages
        WHERE conversation_id = ? AND role = 'assistant'
        ORDER BY id DESC LIMIT 1
    """, (conversation_id,))
    row = cur.fetchone()
    if row:
        cur.execute("DELETE FROM messages WHERE id = ?", (row[0],))
        conn.commit()
        conn.close()
        return row[0]
    conn.close()
    return None

def get_last_user_message(conversation_id):
    """Retrieve the most recent user prompt in the conversation."""
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, content FROM messages
        WHERE conversation_id = ? AND role = 'user'
        ORDER BY id DESC LIMIT 1
    """, (conversation_id,))
    row = cur.fetchone()
    conn.close()
    return row if row else None


# ============================================================

# ============================================================
# PHASE 2: DATA MANAGEMENT & BỀN VỮNG METHODS
# ============================================================
import os
import shutil
import sqlite3
import datetime
from config import DB_PATH

def db_connect():
    return sqlite3.connect(DB_PATH)

def rename_project(project_id, new_name, new_description=None):
    """Update name and optional description for a project."""
    conn = db_connect()
    cur = conn.cursor()
    if new_description is not None:
        cur.execute("""
            UPDATE projects
            SET name = ?, description = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_name.strip(), new_description.strip(), project_id))
    else:
        cur.execute("""
            UPDATE projects
            SET name = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_name.strip(), project_id))
    conn.commit()
    conn.close()

def delete_project(project_id):
    """
    Safely delete a project and all associated cascading records in a single transaction:
    conversations, messages, project_memories, project_summaries, project_sources,
    project_files, and project_chunks.
    """
    conn = db_connect()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN TRANSACTION")
        
        # 1. Delete all messages in conversations belonging to this project
        cur.execute("""
            DELETE FROM messages
            WHERE conversation_id IN (
                SELECT id FROM conversations WHERE project_id = ?
            )
        """, (project_id,))
        
        # 2. Delete conversations
        cur.execute("DELETE FROM conversations WHERE project_id = ?", (project_id,))
        
        # 3. Delete project memories & summaries
        cur.execute("DELETE FROM project_memories WHERE project_id = ?", (project_id,))
        cur.execute("DELETE FROM project_summaries WHERE project_id = ?", (project_id,))
        
        # 4. Delete chunks and files belonging to project sources
        cur.execute("""
            DELETE FROM project_chunks
            WHERE file_id IN (
                SELECT pf.id FROM project_files pf
                JOIN project_sources ps ON pf.source_id = ps.id
                WHERE ps.project_id = ?
            )
        """, (project_id,))
        cur.execute("""
            DELETE FROM project_files
            WHERE source_id IN (
                SELECT id FROM project_sources WHERE project_id = ?
            )
        """, (project_id,))
        cur.execute("DELETE FROM project_sources WHERE project_id = ?", (project_id,))
        
        # 5. Delete project record
        cur.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise e
    finally:
        conn.close()

def rename_conversation(conversation_id, new_title):
    """Update title for a conversation."""
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        UPDATE conversations
        SET title = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (new_title.strip(), conversation_id))
    conn.commit()
    conn.close()

def delete_conversation(conversation_id):
    """Delete a conversation and all its messages in a single transaction."""
    conn = db_connect()
    cur = conn.cursor()
    try:
        cur.execute("BEGIN TRANSACTION")
        cur.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        cur.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise e
    finally:
        conn.close()

def update_project_memory(memory_id, new_content, importance=5):
    """Update a project memory fact and re-calculate embedding."""
    embedding = None
    try:
        import ollama_client
        embedding = ollama_client.get_embedding(new_content)
    except Exception:
        pass
    
    embedding_json = None
    if embedding:
        import json
        embedding_json = json.dumps(embedding)

    conn = db_connect()
    cur = conn.cursor()
    if embedding_json:
        cur.execute("""
            UPDATE project_memories
            SET content = ?, importance = ?, embedding = ?
            WHERE id = ?
        """, (new_content.strip(), int(importance), embedding_json, memory_id))
    else:
        cur.execute("""
            UPDATE project_memories
            SET content = ?, importance = ?
            WHERE id = ?
        """, (new_content.strip(), int(importance), memory_id))
    conn.commit()
    conn.close()

def delete_project_memory(memory_id):
    """Delete a single project memory item."""
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM project_memories WHERE id = ?", (memory_id,))
    conn.commit()
    conn.close()

def backup_database(destination_path=None):
    """
    Safely backup the active SQLite database using SQLite's native online backup API.
    Guarantees no database corruption even during active reads.
    Returns the absolute path of the created backup file.
    """
    if not destination_path:
        backups_dir = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")
        os.makedirs(backups_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        destination_path = os.path.join(backups_dir, f"local_ai_backup_{timestamp}.db")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(destination_path)), exist_ok=True)

    src_conn = sqlite3.connect(DB_PATH)
    dst_conn = sqlite3.connect(destination_path)
    try:
        with dst_conn:
            src_conn.backup(dst_conn, pages=100)
    finally:
        dst_conn.close()
        src_conn.close()

    return destination_path

def restore_database(source_path):
    """
    Safely restore SQLite database from backup file.
    Verifies SQLite integrity before applying restore.
    Creates a pre-restore safety copy (.bak_before_restore).
    """
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"Tệp sao lưu không tồn tại: {source_path}")

    # Check integrity of source backup file
    test_conn = sqlite3.connect(source_path)
    cur = test_conn.cursor()
    cur.execute("PRAGMA integrity_check")
    result = cur.fetchone()
    test_conn.close()

    if not result or result[0] != "ok":
        raise ValueError(f"Tệp sao lưu bị lỗi hoặc hỏng: {result}")

    # Create safety backup of current active database
    pre_restore_backup = f"{DB_PATH}.bak_before_restore"
    shutil.copy2(DB_PATH, pre_restore_backup)

    # Perform online restore from source into active DB
    src_conn = sqlite3.connect(source_path)
    dst_conn = sqlite3.connect(DB_PATH)
    try:
        with dst_conn:
            src_conn.backup(dst_conn, pages=100)
    finally:
        src_conn.close()
        dst_conn.close()

    return True

def optimize_database():
    """
    Maintenance task:
    1. Cleans expired web caches
    2. Removes orphan project chunks
    3. Executes SQLite VACUUM and PRAGMA optimize
    Returns dict with before_size, after_size, and freed_bytes.
    """
    before_size = os.path.getsize(DB_PATH) if os.path.isfile(DB_PATH) else 0

    conn = db_connect()
    cur = conn.cursor()
    try:
        # Delete expired web caches
        cur.execute("DELETE FROM web_cache WHERE expires_at IS NOT NULL AND expires_at < CURRENT_TIMESTAMP")
        
        # Delete orphan chunks
        cur.execute("""
            DELETE FROM project_chunks
            WHERE file_id NOT IN (SELECT id FROM project_files)
        """)
        conn.commit()
    finally:
        conn.close()

    # VACUUM requires autocommit connection (no open transaction)
    vac_conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        vac_conn.execute("VACUUM")
        vac_conn.execute("PRAGMA optimize")
    finally:
        vac_conn.close()

    after_size = os.path.getsize(DB_PATH) if os.path.isfile(DB_PATH) else 0
    freed_bytes = max(0, before_size - after_size)

    return {
        "before_bytes": before_size,
        "after_bytes": after_size,
        "freed_bytes": freed_bytes
    }


# ============================================================
# PHASE 3: SEARCH CHAT, EXPORT MARKDOWN & FILE LOOKUP
# ============================================================
import os
import sqlite3
import datetime
from config import DB_PATH

def db_connect():
    return sqlite3.connect(DB_PATH)

def get_file_path_by_relative_path(project_id, relative_path):
    """Lookup the absolute file path for a relative path within a project."""
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT file_path FROM project_files
        WHERE project_id = ? AND relative_path = ?
        LIMIT 1
    """, (project_id, relative_path))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def search_chat_history(query, project_id=None, limit=40):
    """
    Search messages containing query string across conversations.
    Returns list of dicts: {conversation_id, conversation_title, project_id, project_name, snippet, created_at}
    """
    if not query or not query.strip():
        return []
    conn = db_connect()
    cur = conn.cursor()
    like_query = f"%{query.strip()}%"
    if project_id:
        cur.execute("""
            SELECT m.id, m.conversation_id, c.title, p.id, p.name, m.content, m.created_at
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            JOIN projects p ON c.project_id = p.id
            WHERE p.id = ? AND m.content LIKE ?
            ORDER BY m.id DESC LIMIT ?
        """, (project_id, like_query, limit))
    else:
        cur.execute("""
            SELECT m.id, m.conversation_id, c.title, p.id, p.name, m.content, m.created_at
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            JOIN projects p ON c.project_id = p.id
            WHERE m.content LIKE ?
            ORDER BY m.id DESC LIMIT ?
        """, (like_query, limit))
    rows = cur.fetchall()
    conn.close()
    results = []
    for r in rows:
        results.append({
            "message_id": r[0],
            "conversation_id": r[1],
            "conversation_title": r[2],
            "project_id": r[3],
            "project_name": r[4],
            "snippet": r[5][:120].replace("\n", " "),
            "created_at": r[6]
        })
    return results

def export_conversation_markdown(conversation_id, destination_path=None):
    """Export all messages of a conversation to a well-formatted markdown document."""
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.title, p.name, c.created_at
        FROM conversations c
        JOIN projects p ON c.project_id = p.id
        WHERE c.id = ?
    """, (conversation_id,))
    conv_info = cur.fetchone()
    if not conv_info:
        conn.close()
        raise ValueError(f"Không tìm thấy cuộc trò chuyện #{conversation_id}")
    
    title, proj_name, created_time = conv_info
    
    cur.execute("""
        SELECT role, content, created_at
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id ASC
    """, (conversation_id,))
    messages = cur.fetchall()
    conn.close()
    
    lines = [
        f"# {title}",
        f"- **Dự án:** {proj_name}",
        f"- **Thời gian khởi tạo:** {created_time}",
        f"- **Thời gian xuất tài liệu:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "\n---\n"
    ]
    
    for role, content, msg_time in messages:
        sender = "👤 Bạn" if role == "user" else "🤖 AI Assistant"
        t_str = f" *({msg_time})*" if msg_time else ""
        lines.append(f"### {sender}{t_str}\n\n{content}\n\n---\n")
        
    md_text = "\n".join(lines)
    if destination_path:
        with open(destination_path, "w", encoding="utf-8") as f:
            f.write(md_text)
            
    return md_text
