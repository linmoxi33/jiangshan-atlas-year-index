import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "atlas_year_index.py")
spec = importlib.util.spec_from_file_location("ayi", BIN)
ayi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ayi)


def snap(path, caption, features=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = {"type": "FeatureCollection",
           "snapshot": {"caption": caption},
           "features": features if features is not None else []}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)

    def test_point_year_after_label(self):
        # regression: anchored point regex missed single years written after a label
        self.assertEqual(ayi.parse_year_range("明 · 1407 年 · 永乐极盛"), (1407, 1407))

    def test_point_year_bce_after_label(self):
        self.assertEqual(ayi.parse_year_range("秦 · 公元前 221 年"), (-221, -221))

    def test_point_year_rejects_reign_count(self):
        # "61 年" is a reign-year count, not a calendar year
        self.assertIsNone(ayi.parse_year_range("康熙 61 年"))

    def test_point_year_inside_sentence(self):
        self.assertEqual(ayi.parse_year_range("中华人民共和国 1949 年成立"), (1949, 1949))


class ParseTests(unittest.TestCase):
    def test_plain_range(self):
        self.assertEqual(ayi.parse_year_range("220 — 237 · 三国鼎立初局"), (220, 237))

    def test_bce_range(self):
        self.assertEqual(ayi.parse_year_range("前221 — 前207 · 秦灭六国"), (-221, -207))

    def test_fullwidth_digits_and_spaces(self):
        self.assertEqual(ayi.parse_year_range("１３６８ — １３９８"), (1368, 1398))

    def test_short_dash_and_no_spaces(self):
        self.assertEqual(ayi.parse_year_range("618-907"), (618, 907))

    def test_bce_inherits_when_second_is_larger(self):
        # 前221—207 means 221 BCE .. 207 BCE
        self.assertEqual(ayi.parse_year_range("前221 — 207"), (-221, -207))

    def test_bce_to_ce_crossing(self):
        # 202 BCE .. 8 CE: crossing into CE must be explicit
        self.assertEqual(ayi.parse_year_range("前202 — 公元8"), (-202, 8))

    def test_single_year_caption(self):
        self.assertEqual(ayi.parse_year_range("前 207 · 巨鹿之战"), (-207, -207))
        self.assertEqual(ayi.parse_year_range("1945 · 抗战胜利"), (1945, 1945))

    def test_year_zero_rejected(self):
        self.assertIsNone(ayi.parse_year_range("0 — 10"))

    def test_unparseable(self):
        self.assertIsNone(ayi.parse_year_range("约莫很久以前"))
        self.assertIsNone(ayi.parse_year_range(None))


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def codes(self, report):
        return sorted(f["code"] for f in report["findings"])

    def test_clean_contiguous_group(self):
        snap(os.path.join(self.tmp, "qin", "s_qin_a.geojson"), "前221 — 前207")
        snap(os.path.join(self.tmp, "qin", "s_qin_b.geojson"), "前206 — 前202")
        r = ayi.build(self.tmp)
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["summary"]["parsed"], 2)
        self.assertEqual(r["groups"]["qin"]["uncovered_years"], 0)

    def test_gap_detected(self):
        snap(os.path.join(self.tmp, "ming", "s_ming_a.geojson"), "1368 — 1398")
        snap(os.path.join(self.tmp, "ming", "s_ming_b.geojson"), "1405 — 1433")
        r = ayi.build(self.tmp)
        self.assertIn("group-gap", self.codes(r))
        gap = [f for f in r["findings"] if f["code"] == "group-gap"][0]
        self.assertIn("6 uncovered", gap["detail"])
        self.assertEqual(r["groups"]["ming"]["uncovered_years"], 6)

    def test_overlap_detected(self):
        snap(os.path.join(self.tmp, "tang", "s_tang_a.geojson"), "618 — 700")
        snap(os.path.join(self.tmp, "tang", "s_tang_b.geojson"), "690 — 750")
        r = ayi.build(self.tmp)
        self.assertIn("group-overlap", self.codes(r))

    def test_reversed_range(self):
        snap(os.path.join(self.tmp, "sui", "s_sui_a.geojson"), "700 — 600")
        r = ayi.build(self.tmp)
        self.assertIn("year-reversed", self.codes(r))
        self.assertEqual(r["summary"]["parsed"], 0)

    def test_unparsed_caption(self):
        snap(os.path.join(self.tmp, "yuan", "s_yuan_a.geojson"), "元朝疆域示意")
        r = ayi.build(self.tmp)
        self.assertIn("year-unparsed", self.codes(r))
        self.assertEqual(r["summary"]["unparsed"], 1)

    def test_duplicate_keys_across_groups(self):
        snap(os.path.join(self.tmp, "a", "dup.geojson"), "100 — 110")
        snap(os.path.join(self.tmp, "b", "dup.geojson"), "120 — 130")
        r = ayi.build(self.tmp)
        self.assertIn("duplicate-key", self.codes(r))

    def test_invalid_json(self):
        os.makedirs(os.path.join(self.tmp, "x"))
        with open(os.path.join(self.tmp, "x", "bad.geojson"), "w") as fh:
            fh.write("{not json")
        r = ayi.build(self.tmp)
        self.assertIn("invalid-json", self.codes(r))

    def test_contested_years_counted(self):
        snap(os.path.join(self.tmp, "beisong", "a.geojson"), "960 — 1127")
        snap(os.path.join(self.tmp, "nansong", "b.geojson"), "1127 — 1279")
        r = ayi.build(self.tmp)
        self.assertEqual(r["summary"]["contested_years"], 1)

    def test_sorted_by_start(self):
        snap(os.path.join(self.tmp, "g", "s_g_a.geojson"), "1200 — 1210")
        snap(os.path.join(self.tmp, "g", "s_g_b.geojson"), "1100 — 1110")
        r = ayi.build(self.tmp)
        self.assertEqual([e["key"] for e in r["snapshots"]], ["s_g_b", "s_g_a"])
        self.assertIn("group-nonmonotonic", self.codes(r))

    def test_index_order_is_authoritative(self):
        snap(os.path.join(self.tmp, "g", "z.geojson"), "1100 — 1110")
        snap(os.path.join(self.tmp, "g", "a.geojson"), "1200 — 1210")
        with open(os.path.join(self.tmp, "index.json"), "w") as fh:
            json.dump({"order": ["z", "a"]}, fh)
        r = ayi.build(self.tmp)
        # declared order z then a is chronological even though filenames say otherwise
        self.assertNotIn("group-nonmonotonic", self.codes(r))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        snap(os.path.join(self.tmp, "qin", "s_qin_a.geojson"), "前221 — 前207")
        snap(os.path.join(self.tmp, "qin", "s_qin_b.geojson"), "前206 — 前202")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, BIN] + list(args),
                              capture_output=True, text=True)

    def test_exit_zero_on_clean(self):
        p = self.run_cli(self.tmp, "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertEqual(data["summary"]["findings"], 0)

    def test_reversed_range_not_counted_as_coverage(self):
        # a reversed range must not create a phantom gap or inflate the span
        snap(os.path.join(self.tmp, "qin", "s_qin_a.geojson"), "前300 — 前200")
        snap(os.path.join(self.tmp, "qin", "s_qin_b.geojson"), "前100 — 前90")
        snap(os.path.join(self.tmp, "qin", "s_qin_bad.geojson"), "前50 — 前80")
        p = self.run_cli(self.tmp, "--json")
        data = json.loads(p.stdout)
        codes = [f["code"] for f in data["findings"]]
        self.assertIn("year-reversed", codes)
        gaps = [f for f in data["findings"] if f["code"] == "group-gap"]
        # only the real hole between -200 and -100 counts; the reversed entry
        # must not shorten it to 9 years or extend the group span
        self.assertEqual(len(gaps), 1)
        self.assertIn("99 uncovered", gaps[0]["detail"])
        self.assertEqual(data["summary"]["parsed"], 2)
        self.assertEqual(data["groups"]["qin"]["span"], [-300, -90])

    def test_exit_one_on_findings(self):
        snap(os.path.join(self.tmp, "qin", "s_qin_c.geojson"), "前100 — 前90")
        p = self.run_cli(self.tmp)
        self.assertEqual(p.returncode, 1)

    def test_exit_two_on_missing_dir(self):
        p = self.run_cli(os.path.join(self.tmp, "nope"))
        self.assertEqual(p.returncode, 2)
        self.assertIn("not found", p.stderr)

    def test_json_is_loadable(self):
        p = self.run_cli(self.tmp, "--json")
        json.loads(p.stdout)  # must not raise

    def test_year_query_bce(self):
        p = self.run_cli(self.tmp, "--year", "-210", "--json")
        self.assertEqual(p.returncode, 0)
        data = json.loads(p.stdout)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["snapshots"][0]["key"], "s_qin_a")


if __name__ == "__main__":
    unittest.main()