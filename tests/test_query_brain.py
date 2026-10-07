import json
import unittest
from unittest.mock import patch

import requests

import orchestrator


class FakeStream:
    """Respuesta de Ollama en streaming: una línea JSON por fragmento."""

    def __init__(self, chunks, status_code=200, fail_after=None):
        self.chunks = chunks
        self.status_code = status_code
        self.fail_after = fail_after
        self.text = ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self, decode_unicode=False):
        for index, chunk in enumerate(self.chunks):
            if self.fail_after is not None and index == self.fail_after:
                raise requests.exceptions.ReadTimeout("sin datos")
            yield json.dumps(chunk)


class QueryBrainStreamingTest(unittest.TestCase):
    def test_asks_ollama_in_streaming_and_joins_the_fragments(self):
        chunks = [{"response": "Hola, "}, {"response": "Ricardo."}, {"response": "", "done": True}]
        with patch.object(orchestrator.requests, "post", return_value=FakeStream(chunks)) as post:
            result = orchestrator.query_brain("cotidiano", "hola")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["response"], "Hola, Ricardo.")
        self.assertEqual(result["model"], "qwen2.5:0.5b")
        self.assertIs(post.call_args.kwargs["json"]["stream"], True)
        self.assertIs(post.call_args.kwargs["stream"], True)

    def test_cut_mid_answer_returns_what_arrived(self):
        chunks = [{"response": "Primera parte"}, {"response": " segunda"}]
        stream = FakeStream(chunks, fail_after=1)
        with patch.object(orchestrator.requests, "post", return_value=stream):
            result = orchestrator.query_brain("critico", "analiza")
        self.assertEqual((result["status"], result["response"]), ("success", "Primera parte"))
        self.assertTrue(result["truncated"])

    def test_timeout_before_any_data_is_an_error(self):
        with patch.object(orchestrator.requests, "post",
                          return_value=FakeStream([{"response": "x"}], fail_after=0)):
            result = orchestrator.query_brain("rapido", "hola")
        self.assertEqual(result["status"], "error")
        self.assertIn("Timeout", result["error"])

    def test_http_error_is_reported(self):
        with patch.object(orchestrator.requests, "post",
                          return_value=FakeStream([], status_code=500)):
            result = orchestrator.query_brain("rapido", "hola")
        self.assertEqual(result["status"], "error")
        self.assertIn("HTTP 500", result["error"])

    def test_fallback_models(self):
        models = {name: brain["model"] for name, brain in orchestrator.BRAINS.items()}
        self.assertEqual(models, {"rapido": "qwen2.5:0.5b", "cotidiano": "qwen2.5:0.5b",
                                  "critico": "llama3.2:3b"})


if __name__ == "__main__":
    unittest.main()
