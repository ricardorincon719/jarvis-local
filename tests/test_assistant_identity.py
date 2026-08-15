import unittest

import orchestrator
from assistant_identity import build_assistant_prompt


class AssistantIdentityTest(unittest.TestCase):
    def test_shared_prompt_defines_jarvis_identity(self):
        prompt = build_assistant_prompt("Como te llamas?")

        self.assertIn("Tu nombre es JARVIS", prompt)
        self.assertIn("asistente local de PEARL HOME", prompt)
        self.assertIn("No te presentes como Qwen", prompt)
        self.assertTrue(prompt.endswith("JARVIS:"))

    def test_every_hub_brain_receives_identity(self):
        for brain_name in orchestrator.BRAINS:
            prompt = orchestrator.build_prompt(brain_name, "Quien eres?")
            self.assertIn("Tu nombre es JARVIS", prompt)
            self.assertEqual(prompt.count("INSTRUCCIONES DE IDENTIDAD"), 1)


if __name__ == "__main__":
    unittest.main()
