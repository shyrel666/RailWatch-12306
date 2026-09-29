import ast
from pathlib import Path
import unittest


class RehearsalStaticGuardTests(unittest.TestCase):
    def test_real_checks_have_no_transaction_selectors_or_order_actions(self):
        root = Path(__file__).resolve().parents[1]
        for filename in ("railwatch_rehearsal.py", "railwatch_rehearsal_checks.py"):
            source = (root / filename).read_text(encoding="utf-8")
            for forbidden in ("#submitOrder_id", "#qr_submit_id", "#toPayBtn", "#hbSubmit", "预订", ".regular(", ".alternate("):
                self.assertNotIn(forbidden, source)
            tree = ast.parse(source)
            clicks = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "click"]
            self.assertEqual(len(clicks), int(filename.endswith("checks.py")))

    def test_drill_does_not_write_journal_or_use_html_injection(self):
        source = (Path(__file__).resolve().parents[1] / "railwatch_rehearsal_drill.py").read_text(encoding="utf-8")
        for forbidden in ("innerHTML", "OrderJournal", ".begin(", ".record("):
            self.assertNotIn(forbidden, source)
        self.assertIn('"offline": True', source)
        self.assertIn('url != uri', source)
