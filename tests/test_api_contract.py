import unittest
from unittest.mock import patch

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


    def test_every_route_requires_core_gateway_token_when_configured(self):
        with patch.object(orchestrator, "CORE_GATEWAY_TOKEN", "secret"):
            for route in ("/status", "/api/v1/health", "/scenes"):
                for headers in ({}, {"X-PEARL-Core-Gateway": "otro"}):
                    response = self.client.get(route, headers=headers)
                    self.assertEqual(response.status_code, 403, route)
                    self.assertEqual(
                        response.get_json()["error"], "core_gateway_required"
                    )

            response = self.client.get(
                "/status", headers={"X-PEARL-Core-Gateway": "secret"}
            )
            self.assertEqual(response.status_code, 200)

    def test_http_server_refuses_to_start_without_token(self):
        with patch.object(orchestrator, "CORE_GATEWAY_TOKEN", ""), patch(
            "waitress.serve"
        ) as serve:
            with self.assertRaises(SystemExit):
                orchestrator.run_http_server()

        serve.assert_not_called()

    def test_http_server_runs_on_waitress(self):
        with patch.object(orchestrator, "CORE_GATEWAY_TOKEN", "secret"), patch(
            "waitress.serve"
        ) as serve:
            orchestrator.run_http_server()

        serve.assert_called_once()
        self.assertIs(serve.call_args.args[0], orchestrator.app)


if __name__ == "__main__":
    unittest.main()
