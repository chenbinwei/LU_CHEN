import unittest
import warnings

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)
from fastapi.testclient import TestClient

from video_slicer.api.app import create_app


class ApiAppTest(unittest.TestCase):
    def test_health_route_returns_local_backend_status(self):
        client = TestClient(create_app())

        response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["service"], "video-slicer-local-api")

    def test_context_schema_route_exposes_editable_fields(self):
        client = TestClient(create_app())

        response = client.get("/api/context/schema")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["version"], 1)
        field_keys = [field["key"] for field in body["fields"]]
        self.assertIn("correct_synopsis", field_keys)
        self.assertIn("characters", field_keys)
        self.assertIn("tts_unfriendly_terms", field_keys)


if __name__ == "__main__":
    unittest.main()
