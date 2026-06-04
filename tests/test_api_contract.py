import unittest

import orchestrator


class HubApiContractTest(unittest.TestCase):
    def setUp(self):
        orchestrator.app.config.update(TESTING=True)
        self.client = orchestrator.app.test_client()

    def test_product_identity_marks_hub_beta(self):
        identity = orchestrator.product_identity()

        self.assertEqual(identity["edition"], "hub")
        self.assertEqual(identity["api_version"], "v1")
        self.assertTrue(identity["version"].startswith("0.7.0-beta."))

    def test_legacy_and_versioned_status_routes_remain_available(self):
        for route in ("/status", "/api/v1/status"):
            response = self.client.get(route)
            payload = response.get_json()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(payload["status"], "online")
            self.assertEqual(payload["product"]["edition"], "hub")

    def test_all_public_routes_have_versioned_aliases(self):
        rules = {rule.rule for rule in orchestrator.app.url_map.iter_rules()}
        expected = {
            "/api/v1/process",
            "/api/v1/health",
            "/api/v1/intents",
            "/api/v1/status",
            "/api/v1/memory/event",
            "/api/v1/memory/events",
            "/api/v1/scenes",
            "/api/v1/scenes/candidates",
            "/api/v1/scenes/detect",
            "/api/v1/scenes/suggest",
            "/api/v1/scenes/<scene_id>/approve",
            "/api/v1/scenes/<scene_id>/reject",
            "/api/v1/scene-prompts/pending",
            "/api/v1/scene-prompts/<prompt_id>/decision",
        }

        self.assertTrue(expected.issubset(rules))


if __name__ == "__main__":
    unittest.main()
