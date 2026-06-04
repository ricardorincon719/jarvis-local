import json
import os
import tempfile
import unittest
from unittest.mock import patch

import scene_memory


class SceneMemoryStorageTest(unittest.TestCase):
    def test_legacy_memory_is_copied_to_private_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_dir = os.path.join(temp_dir, "legacy")
            private_dir = os.path.join(temp_dir, "private")
            legacy_events = os.path.join(legacy_dir, "events.json")
            legacy_scenes = os.path.join(legacy_dir, "learned_scenes.json")
            private_events = os.path.join(private_dir, "events.json")
            private_scenes = os.path.join(private_dir, "learned_scenes.json")
            os.makedirs(legacy_dir)

            with open(legacy_events, "w", encoding="utf-8") as file_handle:
                json.dump([{"id": "event_existing"}], file_handle)
            with open(legacy_scenes, "w", encoding="utf-8") as file_handle:
                json.dump([{"id": "scene_existing"}], file_handle)

            with patch.multiple(
                scene_memory,
                MEMORY_DIR=private_dir,
                EVENTS_FILE=private_events,
                SCENES_FILE=private_scenes,
                LEGACY_EVENTS_FILE=legacy_events,
                LEGACY_SCENES_FILE=legacy_scenes,
            ):
                scene_memory._ensure_storage()

            with open(private_events, "r", encoding="utf-8") as file_handle:
                events = json.load(file_handle)
            with open(private_scenes, "r", encoding="utf-8") as file_handle:
                scenes = json.load(file_handle)

            self.assertEqual(events, [{"id": "event_existing"}])
            self.assertEqual(scenes, [{"id": "scene_existing"}])
            self.assertTrue(os.path.exists(legacy_events))
            self.assertTrue(os.path.exists(legacy_scenes))


if __name__ == "__main__":
    unittest.main()
