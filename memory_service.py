"""
memory_service.py - Project-scoped memory management and semantic memory search.
Command format: nhớ: <content>
"""
import json
import re
from config import MEMORY_RESULTS_LIMIT, SIMILARITY_THRESHOLD
import database
import ollama_client

def parse_memory_command(text):
    """
    Checks if text is a memory command like 'nhớ: <content>' or 'nho: <content>'.
    Returns content string if matched, else None.
    """
    if not text:
        return None
    match = re.match(r"^\s*(?:nhớ|nho)\s*:\s*(.+)$", text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def save_memory(project_id, content, importance=5):
    """
    Generate embedding and store memory under the given project_id.
    """
    emb = ollama_client.get_embedding(content)
    mem_id = database.save_project_memory(
        project_id=project_id,
        content=content,
        embedding=emb,
        importance=importance
    )
    return mem_id


def search_project_memories(project_id, query_embedding, limit=MEMORY_RESULTS_LIMIT):
    """
    Semantically search memories strictly scoped to project_id.
    Never searches across other projects.
    Returns list of (score, content, importance).
    """
    if not query_embedding or not project_id:
        return []

    rows = database.get_project_memories_raw(project_id)
    scored = []

    for mem_id, content, emb_json, importance in rows:
        try:
            emb = json.loads(emb_json)
            score = ollama_client.cosine_similarity(query_embedding, emb)
            if score >= SIMILARITY_THRESHOLD:
                scored.append((score, content, importance))
        except Exception:
            continue

    scored.sort(reverse=True, key=lambda x: x[0])
    return scored[:limit]
