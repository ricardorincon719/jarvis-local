import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from scene_memory import MEMORY_DIR


PROMPTS_FILE = os.path.join(MEMORY_DIR, "scene_prompts.json")
ALLOWED_KINDS = {"candidate_approval", "activation_suggestion"}
ALLOWED_DECISIONS = {"accept", "cancel"}


class ScenePromptStore:
    def __init__(self, path: str = PROMPTS_FILE):
        self.path = path
        self._lock = threading.Lock()

    def enqueue_candidate(self, scene: Dict) -> Dict:
        return self.enqueue(
            kind="candidate_approval",
            scene=scene,
            title="Nueva escena aprendida",
            message=f"PEARL aprendio '{scene.get('name')}'. ¿Quieres aprobarla?",
            expires_in_minutes=7 * 24 * 60,
        )

    def enqueue_activation(self, scene: Dict, message: str) -> Dict:
        return self.enqueue(
            kind="activation_suggestion",
            scene=scene,
            title="Escena sugerida",
            message=message,
            expires_in_minutes=30,
        )

    def enqueue(
        self,
        kind: str,
        scene: Dict,
        title: str,
        message: str,
        expires_in_minutes: int,
    ) -> Dict:
        if kind not in ALLOWED_KINDS:
            raise ValueError("Tipo de propuesta invalido")
        scene_id = str(scene.get("id") or "").strip()
        if not scene_id:
            raise ValueError("La propuesta requiere scene_id")

        with self._lock:
            prompts = self._read()
            for prompt in reversed(prompts):
                if prompt.get("kind") == kind and prompt.get("scene_id") == scene_id:
                    if kind == "candidate_approval" or prompt.get("status") == "pending":
                        return prompt

            now = self._now()
            prompt = {
                "id": "prompt_" + uuid.uuid4().hex[:12],
                "kind": kind,
                "scene_id": scene_id,
                "scene_name": scene.get("name") or scene_id,
                "title": title,
                "message": message,
                "status": "pending",
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(minutes=max(1, expires_in_minutes))).isoformat(),
                "decision": None,
                "decided_at": None,
                "idempotency_key": None,
            }
            prompts.append(prompt)
            self._write(prompts[-1000:])
            return prompt

    def list_pending(self, kind: Optional[str] = None) -> List[Dict]:
        with self._lock:
            prompts = self._read()
            changed = self._expire_locked(prompts)
            if changed:
                self._write(prompts)
            return [
                prompt
                for prompt in prompts
                if prompt.get("status") == "pending" and (not kind or prompt.get("kind") == kind)
            ]

    def get(self, prompt_id: str) -> Optional[Dict]:
        with self._lock:
            prompts = self._read()
            changed = self._expire_locked(prompts)
            if changed:
                self._write(prompts)
            for prompt in prompts:
                if prompt.get("id") == prompt_id:
                    return dict(prompt)
        return None

    def decide(self, prompt_id: str, decision: str, idempotency_key: str) -> Tuple[Optional[Dict], bool]:
        if decision not in ALLOWED_DECISIONS:
            raise ValueError("Decision invalida")
        if not str(idempotency_key or "").strip():
            raise ValueError("Se requiere idempotency_key")

        with self._lock:
            prompts = self._read()
            self._expire_locked(prompts)
            for prompt in prompts:
                if prompt.get("id") != prompt_id:
                    continue
                if prompt.get("status") != "pending":
                    self._write(prompts)
                    return dict(prompt), False

                prompt["status"] = "accepted" if decision == "accept" else "cancelled"
                prompt["decision"] = decision
                prompt["decided_at"] = self._now().isoformat()
                prompt["idempotency_key"] = str(idempotency_key).strip()[:160]
                self._write(prompts)
                return dict(prompt), True
        return None, False

    def _expire_locked(self, prompts: List[Dict]) -> bool:
        now = self._now()
        changed = False
        for prompt in prompts:
            if prompt.get("status") != "pending":
                continue
            expires_at = self._parse_time(prompt.get("expires_at"))
            if expires_at is None or expires_at <= now:
                prompt["status"] = "expired"
                changed = True
        return changed

    def _read(self) -> List[Dict]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as file_handle:
                data = json.load(file_handle)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _write(self, prompts: List[Dict]):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temp_path = f"{self.path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as file_handle:
            json.dump(prompts, file_handle, ensure_ascii=False, indent=2)
            file_handle.write("\n")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, self.path)

    @staticmethod
    def _now() -> datetime:
        return datetime.now().astimezone().replace(microsecond=0)

    @staticmethod
    def _parse_time(value: Optional[str]) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None
