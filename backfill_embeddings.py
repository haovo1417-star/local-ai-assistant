"""
backfill_embeddings.py - Safe, bounded, interruptible maintenance utility.
Requirements:
- Does NOT run on app startup (manual utility only)
- Processes ONLY missing embeddings (WHERE embedding IS NULL)
- Never recomputes existing embeddings
- Processes in bounded batches (BATCH_SIZE = 20)
- Commits after each batch
- Streaming cursor, never loading entire DB into RAM
- Interruptible at any time
"""
import sys
import os
import json
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r"C:\LocalAI")
import database
import ollama_client

BATCH_SIZE = 20

def backfill_memories():
    conn = database.db_connect()
    cur = conn.cursor()
    total_processed = 0

    while True:
        # Fetch bounded batch of missing embeddings
        cur.execute("""
            SELECT id, content
            FROM project_memories
            WHERE embedding IS NULL
            ORDER BY id ASC
            LIMIT ?
        """, (BATCH_SIZE,))
        batch = cur.fetchall()

        if not batch:
            break

        print(f"[Memories] Processing batch of {len(batch)} items...")
        for mem_id, content in batch:
            try:
                emb = ollama_client.get_embedding(content)
                if emb:
                    cur.execute(
                        "UPDATE project_memories SET embedding = ? WHERE id = ?",
                        (json.dumps(emb), mem_id)
                    )
                    total_processed += 1
            except Exception as e:
                print(f"[Memories] Error on id {mem_id}: {e}")

        conn.commit()
        print(f"[Memories] Batch committed. Total processed: {total_processed}")
        time.sleep(0.05)

    conn.close()
    return total_processed


def backfill_messages():
    conn = database.db_connect()
    cur = conn.cursor()
    total_processed = 0

    while True:
        # Fetch bounded batch of user messages missing embeddings that meet embedding policy
        cur.execute("""
            SELECT id, conversation_id, content
            FROM messages
            WHERE role = 'user' AND embedding IS NULL
            ORDER BY id ASC
            LIMIT ?
        """, (BATCH_SIZE,))
        batch = cur.fetchall()

        if not batch:
            break

        print(f"[Messages] Processing batch of {len(batch)} items...")
        for msg_id, conv_id, content in batch:
            try:
                if ollama_client.should_embed_message(content):
                    emb = ollama_client.get_embedding(content)
                    if emb:
                        cur.execute(
                            "UPDATE messages SET embedding = ? WHERE id = ?",
                            (json.dumps(emb), msg_id)
                        )
                        total_processed += 1
            except Exception as e:
                print(f"[Messages] Error on message {msg_id}: {e}")

        conn.commit()
        print(f"[Messages] Batch committed. Total processed: {total_processed}")
        time.sleep(0.05)

    conn.close()
    return total_processed


def main():
    print("Starting safe incremental embedding backfill...")
    mem_count = backfill_memories()
    msg_count = backfill_messages()
    print(f"Backfill finished. Memories updated: {mem_count}, Messages updated: {msg_count}.")


if __name__ == "__main__":
    main()
