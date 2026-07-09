import unittest
import warnings

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


if __name__ == "__main__":
    unittest.main()
