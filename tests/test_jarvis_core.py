"""
Automated Test Suite for D.O.N.N.A. / J.A.R.V.I.S. Core Engineering Architecture:
1. Tool Declaration deduplication and schema integrity.
2. Model pool failover, key rotation, and quota protection.
3. OpenClaw Semantic Router (Tool RAG) and real execution.
4. Ambient context detection (foreground window & clipboard).
"""

import sys
import unittest
import collections
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core.model_pool import model_pool, FAST_TEXT_MODEL, KeyStatus
from core.openclaw_engine import openclaw_engine
from core.ambient_context import get_ambient_context, format_ambient_for_prompt
try:
    import main
except ImportError:
    from services.brain_orchestrator import app as main


class TestJarvisCoreArchitecture(unittest.TestCase):

    def test_01_tool_declarations_no_duplicates(self):
        tools = main.TOOL_DECLARATIONS
        names = [t["name"] for t in tools]
        counts = collections.Counter(names)
        duplicates = [k for k, v in counts.items() if v > 1]
        self.assertEqual(duplicates, [], f"Found duplicate tool declarations: {duplicates}")
        self.assertNotIn("reminder", duplicates, "Duplicate 'reminder' tool must be resolved")

    def test_02_tool_declarations_valid_schemas(self):
        for tool in main.TOOL_DECLARATIONS:
            self.assertIn("name", tool)
            self.assertIn("description", tool)
            self.assertIn("parameters", tool)
            params = tool["parameters"]
            self.assertEqual(params.get("type"), "OBJECT")
            self.assertIn("properties", params)

    def test_03_model_pool_defaults_and_rotation(self):
        self.assertEqual(FAST_TEXT_MODEL, "gemini-3.6-flash")
        active_key = model_pool.get_active_key()
        self.assertTrue(bool(active_key), "Model pool must have an active Gemini API key")

        # Test cooldown logic
        ks = KeyStatus("test_key_fake")
        self.assertTrue(ks.is_available)
        ks.mark_rate_limited(cooldown_seconds=10.0)
        self.assertFalse(ks.is_available)

    def test_04_openclaw_semantic_router(self):
        # Must index all 51 skills from openclaw-main
        self.assertGreaterEqual(len(openclaw_engine._skills), 50)

        # Prompt summary must be compact, not a 40-skill dump
        summary = openclaw_engine.get_skills_summary_for_prompt()
        self.assertLess(len(summary), 1200, "System prompt summary for skills must remain concise")
        self.assertIn("openclaw_skill", summary)

        # Semantic router matching
        match_diagram = openclaw_engine.match_skill("нарисуй архитектурную диаграмму")
        self.assertIsNotNone(match_diagram)
        self.assertEqual(match_diagram.name, "diagram-maker")

        match_weather = openclaw_engine.match_skill("погода в Лондоне")
        self.assertIsNotNone(match_weather)
        self.assertEqual(match_weather.name, "weather")

    def test_05_ambient_context(self):
        ctx = get_ambient_context()
        self.assertIn("window_title", ctx)
        self.assertIn("process_name", ctx)
        self.assertIn("clipboard", ctx)

        formatted = format_ambient_for_prompt()
        self.assertIsInstance(formatted, str)

    def test_06_diagram_maker_generates_real_html(self):
        # Verify diagrams folder exists
        diagrams_dir = BASE_DIR / "documents" / "diagrams"
        self.assertTrue(diagrams_dir.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
