"""
ollama_client.py - Lightweight client for local Ollama API.
Provides embeddings, cosine similarity, meaningful message filtering,
tool specifications, bounded multi-turn tool calling, and real-time streaming
with active socket-level cancellation.
"""
import urllib.request
import json
import math
from config import (
    OLLAMA_CHAT_URL,
    OLLAMA_EMBED_URL,
    CHAT_MODEL,
    EMBED_MODEL,
    CONTEXT_LENGTH,
    MAX_TOOL_CALLS_PER_USER_MESSAGE
)

class GenerationCancelled(Exception):
    """Raised when user clicks Stop, closing the underlying HTTP stream to free GPU/CUDA."""
    pass

# Tool Schemas for Qwen3 Tool Calling
TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Tìm kiếm trên internet để lấy thông tin mới nhất hiện nay, phiên bản phần mềm mới, giá cả, quota dịch vụ hoặc tài liệu kỹ thuật trực tuyến.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Từ khóa tìm kiếm thông tin trên internet"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Đọc nội dung văn bản chi tiết từ một đường dẫn URL web cụ thể sau khi đã tìm kiếm được URL phù hợp.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Đường dẫn HTTP/HTTPS của trang web cần đọc"
                    }
                },
                "required": ["url"]
            }
        }
    }
]

def get_embedding(text):
    """
    Generate vector embedding using nomic-embed-text via Ollama API.
    Returns list of floats or None on failure.
    """
    if not text or not text.strip():
        return None

    payload = {
        "model": EMBED_MODEL,
        "input": text.strip()
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_EMBED_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
            embeddings = result.get("embeddings")
            if embeddings and len(embeddings) > 0:
                return embeddings[0]
    except Exception as e:
        print(f"[OllamaClient] Embedding error: {e}")

    return None


def cosine_similarity(a, b):
    """Compute cosine similarity between two numeric vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


def should_embed_message(text):
    """
    Helper to avoid wasting GPU/CPU embedding useless user messages.
    """
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False

    cleaned = stripped.lower().strip("!?.,:;~- ")

    trivial_words = {
        "ok", "okie", "okay", "ừ", "u", "uh", "um", "ừm", "dạ", "vâng", "vang", "da",
        "đúng", "dung", "chuẩn", "chuan", "tiếp", "tiep", "tiếp tục", "tiep tuc",
        "thanks", "thank you", "cảm ơn", "cam on", "tks", "ty",
        "được", "dc", "duoc", "yes", "no", "k", "ko", "khong", "không",
        "hi", "hello", "alo", "test", "bye", "tạm biệt"
    }

    if cleaned in trivial_words:
        return False

    if len(stripped) < 18:
        technical_markers = [
            "api", "db", "sql", "bug", "err", "fix", "port", "host",
            "git", "jwt", "id", "url", "cpu", "ram", "gpu", "app", "ui",
            "net", "web", "nhớ", "hệ", "hàm", "lớp", "bảng", "lỗi", "chạy"
        ]
        if not any(marker in cleaned for marker in technical_markers):
            return False

    return True


def chat_completion_raw(messages, tools=None, num_ctx=CONTEXT_LENGTH, timeout=120, cancel_event=None):
    """
    Low-level Ollama chat call returning full message dict:
    {"role": "assistant", "content": ..., "tool_calls": [...]}
    """
    if cancel_event and cancel_event.is_set():
        raise GenerationCancelled("Cancelled before starting request")

    payload = {
        "model": CHAT_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "num_ctx": num_ctx
        }
    }
    if tools:
        payload["tools"] = tools

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    response = urllib.request.urlopen(req, timeout=timeout)
    try:
        raw_bytes = response.read()
        if cancel_event and cancel_event.is_set():
            raise GenerationCancelled("Cancelled after request read")
        result = json.loads(raw_bytes.decode("utf-8"))
        return result.get("message", {})
    finally:
        response.close()


def chat_stream_raw(messages, tools=None, num_ctx=CONTEXT_LENGTH, timeout=120, cancel_event=None):
    """
    Streams chat completion from Ollama. Yields dicts:
    {"type": "content", "text": str} OR
    {"type": "tool_calls", "calls": list}
    """
    if cancel_event and cancel_event.is_set():
        raise GenerationCancelled("Cancelled before starting stream")

    payload = {
        "model": CHAT_MODEL,
        "messages": messages,
        "stream": True,
        "options": {
            "num_ctx": num_ctx
        }
    }
    if tools:
        payload["tools"] = tools

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    response = urllib.request.urlopen(req, timeout=timeout)
    try:
        for line in response:
            if cancel_event and cancel_event.is_set():
                response.close()
                raise GenerationCancelled("User cancelled generation mid-stream")
            line_str = line.decode("utf-8").strip()
            if not line_str:
                continue
            chunk = json.loads(line_str)
            msg = chunk.get("message", {})
            
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                yield {"type": "tool_calls", "calls": tool_calls}

            content = msg.get("content", "")
            if content:
                yield {"type": "content", "text": content}

            if chunk.get("done", False):
                break
    finally:
        response.close()


def run_chat_with_tools_streaming(
    messages,
    tool_executor,
    tools=TOOLS_SPEC,
    on_token_callback=None,
    on_tool_status_callback=None,
    cancel_event=None,
    max_rounds=MAX_TOOL_CALLS_PER_USER_MESSAGE,
    num_ctx=CONTEXT_LENGTH
):
    """
    Streaming bounded tool-calling loop.
    Yields or callbacks tokens in real-time while properly executing web tools.
    Supports real TCP socket closure when cancel_event is set.
    Returns (final_answer_text, used_web_flag).
    """
    rounds = 0
    used_web = False
    working_messages = list(messages)

    while rounds < max_rounds:
        if cancel_event and cancel_event.is_set():
            raise GenerationCancelled("Cancelled by user")

        tool_calls = None
        streamed_text = ""
        
        # When tools are enabled, stream and watch for either tool_calls or content
        for item in chat_stream_raw(working_messages, tools=tools, num_ctx=num_ctx, cancel_event=cancel_event):
            if item["type"] == "tool_calls":
                if tool_calls is None:
                    tool_calls = []
                tool_calls.extend(item["calls"])
            elif item["type"] == "content":
                tok = item["text"]
                streamed_text += tok
                if on_token_callback:
                    on_token_callback(tok)

        # If model did not request any tools, we have the complete streamed answer
        if not tool_calls:
            return streamed_text, used_web

        # Otherwise, model requested tools. Execute them:
        working_messages.append({
            "role": "assistant",
            "content": streamed_text,
            "tool_calls": tool_calls
        })

        for tc in tool_calls:
            if cancel_event and cancel_event.is_set():
                raise GenerationCancelled("Cancelled during tool execution")

            fn_info = tc.get("function", {})
            fn_name = fn_info.get("name")
            fn_args = fn_info.get("arguments", {})
            call_id = tc.get("id")

            print(f"[TOOL] {fn_name} args={fn_args}")
            if on_tool_status_callback:
                on_tool_status_callback(fn_name, fn_args)

            used_web = True
            tool_output_str = tool_executor(fn_name, fn_args)

            tool_result_msg = {
                "role": "tool",
                "content": tool_output_str
            }
            if call_id:
                tool_result_msg["tool_call_id"] = call_id
            working_messages.append(tool_result_msg)

        rounds += 1

    # Max tool rounds reached: force final synthesis without tools
    print("[ToolLoop] Max tool calls reached, asking for final answer.")
    if on_tool_status_callback:
        on_tool_status_callback("synthesize", {})

    final_text = ""
    for item in chat_stream_raw(working_messages, tools=None, num_ctx=num_ctx, cancel_event=cancel_event):
        if item["type"] == "content":
            tok = item["text"]
            final_text += tok
            if on_token_callback:
                on_token_callback(tok)

    return final_text, used_web


def run_chat_with_tools(
    messages,
    tool_executor,
    tools=TOOLS_SPEC,
    on_tool_status_callback=None,
    max_rounds=MAX_TOOL_CALLS_PER_USER_MESSAGE,
    num_ctx=CONTEXT_LENGTH
):
    """
    Synchronous wrapper for backward compatibility with existing tests and callers.
    """
    return run_chat_with_tools_streaming(
        messages=messages,
        tool_executor=tool_executor,
        tools=tools,
        on_token_callback=None,
        on_tool_status_callback=on_tool_status_callback,
        cancel_event=None,
        max_rounds=max_rounds,
        num_ctx=num_ctx
    )


def chat_complete(messages=None, model=CHAT_MODEL, system_prompt=None, options=None, **kwargs):
    """
    Convenience wrapper returning assistant reply text.
    """
    all_msgs = []
    if system_prompt:
        all_msgs.append({"role": "system", "content": system_prompt})
    if messages:
        all_msgs.extend(messages)
    res = chat_completion_raw(all_msgs)
    return res.get("content", "")
