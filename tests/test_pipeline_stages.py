import contextlib
import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pipeline


class PipelineStagesTest(unittest.TestCase):
    def stages(self, root, without_budget=False):
        return pipeline.build_stages(root / "pdf", root / "ro", root / "work", root / "export",
                                     without_budget=without_budget)

    def test_default_range_and_invalid_selections(self):
        args = pipeline.parse_args([])
        self.assertEqual((args.from_stage, args.to_stage), ("extract", "export"))
        for argv in (["--from-stage", "export", "--to-stage", "extract"],
                     ["--from-stage", "unknown"], ["--from-phase", "3"], ["--to-phase", "9"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    pipeline.parse_args(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_one_export_uses_same_final_dataset_as_index(self):
        stages = self.stages(Path("example"))
        commands = [step["command"] for stage in stages for step in stage["operations"] if step["command"]]
        render = [cmd for cmd in commands if cmd[1] == "phase5_static_export.py"]
        self.assertEqual(len(render), 1)
        index = next(cmd for cmd in commands if cmd[1] == "phase4_index_build.py")
        self.assertEqual(index[index.index("--input") + 1], render[0][render[0].index("--input") + 1])
        self.assertIn("rozpoctova-opatreni-linked/usneseni.json", index[index.index("--input") + 1])

    def test_full_dry_run_does_not_create_outputs_or_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pdf").mkdir()
            (root / "ro").mkdir()
            (root / "pdf/resolution.pdf").touch()
            (root / "ro/budget.pdf").touch()
            argv = ["--pdf", str(root / "pdf"), "--ro-pdf", str(root / "ro"),
                    "--workdir", str(root / "work"), "--export", str(root / "export"),
                    "--classifier-cache", str(root / "cache"), "--dry-run"]
            with patch("pipeline.subprocess.run") as execute, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(pipeline.main(argv), 0)
            execute.assert_not_called()
            self.assertFalse((root / "work").exists())
            self.assertFalse((root / "export").exists())
            self.assertFalse((root / "cache").exists())
            self.assertEqual(output.getvalue().count("DRY RUN:"), 8)

    def test_export_only_skips_pdf_inputs_and_model_operations(self):
        with patch("pipeline.output_exists", return_value=True), \
                patch("pipeline.run_operation", return_value=True) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pipeline.main(["--from-stage", "export", "--pdf", "/missing"]), 0)
        scripts = [call.args[1][1] for call in run.call_args_list]
        self.assertEqual(scripts, ["phase4_index_build.py", "phase4_ro_index_build.py", "phase5_static_export.py"])

    def test_individual_enrich_stage_does_not_export(self):
        with patch("pipeline.output_exists", return_value=True), \
                patch("pipeline.run_operation", return_value=True) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pipeline.main(["--from-stage", "enrich", "--to-stage", "enrich"]), 0)
        self.assertEqual([call.args[1][1] for call in run.call_args_list],
                         ["phase2_resolution_analysis.py", "phase3_resolve_references.py", "crosslink_rozpoctova_opatreni.py"])

    def test_extract_only_preserves_existing_records_and_excludes_budget_pdfs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "resources"
            ro = pdf / "budget"
            ro.mkdir(parents=True)
            (pdf / "resolution.pdf").touch()
            (ro / "budget.pdf").touch()
            raw = root / "work/phase1"
            raw.mkdir(parents=True)
            previous = raw / "previous.json"
            previous.write_text("previous record")
            parsed_budget = root / "work/rozpoctova-opatreni"
            parsed_budget.mkdir()
            (parsed_budget / "previous.json").write_text("previous budget")
            with patch("pipeline.subprocess.run") as run, contextlib.redirect_stdout(io.StringIO()):
                run.return_value.returncode = 0
                self.assertEqual(pipeline.main(["--pdf", str(pdf), "--ro-pdf", str(ro),
                                                "--workdir", str(root / "work"), "--to-stage", "extract"]), 0)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual([cmd[1] for cmd in commands], ["phase1_parse_pdf.py", "parse_rozpoctova_opatreni.py"])
            self.assertEqual(commands[0][2], str(pdf))
            self.assertEqual(previous.read_text(), "previous record")
            self.assertFalse((root / "work/phase3").exists())

    def test_missing_inputs_fail_before_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("pipeline.run_operation") as run, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(pipeline.main(["--from-stage", "export", "--workdir", directory]), 1)
            run.assert_not_called()
            self.assertIn("export", output.getvalue())

    def test_operation_and_output_failures_stop_remaining_operations(self):
        with patch("pipeline.output_exists", return_value=True), \
                patch("pipeline.run_operation", return_value=False) as run, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(pipeline.main(["--from-stage", "export"]), 1)
        self.assertEqual(run.call_count, 1)
        self.assertIn("Index usnesení", output.getvalue())
        # Two prerequisite checks succeed, but the first operation's output is missing.
        with patch("pipeline.output_exists", side_effect=[True, True, False]), \
                patch("pipeline.run_operation", return_value=True) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pipeline.main(["--from-stage", "export"]), 1)
        self.assertEqual(run.call_count, 1)

    def test_without_budget_never_uses_stale_linked_data(self):
        stages = self.stages(Path("example"), without_budget=True)
        commands = [step["command"] for stage in stages for step in stage["operations"] if step["command"]]
        self.assertFalse(any("rozpoctova-opatreni-linked" in " ".join(cmd) for cmd in commands))
        self.assertFalse(any(cmd[1] in {"parse_rozpoctova_opatreni.py", "crosslink_rozpoctova_opatreni.py",
                                       "phase4_ro_index_build.py"} for cmd in commands))
        render = next(cmd for cmd in commands if cmd[1] == "phase5_static_export.py")
        self.assertIn("--without-budget", render)
        self.assertEqual(render[render.index("--input") + 1], "example/work/phase4/usneseni.json")

    def test_resolution_only_export_ignores_auto_detected_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "work/phase4"
            source.mkdir(parents=True)
            (source / "rozpoctova-opatreni").mkdir()
            (source / "rozpoctova-opatreni/invalid.json").write_text("invalid JSON must not be read")
            (source / "usneseni.json").write_text(json.dumps([{
                "id": "RM/1/1/2022", "datum": "2022-10-27", "organ": "Rada města Litovel",
                "actions": ["schvaluje"], "subject": "kulturní akci", "items": [], "amounts": [],
                "classification": {"category": "culture", "source": "manual_override", "status": "classified"},
            }]))
            # Actual index and static-export scripts execute; there is no inference.
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.main(["--from-stage", "export", "--without-budget",
                                                "--workdir", str(root / "work"), "--export", str(root / "export")]), 0)
            data = json.loads((root / "export/assets/usneseni/data/2022.json").read_text())
            self.assertEqual(data[0]["classification"]["source"], "manual_override")
            self.assertFalse((root / "export/rozpoctova-opatreni").exists())


class IncrementalWorkflowTest(unittest.TestCase):
    def test_workflow_release_defaults_and_organization_match_runtime(self):
        from resolution_classification import DEFAULT_SHA256, DEFAULT_URL

        self.assertTrue(DEFAULT_URL.startswith("https://github.com/litovle/litovel-resolution-classifier/"))
        repo = Path(pipeline.__file__).resolve().parent
        for filename in ("sync-litovel-notices.yml", "manual-litovel-pdf.yml"):
            with self.subTest(workflow=filename):
                text = (repo / ".github/workflows" / filename).read_text()
                url = re.search(r"CLASSIFIER_URL:.*\|\| '([^']+)'", text).group(1)
                checksum = re.search(r"CLASSIFIER_SHA256:.*\|\| '([^']+)'", text).group(1)
                self.assertEqual((url, checksum), (DEFAULT_URL, DEFAULT_SHA256))
                self.assertIn("repository: litovle/litovle.cz", text)

    def test_workflows_parse_only_selected_files_then_enrich_and_export(self):
        repo = Path(pipeline.__file__).resolve().parent
        for filename, manifest_name, kinds in [
            ("sync-litovel-notices.yml", ".litovel-sync-manifest.json", ["resolution"]),
            ("sync-litovel-notices.yml", ".litovel-sync-manifest.json", ["budget_change"]),
            ("sync-litovel-notices.yml", ".litovel-sync-manifest.json", ["resolution", "budget_change"]),
            ("manual-litovel-pdf.yml", ".litovel-manual-manifest.json", ["resolution"]),
            ("manual-litovel-pdf.yml", ".litovel-manual-manifest.json", ["budget_change"]),
        ]:
            with self.subTest(workflow=filename, kinds=kinds), tempfile.TemporaryDirectory() as directory:
                text = (repo / ".github/workflows" / filename).read_text()
                embedded = re.search(r"          python - <<'PY'\n(.*?)\n          PY", text, re.S).group(1)
                program = "\n".join(line[10:] for line in embedded.splitlines())
                root = Path(directory)
                raw = root / "work/phase1"
                raw.mkdir(parents=True)
                existing = raw / "existing.json"
                existing.write_text("unchanged existing record")
                selected = [{"kind": kind, "path": f"selected-{index}.pdf"} for index, kind in enumerate(kinds)]
                (root / manifest_name).write_text(json.dumps({"downloaded": selected}))
                original_cwd = Path.cwd()
                try:
                    os.chdir(root)
                    with patch.dict(os.environ, {"CLASSIFIER_URL": "https://example.org/model", "CLASSIFIER_SHA256": "a" * 64}), \
                            patch("subprocess.run") as run:
                        exec(compile(program, filename, "exec"), {})
                finally:
                    os.chdir(original_cwd)
                commands = [call.args[0] for call in run.call_args_list]
                self.assertEqual(len(commands), len(selected) + 1)
                for item, command in zip(selected, commands):
                    expected = "phase1_parse_pdf.py" if item["kind"] == "resolution" else "parse_rozpoctova_opatreni.py"
                    self.assertEqual(command[1:3], [expected, item["path"]])
                command = commands[-1]
                self.assertEqual(command[1], "pipeline.py")
                self.assertEqual(command[command.index("--from-stage") + 1], "enrich")
                self.assertEqual(command[command.index("--to-stage") + 1], "export")
                self.assertEqual(existing.read_text(), "unchanged existing record")


if __name__ == "__main__":
    unittest.main()
