import json
import os
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from scripts import graphify_views as views


class GraphifyViewsTests(unittest.TestCase):
    def setUp(self):
        self.graph = {
            "nodes": [
                {
                    "id": "a",
                    "name": "<script>alert(1)</script>",
                    "source_file": "backend/a.py",
                    "source_location": "4",
                    "community": "core",
                },
                {
                    "id": "b",
                    "name": "Beta",
                    "source_file": "backend/b.py",
                    "line": 9,
                    "community": "../../escape",
                },
                {"id": "c", "name": "Gamma", "source_file": "backend/c.py", "line": 12},
            ],
            "links": [
                {"source": "a", "target": "b", "type": "calls", "confidence": 0.9},
                {"source": "b", "target": "c", "type": "imports"},
            ],
        }
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = self.root
        self.graph_path = (
            self.runtime / "generations" / ("a" * 32) / "graphify-out" / "graph.json"
        )
        self.graph_path.parent.mkdir(parents=True)
        self.graph_path.write_text(json.dumps(self.graph), encoding="utf-8")
        (self.runtime / "exports").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def export_html(self, graph, output):
        with patch("pathlib.Path.cwd", return_value=self.runtime):
            views.export_html(graph, output)

    def export_wiki(self, graph, output):
        with patch("pathlib.Path.cwd", return_value=self.runtime):
            views.export_wiki(graph, output)

    def test_json_export_preserves_graph(self):
        dst = self.runtime / "exports" / "out.json"
        with (
            patch("os.getcwd", return_value=str(self.runtime)),
            patch("pathlib.Path.cwd", return_value=self.runtime),
        ):
            self.assertEqual(
                0,
                views.main(["export", str(self.graph_path), "json", str(dst)]),
            )
        self.assertEqual(self.graph, json.loads(dst.read_text(encoding="utf-8")))

    def test_cli_accepts_runtime_relative_paths_from_wrapper_cwd(self):
        previous = Path.cwd()
        try:
            os.chdir(self.runtime)
            self.assertEqual(
                0,
                views.main(
                    [
                        "export",
                        str(self.graph_path.relative_to(self.runtime)),
                        "html",
                        "exports/wrapper.html",
                    ]
                ),
            )
        finally:
            os.chdir(previous)
        self.assertTrue((self.runtime / "exports" / "wrapper.html").is_file())

    def test_cli_rejects_absolute_and_traversal_outputs_for_each_format(self):
        with tempfile.TemporaryDirectory() as outside_temp:
            outside = Path(outside_temp)
            with patch("pathlib.Path.cwd", return_value=self.runtime):
                for export_format, suffix in (
                    ("html", "page.html"),
                    ("wiki", "wiki"),
                    ("json", "graph.json"),
                ):
                    for output in (
                        outside / suffix,
                        self.runtime / "exports" / ".." / ".." / "outside" / suffix,
                    ):
                        with self.subTest(format=export_format, output=output):
                            self.assertEqual(
                                2,
                                views.main(
                                    [
                                        "export",
                                        str(self.graph_path),
                                        export_format,
                                        str(output),
                                    ]
                                ),
                            )
                            self.assertFalse(output.exists())
            self.assertEqual([], list(outside.iterdir()))

    def test_cli_rejects_graph_symlink_to_outside(self):
        with tempfile.TemporaryDirectory() as outside_temp:
            outside = Path(outside_temp) / "graph.json"
            outside.write_text(json.dumps(self.graph), encoding="utf-8")
            link = (
                self.runtime
                / "generations"
                / ("b" * 32)
                / "graphify-out"
                / "graph.json"
            )
            link.parent.mkdir(parents=True)
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            output = self.runtime / "exports" / "must-not-exist.json"
            with patch("pathlib.Path.cwd", return_value=self.runtime):
                self.assertEqual(
                    2, views.main(["export", str(link), "json", str(output)])
                )
            self.assertFalse(output.exists())

    def test_cli_rejects_output_symlink(self):
        target = self.runtime / "exports" / "target.json"
        target.write_text("original", encoding="utf-8")
        link = self.runtime / "exports" / "link.json"
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"symlinks unavailable: {exc}")
        with patch("pathlib.Path.cwd", return_value=self.runtime):
            self.assertEqual(
                2,
                views.main(["export", str(self.graph_path), "json", str(link)]),
            )
        self.assertEqual("original", target.read_text(encoding="utf-8"))

    def test_direct_html_and_wiki_writers_enforce_exports_boundary(self):
        for export, output in (
            (self.export_html, self.root / "outside.html"),
            (self.export_wiki, self.root / "outside-wiki"),
        ):
            with (
                self.subTest(output=output),
                self.assertRaisesRegex(
                    ValueError, "inside the current runtime exports"
                ),
            ):
                export(self.graph, output)
            self.assertFalse(output.exists())

    def test_html_is_offline_searchable_and_escapes_script_payload(self):
        dst = self.runtime / "exports" / "index.html"
        self.export_html(self.graph, dst)
        content = dst.read_text(encoding="utf-8")
        self.assertIn("Relationships", content)
        self.assertIn("confidence", content)
        self.assertIn("backend/a.py", content)
        self.assertIn("\\u003cscript\\u003e", content)
        self.assertNotIn("<script>alert(1)</script>", content)
        self.assertNotIn("https://", content)
        self.assertIn("Content-Security-Policy", content)
        self.assertIn("String(s??'')", content)
        self.assertIn("a?.name??e.source", content)
        self.assertNotIn("----", content)
        self.assertNotIn("--.", content)

    def test_generated_html_javascript_passes_node_syntax_check(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is not installed")
        dst = self.runtime / "exports" / "index.html"
        self.export_html(self.graph, dst)
        content = dst.read_text(encoding="utf-8")

        class ScriptReader(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_script = False
                self.parts = []

            def handle_starttag(self, tag, attrs):
                if tag.lower() == "script":
                    self.in_script = True

            def handle_endtag(self, tag):
                if tag.lower() == "script":
                    self.in_script = False

            def handle_data(self, data):
                if self.in_script:
                    self.parts.append(data)

        parser = ScriptReader()
        parser.feed(content)
        self.assertTrue(parser.parts)
        js = self.runtime / "exports" / "generated.js"
        js.write_text("\n".join(parser.parts), encoding="utf-8")
        result = subprocess.run(
            [node, "--check", str(js)], capture_output=True, text=True, check=False
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_wiki_is_deterministic_and_slug_cannot_traverse(self):
        out = self.runtime / "exports" / "wiki"
        self.export_wiki(self.graph, out)
        self.assertTrue((out / "index.md").is_file())
        group_files = list((out / "groups").glob("*.md"))
        self.assertEqual(3, len(group_files))
        self.assertFalse((self.root / "escape.md").exists())
        core_path = next((out / "groups").glob("core-*.md"))
        core = core_path.read_text(encoding="utf-8")
        self.assertIn("Source: `backend/a.py:4`", core)
        self.assertIn("depends on", core)

    def test_wiki_indexes_each_edge_once_for_large_graph(self):
        node_count = 1200
        nodes = [
            {"id": str(index), "name": f"Node {index}", "community": "large"}
            for index in range(node_count)
        ]
        edges = [
            {"source": str(index), "target": str((index + 1) % node_count)}
            for index in range(node_count)
        ]
        edges.append({"source": "1", "target": "0"})
        edges.extend(
            {"source": str(index), "target": str((index + 17) % node_count)}
            for index in range(node_count)
        )
        graph = {"nodes": nodes, "links": edges}
        out = self.runtime / "exports" / "large-wiki"
        original_edge_ends = views.edge_ends
        with patch.object(views, "edge_ends", wraps=original_edge_ends) as endpoints:
            self.export_wiki(graph, out)
        self.assertEqual(len(edges), endpoints.call_count)
        page = next((out / "groups").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("called by / referenced by", page)
        self.assertIn("depends on", page)

    def test_wiki_group_collisions_and_existing_output_are_safe(self):
        graph = {
            "nodes": [
                {"id": "1", "name": "One", "community": "a b"},
                {"id": "2", "name": "Two", "community": "a-b"},
                {"id": "3", "name": "Three", "community": "x" * 80 + "first"},
                {"id": "4", "name": "Four", "community": "x" * 80 + "second"},
            ]
        }
        out = self.runtime / "exports" / "collision-wiki"
        self.export_wiki(graph, out)
        files = list((out / "groups").glob("*.md"))
        self.assertEqual(4, len(files))
        contents = "\n".join(path.read_text(encoding="utf-8") for path in files)
        for name in ("One", "Two", "Three", "Four"):
            self.assertIn(name, contents)
        with self.assertRaisesRegex(ValueError, "must be empty"):
            self.export_wiki({"nodes": []}, out)

    def test_inline_code_uses_safe_delimiter(self):
        raw = "prefix `ticks`\nsecond line"
        code = views.md_code(raw)
        self.assertTrue(code.startswith("``"))
        self.assertIn("prefix `ticks` second line", code)

    def test_load_graph_rejects_malformed_nodes_and_edges(self):
        path = self.root / "bad.json"
        for data in (
            {"nodes": [None]},
            {"nodes": [{"id": []}]},
            {"nodes": [], "links": [{"source": {}, "target": "x"}]},
        ):
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(TypeError):
                views.load_graph(path)

    def test_query_explain_and_bounded_directed_paths(self):
        self.assertEqual(
            ["Beta"], [n["name"] for n in views.search(self.graph, "beta")]
        )
        explained = views.explain(self.graph, "b")
        self.assertEqual(1, len(explained["incoming"]))
        self.assertEqual(1, len(explained["outgoing"]))
        self.assertEqual(["a", "b", "c"], views.find_path(self.graph, "a", "c"))
        self.assertIsNone(views.find_path(self.graph, "c", "a"))
        self.assertEqual(
            ["c", "b", "a"], views.find_path(self.graph, "c", "a", directed=False)
        )
        with self.assertRaises(ValueError):
            views.find_path(self.graph, "a", "c", limit=1000)


if __name__ == "__main__":
    unittest.main()
