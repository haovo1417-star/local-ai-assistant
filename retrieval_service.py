"""
retrieval_service.py - Project-scoped semantic retrieval, Knowledge RAG, and context builder.
Context Priority (Step 20):
User Request > Current Project > Project Memory > Project Summary >
Project Knowledge (Source/Docs) > Semantic Chat History > Recent Chat > Web
"""
import json
from config import (
    RELATED_CONVERSATIONS_LIMIT,
    SEMANTIC_RESULTS_LIMIT,
    SIMILARITY_THRESHOLD,
    SUMMARY_CATEGORIES,
    KNOWLEDGE_RESULTS_LIMIT,
    MAX_KNOWLEDGE_CONTEXT_CHARS
)
import database
import ollama_client
import memory_service
import web_service
import knowledge_service

# ============================================================
# CONVERSATION TOPIC EMBEDDING (INCREMENTAL AVERAGE)
# ============================================================

def update_topic_embedding(conversation_id, new_embedding):
    if new_embedding is None or conversation_id is None:
        return

    conv = database.get_conversation(conversation_id)
    if not conv:
        return

    _, _, _, old_emb_json, count, _ = conv

    if old_emb_json:
        try:
            old_emb = json.loads(old_emb_json)
            new_count = count + 1
            averaged = [
                ((old * count) + new) / new_count
                for old, new in zip(old_emb, new_embedding)
            ]
        except Exception:
            averaged = new_embedding
            new_count = 1
    else:
        averaged = new_embedding
        new_count = 1

    database.update_conversation_embedding_db(conversation_id, averaged, new_count)


# ============================================================
# TWO-STAGE PROJECT-SCOPED HISTORICAL RETRIEVAL
# ============================================================

def find_related_conversations(project_id, query_embedding, current_conversation_id, limit=RELATED_CONVERSATIONS_LIMIT):
    if not query_embedding or not project_id:
        return []

    conn = database.db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, embedding
        FROM conversations
        WHERE project_id = ? AND embedding IS NOT NULL
    """, (project_id,))
    rows = cur.fetchall()
    conn.close()

    scored = []
    for conv_id, title, emb_json in rows:
        try:
            emb = json.loads(emb_json)
            score = ollama_client.cosine_similarity(query_embedding, emb)
            if conv_id == current_conversation_id:
                score += 0.05

            if score >= SIMILARITY_THRESHOLD:
                scored.append((score, conv_id, title))
        except Exception:
            continue

    scored.sort(reverse=True, key=lambda x: x[0])
    return scored[:limit]


def find_related_messages(project_id, query_embedding, related_conversations, limit=SEMANTIC_RESULTS_LIMIT):
    if not query_embedding or not related_conversations:
        return []

    conv_ids = [item[1] for item in related_conversations]
    placeholders = ",".join("?" for _ in conv_ids)

    conn = database.db_connect()
    cur = conn.cursor()

    cur.execute(f"""
        SELECT id, conversation_id, content, embedding
        FROM messages
        WHERE role = 'user'
          AND embedding IS NOT NULL
          AND conversation_id IN ({placeholders})
    """, conv_ids)
    rows = cur.fetchall()

    scored = []
    for msg_id, conv_id, content, emb_json in rows:
        try:
            emb = json.loads(emb_json)
            score = ollama_client.cosine_similarity(query_embedding, emb)
            if score >= SIMILARITY_THRESHOLD:
                scored.append((score, msg_id, conv_id, content))
        except Exception:
            continue

    scored.sort(reverse=True, key=lambda x: x[0])

    results = []
    for score, msg_id, conv_id, user_content in scored[:limit]:
        cur.execute("""
            SELECT content
            FROM messages
            WHERE conversation_id = ? AND id > ? AND role = 'assistant'
            ORDER BY id ASC
            LIMIT 1
        """, (conv_id, msg_id))
        asst_row = cur.fetchone()
        assistant_content = asst_row[0] if asst_row else ""

        cur.execute("SELECT title FROM conversations WHERE id = ?", (conv_id,))
        title_row = cur.fetchone()
        title = title_row[0] if title_row else "Cuộc hội thoại"

        results.append({
            "score": score,
            "conversation": title,
            "user": user_content,
            "assistant": assistant_content
        })

    conn.close()
    return results


# ============================================================
# PROJECT SUMMARIES SELECTION
# ============================================================

CATEGORY_KEYWORDS = {
    "architecture": ["kiến trúc", "architecture", "hệ thống", "cấu trúc", "thiết kế", "pattern", "design"],
    "backend": ["backend", "server", "api", "asp.net", "c#", "node", "django", "fastapi", "service"],
    "frontend": ["frontend", "giao diện", "ui", "react", "vue", "tkinter", "css", "html", "web"],
    "mobile": ["mobile", "android", "ios", "flutter", "react native", "app di động"],
    "database": ["database", "csdl", "cơ sở dữ liệu", "postgres", "sql", "sqlite", "table", "bảng", "migration"],
    "routing": ["routing", "tuyến đường", "đường đi", "ors", "haversine", "bản đồ", "map", "tọa độ", "fallback"],
    "ai": ["ai", "mô hình", "model", "llm", "embedding", "qwen", "nomic", "ollama", "rag", "semantic"],
    "project_management": ["sprint", "kế hoạch", "tiến độ", "task", "jira", "deadline", "quản lý", "timeline"]
}

def get_relevant_summaries(project_id, user_query):
    summaries = []
    query_lower = user_query.lower() if user_query else ""

    gen_sum = database.get_project_summary(project_id, "general")
    if gen_sum:
        summaries.append(("general", gen_sum))

    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            cat_sum = database.get_project_summary(project_id, cat)
            if cat_sum:
                summaries.append((cat, cat_sum))

    return summaries


# ============================================================
# CONTEXT BUILDER (STEPS 13, 20, 21, 23 & PHASE 3 CONTEXT INSPECTOR)
# ============================================================

def build_ai_context_full(project_id, conversation_id, user_query="", query_embedding=None, **kwargs):
    if not query_embedding and user_query:
        try:
            query_embedding = ollama_client.get_embedding(user_query)
        except Exception:
            query_embedding = None

    sections = []
    metadata = {
        "project_id": project_id,
        "project_name": "Mặc định",
        "summaries": [],
        "memories": [],
        "rag_sources": [],
        "historical_count": 0,
        "sections_count": 0
    }

    # 1. Project profile
    proj = database.get_project(project_id)
    if proj:
        proj_name = proj[1]
        proj_desc = proj[2]
        metadata["project_name"] = proj_name
        sections.append(f"DỰ ÁN HIỆN TẠI: {proj_name}" + (f" - {proj_desc}" if proj_desc else ""))

    # 2. Project summaries
    summaries = get_relevant_summaries(project_id, user_query)
    if summaries:
        metadata["summaries"] = [{"category": cat, "content": c} for cat, c in summaries]
        sum_text = "TỔNG KẾT DỰ ÁN LIÊN QUAN:\n"
        for cat, c in summaries:
            sum_text += f"- [{cat.upper()}]: {c}\n"
        sections.append(sum_text.strip())

    # 3. Project memories
    if query_embedding:
        memories = memory_service.search_project_memories(project_id, query_embedding)
        if memories:
            metadata["memories"] = [
                {"score": round(score, 3), "content": c, "importance": imp}
                for score, c, imp in memories
            ]
            mem_text = "THÔNG TIN GHI NHỚ NỘI BỘ DỰ ÁN (PROJECT MEMORY):\n"
            for score, c, imp in memories:
                mem_text += f"- {c}\n"
            sections.append(mem_text.strip())

    # 4. Project Knowledge / File RAG
    if query_embedding:
        knowledge_chunks = knowledge_service.search_project_knowledge(project_id, query_embedding, limit=KNOWLEDGE_RESULTS_LIMIT)
        if knowledge_chunks:
            metadata["rag_sources"] = [
                {
                    "file_name": chunk.get("file_name", "file"),
                    "relative_path": chunk.get("relative_path", "file"),
                    "start_line": chunk.get("start_line", 1),
                    "end_line": chunk.get("end_line", 1),
                    "score": round(chunk.get("score", 0.0), 3)
                }
                for chunk in knowledge_chunks
            ]
            k_text = knowledge_service.format_knowledge_context(knowledge_chunks, max_chars=MAX_KNOWLEDGE_CONTEXT_CHARS)
            if k_text:
                sections.append("DỮ LIỆU TÀI LIỆU & MÃ NGUỒN DỰ ÁN (PROJECT KNOWLEDGE / FILE RAG):\n" + k_text)

    # 5. Historical semantic search results (two-stage)
    if query_embedding:
        related_convos = find_related_conversations(project_id, query_embedding, conversation_id)
        if related_convos:
            historical_msgs = find_related_messages(project_id, query_embedding, related_convos)
            if historical_msgs:
                metadata["historical_count"] = len(historical_msgs)
                hist_text = "DỮ LIỆU LỊCH SỬ TỪ CÁC CUỘC TRÒ CHUYỆN TRƯỚC:\n"
                for item in historical_msgs:
                    hist_text += f"\n[{item['conversation']}]\n"
                    hist_text += f"Người dùng: {item['user']}\n"
                    if item['assistant']:
                        hist_text += f"Trả lời trước đây: {item['assistant']}\n"
                sections.append(hist_text.strip())

    metadata["sections_count"] = len(sections)
    return "\n\n".join(sections), metadata


def build_ai_context(project_id, conversation_id, user_query="", query_embedding=None, **kwargs):
    """Backward compatible wrapper returning single context text."""
    context_text, _ = build_ai_context_full(
        project_id,
        conversation_id,
        user_query=user_query,
        query_embedding=query_embedding,
        **kwargs
    )
    return context_text
