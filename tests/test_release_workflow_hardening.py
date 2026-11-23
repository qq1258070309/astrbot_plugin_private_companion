"""Release workflow hardening: gate failures must fail the job (offline text checks)."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class ReleaseWorkflowFailClosedTests(unittest.TestCase):
    def test_no_workflow_hardcodes_a_passing_gate_result(self):
        for path in sorted(WORKFLOWS.glob("*.yml")):
            with self.subTest(workflow=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("echo '" + '{"result":"pass"}' + "' >", text)
                self.assertNotIn("continue-on-error: true", text)

    def test_gates_use_fail_closed_runner_and_assert_its_verdict(self):
        for name in ("sync-release.yml", "release-current.yml", "release-tag.yml"):
            with self.subTest(workflow=name):
                text = (WORKFLOWS / name).read_text(encoding="utf-8")
                self.assertIn("tools/run_release_gates.sh", text)
                expected = "grep -qx '" + '{"result":"pass"}' + "' \"$RUNNER_TEMP/gates.json\""
                self.assertIn(expected, text)

    def test_publish_is_guarded_by_gate_success_and_asset_preflight(self):
        for name in ("sync-release.yml", "release-current.yml", "release-tag.yml"):
            with self.subTest(workflow=name):
                text = (WORKFLOWS / name).read_text(encoding="utf-8")
                self.assertIn("steps.gates.outcome == 'success'", text)
                self.assertIn("sha256sum -c SHA256SUMS.txt", text)
                self.assertIn("missing or empty release asset", text)


if __name__ == "__main__":
    unittest.main()
