import unittest
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
from fastapi.testclient import TestClient

from video_slicer.api.app import create_app


class FrontendStaticTest(unittest.TestCase):
    def test_root_serves_workspace_html(self):
        client = TestClient(create_app())

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("视频切片工作台", response.text)
        self.assertIn('/assets/styles.css', response.text)
        self.assertIn('/assets/app.js', response.text)

    def test_static_assets_are_served(self):
        client = TestClient(create_app())

        css = client.get("/assets/styles.css")
        js = client.get("/assets/app.js")

        self.assertEqual(css.status_code, 200)
        self.assertIn(".workspace", css.text)
        self.assertEqual(js.status_code, 200)
        self.assertIn("requestJson", js.text)

    def test_frontend_contains_required_workspace_controls(self):
        html = Path("frontend/index.html").read_text(encoding="utf-8")

        required_ids = [
            "projectForm",
            "sourceVideoPath",
            "sourceDurationSeconds",
            "contextForm",
            "contextTitle",
            "correctSynopsis",
            "storyFocus",
            "versionForm",
            "targetDurationSeconds",
            "voiceCloneId",
            "bgmPath",
            "renderForm",
            "ttsMode",
            "jobList",
        ]
        for element_id in required_ids:
            self.assertIn(f'id="{element_id}"', html)

    def test_frontend_javascript_uses_backend_contract(self):
        script = Path("frontend/app.js").read_text(encoding="utf-8")

        required_snippets = [
            'requestJson("/api/projects"',
            "source_duration_seconds",
            "context_packet",
            "target_duration_seconds",
            "voice_clone_id",
            "bgm_path",
            "voiceover_speed",
            "targetDuration >= state.selectedProject.source_duration_seconds",
            "setInterval",
            "clearInterval",
        ]
        for snippet in required_snippets:
            self.assertIn(snippet, script)


if __name__ == "__main__":
    unittest.main()
