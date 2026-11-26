"""Run with:  python -m unittest discover -s tests -v   (or pytest, if installed)"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import alerts, cleaner, exporter, importer, schema, search, storage, summary, validation
from core.parsing import is_missing, parse_date, parse_number
from core.service import Workspace

SAMPLE = storage.SAMPLE_CSV


def sample():
    cols, rows = storage.load_dataset(SAMPLE)
    return cols, rows, schema.rules_for(cols, rows)


class ParsingTests(unittest.TestCase):
    def test_missing_tokens(self):
        for v in ("", "  ", "N/A", "null", "-", None):
            self.assertTrue(is_missing(v), v)
        self.assertFalse(is_missing("0"))

    def test_numbers_and_dates(self):
        self.assertEqual(parse_number("1,200.5"), 1200.5)
        self.assertIsNone(parse_number("abc"))
        self.assertIsNone(parse_number("nan"))
        self.assertEqual(parse_date("15/08/2022")[0].isoformat(), "2022-08-15")
        self.assertEqual(parse_date("Aug 20, 2022")[0].isoformat(), "2022-08-20")
        self.assertIsNone(parse_date("2022-13-45")[0])


class CleanerTests(unittest.TestCase):
    def setUp(self):
        self.cols, self.rows, self.rules = sample()
        self.issues = cleaner.analyze(self.cols, self.rows, self.rules)

    def sub(self, name):
        return [i for i in self.issues if i.subtype == name]

    def test_missing_found(self):
        self.assertEqual(len([i for i in self.issues if i.kind == "missing"]), 7)
        self.assertEqual(len(self.sub("placeholder")), 1)        # "N/A"

    def test_duplicates_found(self):
        self.assertEqual([i.row for i in self.sub("exact duplicate")], [33])
        self.assertEqual([i.row for i in self.sub("duplicate key")], [34])

    def test_inconsistent_found(self):
        self.assertEqual(len(self.sub("spelling variant")), 4)    # comp sci, CS, ELECTRONICS, Mechancial
        self.assertEqual(len(self.sub("out of range")), 6)
        self.assertEqual(len(self.sub("mixed date format")), 2)
        self.assertEqual(len(self.sub("invalid format")), 2)      # bad email + impossible date

    def test_boundary_values_are_not_flagged(self):
        flagged = {(i.row, i.column) for i in self.issues}
        for cell in [(6, "age"), (9, "age"), (8, "marks"), (10, "marks"), (10, "attendance")]:
            self.assertNotIn(cell, flagged)

    def test_fixes_reduce_issues_and_do_not_mutate_input(self):
        before = [dict(r) for r in self.rows]
        new, log = cleaner.apply_fixes(self.cols, self.rows, self.rules, set(cleaner.FIX_OPTIONS))
        self.assertEqual(before, self.rows)
        self.assertLess(len(cleaner.analyze(self.cols, new, self.rules)), len(self.issues))
        self.assertEqual(len(new), 39)                            # exact duplicate removed
        again, _ = cleaner.apply_fixes(self.cols, new, self.rules, set(cleaner.FIX_OPTIONS))
        self.assertEqual(new, again)                              # idempotent

    def test_empty_and_odd_datasets(self):
        self.assertEqual(cleaner.analyze(schema.STUDENT_COLUMNS, [], schema.DEFAULT_RULES), [])
        cols = ["a", "b"]
        rows = [{"a": "1", "b": "x"}, {"a": "1", "b": "x"}]
        rules = schema.rules_for(cols, rows)
        self.assertTrue(any(i.subtype == "exact duplicate" for i in cleaner.analyze(cols, rows, rules)))


class StorageTests(unittest.TestCase):
    def test_roundtrip_csv_json(self):
        cols, rows, _ = sample()
        with tempfile.TemporaryDirectory() as d:
            for ext in ("csv", "json"):
                p = Path(d) / f"x.{ext}"
                storage.save_dataset(p, cols, rows)
                c2, r2 = storage.load_dataset(p)
                self.assertEqual((cols, rows), (c2, r2))

    def test_corrupt_and_missing_files_recover(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "w.json"
            cols, rows, notes = storage.load_working(p)           # missing -> seeded
            self.assertEqual(len(rows), 40)
            p.write_text("{not json", encoding="utf-8")
            cols, rows, notes = storage.load_working(p)           # corrupt -> clean template
            self.assertEqual(rows, [])
            self.assertTrue(any("backup" in n for n in notes))
            p.write_text("[1, 2, 3]", encoding="utf-8")           # wrong schema
            self.assertEqual(storage.load_working(p)[1], [])

    def test_unsupported_extension(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.txt"; p.write_text("hi")
            with self.assertRaises(storage.StorageError):
                storage.load_dataset(p)


class ValidationTests(unittest.TestCase):
    def feed(self, *answers):
        it = iter(answers)
        return lambda prompt: next(it)

    def test_ask_number_loops_until_valid(self):
        quiet = lambda m: None
        v = validation.ask_number("Age", kind="int", lo=16, hi=60, input_fn=self.feed("abc", "", "200", "17.5", "25"), out=quiet)
        self.assertEqual(v, "25")

    def test_cancel_and_eof(self):
        with self.assertRaises(validation.InputAborted):
            validation.ask_str("x", input_fn=self.feed("/cancel"))
        def eof(_): raise EOFError
        with self.assertRaises(validation.InputAborted):
            validation.ask_str("x", input_fn=eof)

    def test_validate_field(self):
        R = schema.DEFAULT_RULES
        self.assertIsNotNone(validation.validate_field("age", R["age"], "x", [])[1])
        self.assertIsNotNone(validation.validate_field("marks", R["marks"], "101", [])[1])
        self.assertEqual(validation.validate_field("department", R["department"], "comp sci", [])[0], "Computer Science")
        self.assertIsNotNone(validation.validate_field("department", R["department"], "Nope", [])[1])
        self.assertEqual(validation.validate_field("email", R["email"], "A@B.com", [])[0], "a@b.com")
        self.assertEqual(validation.validate_field("enrollment_date", R["enrollment_date"], "15/08/2022", [])[0], "2022-08-15")
        self.assertIsNotNone(validation.validate_field("student_id", R["student_id"], "S001", [{"student_id": "S001"}])[1])

    def test_next_id(self):
        self.assertEqual(validation.next_id([{"student_id": "S009"}, {"student_id": "S040"}], "student_id", {}), "S041")


class SearchSummaryAlertExportTests(unittest.TestCase):
    def setUp(self):
        self.cols, self.rows, self.rules = sample()
        self.issues = cleaner.analyze(self.cols, self.rows, self.rules)
        self.s = summary.compute_summary(self.cols, self.rows, self.issues, self.rules)

    def test_search(self):
        self.assertEqual(len(search.search_records(self.rows, self.cols, "aarav")), 1)
        found = search.search_records(self.rows, self.cols, filters={"department": "civil"})
        self.assertTrue(all(r["department"] == "Civil" for _, r in found))
        found = search.search_records(self.rows, self.cols, ranges={"marks": (90, None)})
        self.assertTrue(all(float(r["marks"]) >= 90 for _, r in found))
        rows_missing = search.rows_with_issue_kind(self.issues, "missing")
        self.assertEqual(len(search.search_records(self.rows, self.cols, issue_rows=rows_missing)), len(rows_missing))

    def test_summary(self):
        self.assertEqual(self.s["rows"], 40)
        self.assertEqual(self.s["missing_cells"], 7)
        self.assertIn(self.s["status"], ("Healthy", "Needs Attention", "Critical"))
        self.assertAlmostEqual(self.s["numeric"]["age"]["max"], 60)    # 150 excluded as invalid
        self.assertEqual(self.s["trend"]["periods"][-1], "2024")       # future 2031 excluded

    def test_alerts(self):
        a = alerts.generate_alerts(self.s, self.issues)
        self.assertEqual(a[0].level, "CRITICAL")
        clean = summary.compute_summary(self.cols, [], [], self.rules)
        self.assertEqual(alerts.generate_alerts(clean, [])[0].level, "INFO")

    def test_exports(self):
        a = alerts.generate_alerts(self.s, self.issues)
        self.assertIn("# Data Quality Report", exporter.markdown_report(self.s, self.issues, a))
        self.assertIn("AUDIT LOG", exporter.audit_log_text(self.s, self.issues, a))
        self.assertEqual(len(exporter.issues_csv_text(self.issues).strip().splitlines()), len(self.issues) + 1)


class ImporterTests(unittest.TestCase):
    def test_import_log(self):
        cols = schema.STUDENT_COLUMNS
        rules = schema.rules_for(cols, [])
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "legacy.csv"
            f.write_text("Student ID,Student Name,Dept,Score,Age,Junk\nS101,Alok Jain,CS,88,20,x\nS102,Short\n\nS103,Neha Rao,Civil,abc,20,y\n")
            r = importer.import_csv(f, cols, rules, log_path=Path(d) / "log.txt")
            self.assertEqual((r.accepted, r.warned, r.rejected, r.skipped), (2, 1, 1, 1))
            self.assertTrue(Path(r.log_path).exists())
            strict = importer.import_csv(f, cols, rules, strict=True)
            self.assertEqual(strict.rejected, 2)
            with self.assertRaises(importer.ImportFailure):
                importer.import_csv(Path(d) / "missing.csv", cols, rules)
            (Path(d) / "bad.csv").write_text("x,y\n1,2\n")
            with self.assertRaises(importer.ImportFailure):
                importer.import_csv(Path(d) / "bad.csv", cols, rules)


class WorkspaceTests(unittest.TestCase):
    def test_persistence_undo_clean(self):
        with tempfile.TemporaryDirectory() as d:
            kw = dict(path=Path(d) / "w.json", history_path=Path(d) / "h.json", reports_dir=Path(d) / "rep")
            ws = Workspace(**kw)
            self.assertEqual(len(ws.rows), 40)
            n = ws.add_record({"student_id": "S099", "name": "Test User", "department": "Civil", "age": "20",
                               "marks": "50", "attendance": "80", "enrollment_date": "2024-01-01", "email": "t@x.com"})
            self.assertEqual(n, 41)
            self.assertEqual(len(Workspace(**kw).rows), 41)        # survives a restart
            before = ws.summary["quality_score"]
            ws.clean(set(cleaner.FIX_OPTIONS))
            self.assertGreater(ws.summary["quality_score"], before)
            self.assertTrue(ws.undo())
            self.assertEqual(len(ws.rows), 41)
            self.assertTrue(ws.validate_record({"student_id": "S099", "name": "Dup"}))   # id exists
            files = ws.export()
            self.assertEqual(len(files), 3)
            self.assertGreaterEqual(len(ws.history()), 1)


if __name__ == "__main__":
    unittest.main()
