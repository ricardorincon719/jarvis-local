import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import orchestrator
from scene_prompts import ScenePromptStore


SCENE = {
    "id": "scene_test",
    "name": "Jazz y luz calida",
    "status": "candidate",
}


class ScenePromptStoreTest(unittest.TestCase):
    def test_candidate_prompt_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ScenePromptStore(str(Path(temp_dir) / "prompts.json"))

            first = store.enqueue_candidate(SCENE)
            second = store.enqueue_candidate(SCENE)

            self.assertEqual(first["id"], second["id"])
            self.assertEqual(len(store.list_pending()), 1)

    def test_decision_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ScenePromptStore(str(Path(temp_dir) / "prompts.json"))
            prompt = store.enqueue_candidate(SCENE)

            first, first_changed = store.decide(prompt["id"], "accept", "decision-1")
            second, second_changed = store.decide(prompt["id"], "accept", "decision-1")

            self.assertTrue(first_changed)
            self.assertFalse(second_changed)
            self.assertEqual(first["status"], "accepted")
            self.assertEqual(second["decision"], "accept")

    def test_expired_prompt_is_not_pending(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ScenePromptStore(str(Path(temp_dir) / "prompts.json"))
            prompt = store.enqueue_candidate(SCENE)
            old_time = datetime.now(timezone.utc) - timedelta(minutes=1)

            with patch.object(store, "_now", return_value=old_time - timedelta(minutes=1)):
                activation = store.enqueue_activation({**SCENE, "status": "approved"}, "Activar escena")
            with patch.object(store, "_now", return_value=old_time + timedelta(minutes=31)):
                pending = store.list_pending()

            self.assertIn(prompt["id"], {item["id"] for item in pending})
            self.assertNotIn(activation["id"], {item["id"] for item in pending})


class ScenePromptApiTest(unittest.TestCase):
    def setUp(self):
        orchestrator.app.config.update(TESTING=True)
        self.client = orchestrator.app.test_client()

    def test_candidate_accept_is_applied_once_and_never_executes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ScenePromptStore(str(Path(temp_dir) / "prompts.json"))
            prompt = store.enqueue_candidate(SCENE)

            with patch.object(orchestrator, "scene_prompt_store", store), patch.object(
                orchestrator,
                "update_scene_status",
                return_value={**SCENE, "status": "approved"},
            ) as update_status:
                first = self.client.post(
                    f"/api/v1/scene-prompts/{prompt['id']}/decision",
                    json={"decision": "accept", "idempotency_key": "decision-1"},
                )
                second = self.client.post(
                    f"/api/v1/scene-prompts/{prompt['id']}/decision",
                    json={"decision": "accept", "idempotency_key": "decision-1"},
                )

            self.assertEqual(first.status_code, 200)
            self.assertTrue(first.get_json()["decision_applied"])
            self.assertFalse(first.get_json()["executed"])
            self.assertFalse(second.get_json()["decision_applied"])
            update_status.assert_called_once_with("scene_test", "approved")

    def test_decision_requires_core_gateway_token_when_configured(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ScenePromptStore(str(Path(temp_dir) / "prompts.json"))
            prompt = store.enqueue_candidate(SCENE)

            with patch.object(orchestrator, "scene_prompt_store", store), patch.object(
                orchestrator, "CORE_GATEWAY_TOKEN", "secret"
            ):
                blocked = self.client.post(
                    f"/api/v1/scene-prompts/{prompt['id']}/decision",
                    json={"decision": "accept", "idempotency_key": "decision-1"},
                )
                allowed = self.client.post(
                    f"/api/v1/scene-prompts/{prompt['id']}/decision",
                    headers={"X-PEARL-Core-Gateway": "secret"},
                    json={"decision": "accept", "idempotency_key": "decision-1"},
                )

            self.assertEqual(blocked.status_code, 403)
            self.assertEqual(blocked.get_json()["error"], "core_gateway_required")
            self.assertEqual(allowed.status_code, 200)

    def test_pending_endpoint_returns_prompts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ScenePromptStore(str(Path(temp_dir) / "prompts.json"))
            store.enqueue_candidate(SCENE)

            with patch.object(orchestrator, "scene_prompt_store", store):
                response = self.client.get("/api/v1/scene-prompts/pending")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.get_json()["prompts"]), 1)


if __name__ == "__main__":
    unittest.main()
