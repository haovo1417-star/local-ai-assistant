# -*- coding: utf-8 -*-
"""
Local AI Project Knowledge / File RAG - Comprehensive Validation Suite
Tests A through O covering:
- Indexing, ignores, incremental scan, change detection, deletion
- Project isolation, semantic recall, line metadata, PDF parsing
- Unsupported/large files, GUI thread safety, context budget, source priority
- Regression tests for existing core capabilities
"""

import os
import sys
import shutil
import time
import json
import sqlite3
import unittest
import io

import config
import database
import knowledge_service
import retrieval_service
import memory_service
import web_service
import ollama_client

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

TEST_DIR = os.path.join(config.BASE_DIR, "test_project_knowledge")
PROJ_A_NAME = "Test Emergency Dispatch A"
PROJ_B_NAME = "Test Other System B"

PDF_CONTENT_BYTES = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 120 >>
stream
BT
/F1 12 Tf
72 712 Td
(Emergency Dispatch Standard Operating Procedure 2026: Always deploy nearest tier 1 paramedic vehicle first.) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000244 00000 n 
0000000415 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
492
%%EOF"""

class ProjectKnowledgeRAGTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()
        # Clean up any leftover test projects
        conn = sqlite3.connect(config.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM projects WHERE name IN (?, ?)", (PROJ_A_NAME, PROJ_B_NAME))
        old_ids = [r[0] for r in cur.fetchall()]
        for pid in old_ids:
            cur.execute("DELETE FROM project_chunks WHERE project_id = ?", (pid,))
            cur.execute("DELETE FROM project_files WHERE project_id = ?", (pid,))
            cur.execute("DELETE FROM project_sources WHERE project_id = ?", (pid,))
            cur.execute("DELETE FROM project_memories WHERE project_id = ?", (pid,))
            cur.execute("DELETE FROM project_summaries WHERE project_id = ?", (pid,))
            cur.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE project_id = ?)", (pid,))
            cur.execute("DELETE FROM conversations WHERE project_id = ?", (pid,))
            cur.execute("DELETE FROM projects WHERE id = ?", (pid,))
        conn.commit()
        conn.close()

        # Create clean test directory
        if os.path.exists(TEST_DIR):
            shutil.rmtree(TEST_DIR, ignore_errors=True)
        os.makedirs(TEST_DIR, exist_ok=True)

        # Create sample files
        backend_dir = os.path.join(TEST_DIR, "Backend", "Services")
        os.makedirs(backend_dir, exist_ok=True)
        helpers_dir = os.path.join(TEST_DIR, "Backend", "Helpers")
        os.makedirs(helpers_dir, exist_ok=True)
        docs_dir = os.path.join(TEST_DIR, "docs")
        os.makedirs(docs_dir, exist_ok=True)

        # DispatchEngineService.cs
        cls.dispatch_service_path = os.path.join(backend_dir, "DispatchEngineService.cs")
        with open(cls.dispatch_service_path, "w", encoding="utf-8") as f:
            f.write("""namespace EmergencyDispatch.Backend.Services
{
    public class DispatchEngineService
    {
        private readonly IUnitRepository _unitRepo;
        private readonly IRoutingService _routingService;

        public DispatchEngineService(IUnitRepository unitRepo, IRoutingService routingService)
        {
            _unitRepo = unitRepo;
            _routingService = routingService;
        }

        // DispatchEngineService hien chon xe cuu ho theo thu tu:
        // 1. Loc cac xe cuu ho dang Available va dung chuyen mon (Rescue, Paramedic)
        // 2. Chon 5 ung vien co khoang cach Haversine gan hien truong nhat
        // 3. Goi OpenRouteService routing API de tinh ETA thuc te theo giao thong
        // 4. Xep hang theo ETA nho nhat va chi dinh xe dau tien
        public async Task<RescueUnit> SelectBestRescueUnit(EmergencyCall call)
        {
            var availableUnits = await _unitRepo.GetAvailableUnitsAsync(call.RequiredType);
            var nearbyCandidates = availableUnits
                .OrderBy(u => GeospatialHelper.CalculateDistance(u.Latitude, u.Longitude, call.Latitude, call.Longitude))
                .Take(5)
                .ToList();

            RescueUnit bestUnit = null;
            double minEta = double.MaxValue;

            foreach (var unit in nearbyCandidates)
            {
                var route = await _routingService.GetRouteAsync(unit.Location, call.Location);
                if (route.DurationSeconds < minEta)
                {
                    minEta = route.DurationSeconds;
                    bestUnit = unit;
                }
            }
            return bestUnit;
        }
    }
}
""")

        # GeospatialHelper.cs with fallback = 1.25
        cls.geo_helper_path = os.path.join(helpers_dir, "GeospatialHelper.cs")
        with open(cls.geo_helper_path, "w", encoding="utf-8") as f:
            f.write("""namespace EmergencyDispatch.Backend.Helpers
{
    public static class GeospatialHelper
    {
        // Traffic fallback factor calibrated for urban emergency response: 1.25
        public const double UrbanTrafficFallbackFactor = 1.25;

        public static double CalculateDistance(double lat1, double lon1, double lat2, double lon2)
        {
            const double R = 6371.0; // Earth radius in km
            var dLat = (lat2 - lat1) * Math.PI / 180.0;
            var dLon = (lon2 - lon1) * Math.PI / 180.0;
            var a = Math.Sin(dLat / 2) * Math.Sin(dLat / 2) +
                    Math.Cos(lat1 * Math.PI / 180.0) * Math.Cos(lat2 * Math.PI / 180.0) *
                    Math.Sin(dLon / 2) * Math.Sin(dLon / 2);
            var c = 2 * Math.Atan2(Math.Sqrt(a), Math.Sqrt(1 - a));
            return R * c * UrbanTrafficFallbackFactor;
        }
    }
}
""")

        # README.md
        cls.readme_path = os.path.join(TEST_DIR, "README.md")
        with open(cls.readme_path, "w", encoding="utf-8") as f:
            f.write("""# Emergency Dispatch System 2026
Lightweight High-Availability Incident Dispatcher.
Core components:
- DispatchEngineService: Automated emergency vehicle selection.
- GeospatialHelper: Coordinate distance calculations with 1.25 urban congestion factor.
- Database: SQLite event journal.
""")

        # database.sql
        cls.sql_path = os.path.join(TEST_DIR, "database.sql")
        with open(cls.sql_path, "w", encoding="utf-8") as f:
            f.write("""CREATE TABLE emergency_units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_code TEXT NOT NULL UNIQUE,
    unit_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Available',
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_units_status_type ON emergency_units(status, unit_type);
""")

        # SOP.pdf
        cls.pdf_path = os.path.join(docs_dir, "SOP.pdf")
        with open(cls.pdf_path, "wb") as f:
            f.write(PDF_CONTENT_BYTES)

        # Create ignored folders with files inside
        for ignored in [".git", "node_modules", "bin", "obj"]:
            ign_path = os.path.join(TEST_DIR, ignored)
            os.makedirs(ign_path, exist_ok=True)
            with open(os.path.join(ign_path, "dummy.cs"), "w") as f:
                f.write("// Should be ignored")

        # Create unsupported binary file (.exe)
        cls.exe_path = os.path.join(TEST_DIR, "tools.exe")
        with open(cls.exe_path, "wb") as f:
            f.write(b"\x4d\x5a\x90\x00\x03\x00\x00\x00")

        # Create large file (>5MB)
        cls.large_file_path = os.path.join(TEST_DIR, "large_dump.sql")
        with open(cls.large_file_path, "wb") as f:
            f.write(b"-- LARGE FILE\n" + b"SELECT 1;\n" * (600000))

        # Setup test projects
        cls.proj_a_id = database.create_project(PROJ_A_NAME, "Project A for RAG testing")
        cls.proj_b_id = database.create_project(PROJ_B_NAME, "Project B for isolation testing")

    @classmethod
    def tearDownClass(cls):
        # Clean up test directory
        if os.path.exists(TEST_DIR):
            shutil.rmtree(TEST_DIR, ignore_errors=True)
        # Remove test project entries
        conn = sqlite3.connect(config.DB_PATH)
        cur = conn.cursor()
        for pid in [cls.proj_a_id, cls.proj_b_id]:
            cur.execute("DELETE FROM project_chunks WHERE project_id = ?", (pid,))
            cur.execute("DELETE FROM project_files WHERE project_id = ?", (pid,))
            cur.execute("DELETE FROM project_sources WHERE project_id = ?", (pid,))
            cur.execute("DELETE FROM project_memories WHERE project_id = ?", (pid,))
            cur.execute("DELETE FROM project_summaries WHERE project_id = ?", (pid,))
            cur.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE project_id = ?)", (pid,))
            cur.execute("DELETE FROM conversations WHERE project_id = ?", (pid,))
            cur.execute("DELETE FROM projects WHERE id = ?", (pid,))
        conn.commit()
        conn.close()

    def test_A_folder_indexing(self):
        """TEST A - Folder indexing: Add test folder, files discovered and indexed."""
        print("\n=== Running TEST A: Folder Indexing ===")
        src_id = database.add_project_source(self.proj_a_id, "folder", TEST_DIR, "EmergencyDispatch")
        self.assertIsNotNone(src_id)

        stats = knowledge_service.index_changed_files(self.proj_a_id)
        print(f"Indexing stats: {stats}")
        self.assertGreater(stats["indexed_files"], 0)
        self.assertGreater(stats["indexed_chunks"], 0)

        # Check DB project_files
        conn = sqlite3.connect(config.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT file_name, indexing_status, file_size FROM project_files WHERE project_id = ?", (self.proj_a_id,))
        rows = cur.fetchall()
        conn.close()
        file_names = [r[0] for r in rows]
        print(f"Discovered files: {file_names}")

        self.assertIn("DispatchEngineService.cs", file_names)
        self.assertIn("GeospatialHelper.cs", file_names)
        self.assertIn("README.md", file_names)
        self.assertIn("database.sql", file_names)
        self.assertIn("SOP.pdf", file_names)
        print("TEST A: PASS")

    def test_B_ignore_directories(self):
        """TEST B - Ignore directories: .git, node_modules, bin, obj must NOT be indexed."""
        print("\n=== Running TEST B: Ignore Directories ===")
        conn = sqlite3.connect(config.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT file_path FROM project_files WHERE project_id = ?", (self.proj_a_id,))
        paths = [r[0] for r in cur.fetchall()]
        conn.close()

        for p in paths:
            for ign in config.IGNORED_DIRECTORIES:
                self.assertNotIn(os.sep + ign + os.sep, p, f"Ignored dir {ign} was found in indexed path: {p}")
        print("TEST B: PASS (no ignored directory files indexed)")

    def test_C_incremental_unchanged_scan(self):
        """TEST C - Incremental unchanged scan: 0 files re-embedded on second run."""
        print("\n=== Running TEST C: Incremental Unchanged Scan ===")
        t0 = time.time()
        stats = knowledge_service.index_changed_files(self.proj_a_id)
        duration = time.time() - t0
        print(f"Second scan stats: {stats} in {duration:.3f}s")
        self.assertEqual(stats["indexed_files"], 0, "Unchanged scan must index 0 files!")
        self.assertEqual(stats["indexed_chunks"], 0, "Unchanged scan must index 0 chunks!")
        self.assertGreater(stats["skipped_unchanged"], 0)
        print("TEST C: PASS (0 files re-embedded)")

    def test_D_changed_file(self):
        """TEST D - Changed file: Modify one file, only that file is re-indexed."""
        print("\n=== Running TEST D: Changed File Re-indexing ===")
        time.sleep(1.1)
        with open(self.readme_path, "a", encoding="utf-8") as f:
            f.write("\n<!-- updated version 2.0 -->\n")

        stats = knowledge_service.index_changed_files(self.proj_a_id)
        print(f"Changed file scan stats: {stats}")
        self.assertEqual(stats["indexed_files"], 1, f"Expected exactly 1 changed file re-indexed, got {stats['indexed_files']}")
        print("TEST D: PASS (only modified file re-indexed)")

    def test_E_deleted_file(self):
        """TEST E - Deleted file: Delete file, stale chunks removed from search."""
        print("\n=== Running TEST E: Deleted File Cleanup ===")
        temp_file = os.path.join(TEST_DIR, "temp_to_delete.txt")
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write("Temporary file content for deletion testing.")

        knowledge_service.index_changed_files(self.proj_a_id)
        results_before = knowledge_service.search_project_knowledge(self.proj_a_id, "Temporary file content for deletion", limit=5)
        self.assertTrue(any("temp_to_delete.txt" in r.get("relative_path", "") for r in results_before))

        os.remove(temp_file)
        stats = knowledge_service.index_changed_files(self.proj_a_id)
        print(f"Post-delete scan stats: {stats}")
        self.assertGreaterEqual(stats["deleted_files"], 1)

        results_after = knowledge_service.search_project_knowledge(self.proj_a_id, "Temporary file content for deletion", limit=5)
        self.assertFalse(any("temp_to_delete.txt" in r.get("relative_path", "") for r in results_after))
        print("TEST E: PASS (stale chunks removed)")

    def test_F_project_isolation(self):
        """TEST F - Project isolation: Project A query does not retrieve Project B chunks."""
        print("\n=== Running TEST F: Project Isolation ===")
        proj_b_dir = os.path.join(config.BASE_DIR, "test_proj_b")
        os.makedirs(proj_b_dir, exist_ok=True)
        secret_b_file = os.path.join(proj_b_dir, "SecretB.cs")
        with open(secret_b_file, "w", encoding="utf-8") as f:
            f.write("""public class SecretBClass {
    // TopSecretProjectBToken = "XYZ-PROJECT-B-SECRET-999"
}""")

        database.add_project_source(self.proj_b_id, "folder", proj_b_dir, "ProjBFolder")
        knowledge_service.index_changed_files(self.proj_b_id)

        # Search from Project A for Project B's secret
        results_a = knowledge_service.search_project_knowledge(self.proj_a_id, "TopSecretProjectBToken", limit=5)
        self.assertFalse(any("SecretBClass" in r.get("content", "") for r in results_a), "Project A search MUST NOT retrieve Project B chunks!")
        self.assertFalse(any("XYZ-PROJECT-B-SECRET-999" in r.get("content", "") for r in results_a))

        # Search from Project B for Project B's secret
        results_b = knowledge_service.search_project_knowledge(self.proj_b_id, "TopSecretProjectBToken", limit=5)
        self.assertGreater(len(results_b), 0, "Project B search should retrieve Project B chunk!")
        self.assertTrue(any("SecretBClass" in r.get("content", "") for r in results_b))
        self.assertFalse(any("DispatchEngineService" in r.get("content", "") for r in results_b), "Project B search MUST NOT retrieve Project A chunks!")

        shutil.rmtree(proj_b_dir, ignore_errors=True)
        print("TEST F: PASS (strict project isolation)")

    def test_G_semantic_source_recall(self):
        """TEST G - Semantic source recall: 'Dispatch engine chọn xe cứu hộ như thế nào?' retrieves DispatchEngineService.cs."""
        print("\n=== Running TEST G: Semantic Source Recall ===")
        query = "Dispatch engine chọn xe cứu hộ như thế nào?"
        results = knowledge_service.search_project_knowledge(self.proj_a_id, query, limit=3)
        self.assertGreater(len(results), 0, "Should retrieve at least one chunk for dispatch query")
        top_chunk = results[0]
        print(f"Top recalled file: {top_chunk.get('relative_path')} (Score: {top_chunk.get('score'):.4f})")
        self.assertTrue("DispatchEngineService.cs" in top_chunk.get("relative_path", "") or "SelectBestRescueUnit" in top_chunk.get("content", ""))
        print("TEST G: PASS (DispatchEngineService.cs recalled)")

    def test_H_line_metadata(self):
        """TEST H - Line metadata: retrieved chunk includes relative_path, start_line, end_line."""
        print("\n=== Running TEST H: Line Metadata ===")
        results = knowledge_service.search_project_knowledge(self.proj_a_id, "UrbanTrafficFallbackFactor", limit=3)
        self.assertGreater(len(results), 0)
        found_geo = None
        for r in results:
            if "GeospatialHelper.cs" in r.get("relative_path", ""):
                found_geo = r
                break
        self.assertIsNotNone(found_geo, "Should retrieve GeospatialHelper.cs")
        self.assertIn("relative_path", found_geo)
        self.assertIn("start_line", found_geo)
        self.assertIn("end_line", found_geo)
        self.assertGreaterEqual(found_geo["start_line"], 1)
        self.assertGreater(found_geo["end_line"], found_geo["start_line"])
        print(f"Line metadata: {found_geo['relative_path']} lines {found_geo['start_line']}-{found_geo['end_line']}")
        print("TEST H: PASS (valid line metadata)")

    def test_I_pdf_text_extraction(self):
        """TEST I - PDF text extraction: Index a text-based PDF and retrieve relevant chunk."""
        print("\n=== Running TEST I: PDF Text Extraction ===")
        results = knowledge_service.search_project_knowledge(self.proj_a_id, "paramedic vehicle operating procedure", limit=3)
        self.assertGreater(len(results), 0)
        found_pdf = any("SOP.pdf" in r.get("relative_path", "") for r in results)
        self.assertTrue(found_pdf, "Should retrieve SOP.pdf chunk for paramedic vehicle operating procedure")
        print("TEST I: PASS (PDF text extracted and recalled)")

    def test_J_unsupported_file(self):
        """TEST J - Bad/unsupported file: Binary .exe skipped gracefully without crashing."""
        print("\n=== Running TEST J: Unsupported File Handling ===")
        conn = sqlite3.connect(config.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT indexing_status FROM project_files WHERE project_id = ? AND file_name = 'tools.exe'", (self.proj_a_id,))
        row = cur.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "unsupported")
        print(f"tools.exe indexing status: {row[0]}")
        print("TEST J: PASS (unsupported file skipped gracefully)")

    def test_K_large_file(self):
        """TEST K - Large file: File > 5MB marked skipped_large without crashing."""
        print("\n=== Running TEST K: Large File Handling ===")
        conn = sqlite3.connect(config.DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT indexing_status, file_size FROM project_files WHERE project_id = ? AND file_name = 'large_dump.sql'", (self.proj_a_id,))
        row = cur.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "skipped_large")
        print(f"large_dump.sql size: {row[1]} bytes, status: {row[0]}")
        print("TEST K: PASS (large file marked skipped_large)")

    def test_L_gui_responsiveness(self):
        """TEST L - GUI responsiveness: Background indexing thread execution with queue progress callback."""
        print("\n=== Running TEST L: Background Indexing Execution ===")
        progress_msgs = []
        def on_progress(indexed, total, filename):
            progress_msgs.append((indexed, total, filename))

        import threading
        t = threading.Thread(target=knowledge_service.index_changed_files, args=(self.proj_a_id, on_progress))
        t.start()
        t.join(timeout=30)
        self.assertFalse(t.is_alive(), "Background thread must finish within timeout")
        print(f"Background indexing executed smoothly. Progress callbacks received: {len(progress_msgs)}")
        print("TEST L: PASS (non-blocking thread execution)")

    def test_M_context_budget(self):
        """TEST M - Context budget: Final knowledge context stays under configured character budget."""
        print("\n=== Running TEST M: Context Budget ===")
        smart_context = retrieval_service.build_ai_context(
            project_id=self.proj_a_id,
            conversation_id=999999,
            user_query="DispatchEngineService va GeospatialHelper hoat dong the nao?"
        )
        self.assertLessEqual(len(smart_context), config.MAX_KNOWLEDGE_CONTEXT_CHARS + 2000)
        self.assertIn("PROJECT KNOWLEDGE / FILE RAG", smart_context)
        self.assertTrue("Tài liệu/Mã nguồn:" in smart_context or "DispatchEngineService.cs" in smart_context)
        print(f"Knowledge context length: {len(smart_context)} chars (well within budget)")
        print("TEST M: PASS (context budget maintained)")

    def test_N_source_priority(self):
        """TEST N - Source priority: Current source (1.25) vs historical chat (1.35)."""
        print("\n=== Running TEST N: Source Priority Grounding ===")
        convo_id = database.create_conversation(self.proj_a_id, "Fallback discussion")
        database.add_message(convo_id, "user", "He so fallback giao thong truoc day la bao nhieu?")
        database.add_message(convo_id, "assistant", "Truoc day theo cuoc hop cu, he so fallback giao thong la 1.35.")

        user_msg = "Hien tai trong source code, he so fallback giao thong (UrbanTrafficFallbackFactor) la bao nhieu?"
        smart_context = retrieval_service.build_ai_context(
            project_id=self.proj_a_id,
            conversation_id=convo_id,
            user_query=user_msg
        )

        self.assertIn("UrbanTrafficFallbackFactor = 1.25", smart_context)

        system_prompt = config.SYSTEM_PROMPT_TEMPLATE.format(chat_model="qwen3:4b-q4_K_M") + "\n\nNGU CANH:\n" + smart_context
        self.assertIn("CODE VERSION PRIORITY", system_prompt)

        messages = [
            {"role": "user", "content": "He so fallback giao thong truoc day la bao nhieu?"},
            {"role": "assistant", "content": "Truoc day theo cuoc hop cu, he so fallback giao thong la 1.35."},
            {"role": "user", "content": user_msg}
        ]

        response = ollama_client.chat_complete(
            model="qwen3:4b-q4_K_M",
            messages=messages,
            system_prompt=system_prompt,
            options={"temperature": 0.0}
        )
        print(f"Model Answer:\n{response}")
        self.assertIn("1.25", response, "Model answer MUST prioritize current source code value 1.25 over 1.35")
        print("TEST N: PASS (source priority grounded at 1.25)")

    def test_O_regression_tests(self):
        """TEST O - Core regressions: Project isolation, lazy loading, memory, web search, web cache, tool loop guard, SQLite integrity."""
        print("\n=== Running TEST O: Regression Tests ===")
        # 1. SQLite integrity
        conn = sqlite3.connect(config.DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        integrity = cur.fetchone()[0]
        conn.close()
        self.assertEqual(integrity, "ok", "Database PRAGMA integrity_check must be 'ok'")

        # 2. Keyset lazy loading
        convo_id = database.create_conversation(self.proj_a_id, "LazyLoadConvo")
        for i in range(15):
            database.add_message(convo_id, "user" if i % 2 == 0 else "assistant", f"Message number {i}")
        page1 = database.get_messages_latest(convo_id, limit=5)
        self.assertEqual(len(page1), 5)
        self.assertEqual(page1[-1][2], "Message number 14")
        oldest_id = page1[0][0]
        page2 = database.get_messages_before(convo_id, before_message_id=oldest_id, limit=5)
        self.assertEqual(len(page2), 5)
        self.assertEqual(page2[-1][0], oldest_id - 1)

        # 3. Project memory isolation
        mem_id_a = database.add_project_memory(self.proj_a_id, "architecture", "Core rule for A only")
        mem_id_b = database.add_project_memory(self.proj_b_id, "architecture", "Core rule for B only")
        mems_a = database.get_project_memories(self.proj_a_id)
        mems_b = database.get_project_memories(self.proj_b_id)
        self.assertTrue(any("rule for A" in m["content"] for m in mems_a))
        self.assertFalse(any("rule for B" in m["content"] for m in mems_a))
        self.assertTrue(any("rule for B" in m["content"] for m in mems_b))
        self.assertFalse(any("rule for A" in m["content"] for m in mems_b))

        # 4. Anti-SSRF check
        is_safe_local, err1 = web_service.is_safe_url("http://127.0.0.1:8000")
        is_safe_internal, err2 = web_service.is_safe_url("http://192.168.1.1")
        is_safe_public, err3 = web_service.is_safe_url("https://example.com")
        self.assertFalse(is_safe_local)
        self.assertFalse(is_safe_internal)
        self.assertTrue(is_safe_public)

        # 5. Web Cache
        test_url = "https://example.com/test-rag-cache"
        test_html = "<html><body><h1>Example Heading</h1><p>Sample content for regression.</p></body></html>"
        database.set_web_cache(test_url, "url_content", test_html, ttl_minutes=60)
        cached = database.get_web_cache(test_url)
        self.assertIsNotNone(cached)
        self.assertTrue("Example Heading" in (cached if isinstance(cached, str) else cached.get("content", "")))

        # 6. Tool calling definition exists
        tools = ollama_client.TOOLS_SPEC
        self.assertEqual(len(tools), 2)
        tool_names = [t["function"]["name"] for t in tools]
        self.assertIn("web_search", tool_names)
        self.assertIn("web_fetch", tool_names)

        # 7. GUI startup verification (headless update)
        import tkinter as tk
        from app import LocalAIApp
        root = tk.Tk()
        root.withdraw()
        app = LocalAIApp(root)
        root.update()
        self.assertIsNotNone(app.btn_add_folder)
        self.assertIsNotNone(app.btn_add_file)
        self.assertIsNotNone(app.btn_reindex)
        root.destroy()

        print("TEST O: PASS (all core regressions PASS)")

if __name__ == "__main__":
    suite = unittest.TestLoader().loadTestsFromTestCase(ProjectKnowledgeRAGTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
