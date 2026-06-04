#!/usr/bin/env python3
"""
Memoria local de escenas aprendidas.

Registra eventos estructurados, detecta patrones repetidos y crea escenas
candidatas. Este modulo no ejecuta musica ni luces.
"""

import json
import os
import re
import shutil
import threading
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEGACY_MEMORY_DIR = os.path.join(BASE_DIR, "memory")
DEFAULT_MEMORY_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "pearl-home", "scene-memory")
MEMORY_DIR = os.getenv("JARVIS_LOCAL_SCENE_MEMORY_DIR") or DEFAULT_MEMORY_DIR
EVENTS_FILE = os.path.join(MEMORY_DIR, "events.json")
SCENES_FILE = os.path.join(MEMORY_DIR, "learned_scenes.json")
LEGACY_EVENTS_FILE = os.path.join(LEGACY_MEMORY_DIR, "events.json")
LEGACY_SCENES_FILE = os.path.join(LEGACY_MEMORY_DIR, "learned_scenes.json")

DEFAULT_MIN_REPETITIONS = 6
DEFAULT_MIN_UNIQUE_DAYS = 6

_lock = threading.Lock()


def _ensure_storage():
    os.makedirs(MEMORY_DIR, exist_ok=True)
    for path, legacy_path in ((EVENTS_FILE, LEGACY_EVENTS_FILE), (SCENES_FILE, LEGACY_SCENES_FILE)):
        if not os.path.exists(path):
            if os.path.abspath(path) != os.path.abspath(legacy_path) and os.path.exists(legacy_path):
                shutil.copy2(legacy_path, path)
            else:
                _write_json(path, [])
        os.chmod(path, 0o600)


def _read_json(path: str) -> List[Dict]:
    _ensure_storage()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_json(path: str, data: List[Dict]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)


def _now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _parse_time(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return "unknown"
    value = value.strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value or "unknown"


def _brightness_bucket(value) -> str:
    try:
        brightness = int(value)
    except (TypeError, ValueError):
        return "unknown"

    if brightness <= 25:
        return "low"
    if brightness <= 60:
        return "medium"
    return "high"


def _time_window(dt: datetime) -> str:
    hour = dt.hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 23:
        return "evening"
    return "night"


def _event_signature(event: Dict) -> Tuple[str, str, str, str, str]:
    dt = _parse_time(event.get("timestamp"))
    music = event.get("music") or {}
    lights = event.get("lights") or {}

    music_key = _normalize_text(music.get("genre") or music.get("query"))
    color_key = _normalize_text(lights.get("color") or lights.get("scene"))
    brightness_key = _brightness_bucket(lights.get("brightness"))

    return (
        _normalize_text(event.get("intent")),
        music_key,
        color_key,
        brightness_key,
        _time_window(dt),
    )


def _scene_signature(scene: Dict) -> Optional[List[str]]:
    signature = scene.get("signature")
    return signature if isinstance(signature, list) else None


def _build_scene_from_group(signature: Tuple[str, str, str, str, str], events: List[Dict]) -> Dict:
    intent, music_key, color_key, brightness_key, time_key = signature
    latest_event = max(events, key=lambda item: item.get("timestamp", ""))
    music = latest_event.get("music") or {}
    lights = latest_event.get("lights") or {}

    scene_id = "scene_" + uuid.uuid4().hex[:12]
    readable_intent = intent.replace("_", " ")
    readable_music = music_key.replace("_", " ")
    readable_color = color_key.replace("_", " ")

    return {
        "id": scene_id,
        "name": f"{readable_intent} con {readable_music} y luz {readable_color}",
        "status": "candidate",
        "confidence": min(0.95, round(0.45 + (len(events) * 0.07), 2)),
        "evidence_count": len(events),
        "unique_days": len({(_parse_time(item.get("timestamp")).date().isoformat()) for item in events}),
        "first_seen": min(item.get("timestamp", "") for item in events),
        "last_seen": latest_event.get("timestamp"),
        "signature": list(signature),
        "trigger": {
            "intent": intent,
            "time_window": time_key,
            "requires_confirmation": True,
        },
        "actions": {
            "music": {
                "action": "play",
                "query": music.get("query") or music_key,
                "genre": music.get("genre"),
            },
            "lights": {
                "action": "set",
                "color": lights.get("color") or lights.get("scene") or color_key,
                "brightness": lights.get("brightness"),
                "scene": lights.get("scene"),
            },
        },
        "safety": {
            "requires_confirmation": True,
            "auto_execute": False,
        },
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "execution_count": 0,
        "last_confirmed_at": None,
    }


def record_event(event: Dict) -> Dict:
    if not isinstance(event, dict):
        raise ValueError("El evento debe ser un objeto JSON")

    normalized = {
        "id": event.get("id") or "event_" + uuid.uuid4().hex[:12],
        "timestamp": event.get("timestamp") or _now_iso(),
        "intent": _normalize_text(event.get("intent")),
        "music": event.get("music") if isinstance(event.get("music"), dict) else {},
        "lights": event.get("lights") if isinstance(event.get("lights"), dict) else {},
        "source": event.get("source") or "unknown",
        "metadata": event.get("metadata") if isinstance(event.get("metadata"), dict) else {},
    }

    with _lock:
        events = _read_json(EVENTS_FILE)
        events.append(normalized)
        _write_json(EVENTS_FILE, events)
        candidates = detect_candidates_locked(events)

    return {
        "event": normalized,
        "candidates_created": candidates,
    }


def list_events(limit: int = 50) -> List[Dict]:
    with _lock:
        events = _read_json(EVENTS_FILE)
    return events[-limit:]


def list_scenes(status: Optional[str] = None) -> List[Dict]:
    with _lock:
        scenes = _read_json(SCENES_FILE)
    if status:
        return [scene for scene in scenes if scene.get("status") == status]
    return scenes


def detect_candidates_locked(events: Optional[List[Dict]] = None) -> List[Dict]:
    events = events if events is not None else _read_json(EVENTS_FILE)
    scenes = _read_json(SCENES_FILE)
    existing_signatures = {
        tuple(signature)
        for signature in (_scene_signature(scene) for scene in scenes)
        if signature
    }

    grouped = defaultdict(list)
    for event in events:
        signature = _event_signature(event)
        if "unknown" in signature[:3]:
            continue
        grouped[signature].append(event)

    created = []
    for signature, group in grouped.items():
        unique_days = {
            _parse_time(item.get("timestamp")).date().isoformat()
            for item in group
        }
        if len(group) < DEFAULT_MIN_REPETITIONS:
            continue
        if len(unique_days) < DEFAULT_MIN_UNIQUE_DAYS:
            continue
        if signature in existing_signatures:
            continue

        scene = _build_scene_from_group(signature, group)
        scenes.append(scene)
        existing_signatures.add(signature)
        created.append(scene)

    if created:
        _write_json(SCENES_FILE, scenes)

    return created


def detect_candidates() -> List[Dict]:
    with _lock:
        return detect_candidates_locked()


def update_scene_status(scene_id: str, status: str) -> Optional[Dict]:
    if status not in {"candidate", "approved", "rejected", "archived"}:
        raise ValueError("Estado de escena invalido")

    with _lock:
        scenes = _read_json(SCENES_FILE)
        for scene in scenes:
            if scene.get("id") == scene_id:
                scene["status"] = status
                scene["updated_at"] = _now_iso()
                if status == "approved":
                    scene["last_confirmed_at"] = _now_iso()
                _write_json(SCENES_FILE, scenes)
                return scene
    return None


def suggest_scene(context: Optional[Dict] = None) -> Optional[Dict]:
    context = context or {}
    intent = _normalize_text(context.get("intent")) if context.get("intent") else None
    now = _parse_time(context.get("timestamp"))
    current_window = _time_window(now)

    scenes = [
        scene for scene in list_scenes()
        if scene.get("status") in {"candidate", "approved"}
    ]

    scored = []
    for scene in scenes:
        trigger = scene.get("trigger") or {}
        score = float(scene.get("confidence") or 0)
        if intent and trigger.get("intent") == intent:
            score += 0.2
        if trigger.get("time_window") == current_window:
            score += 0.1
        scored.append((score, scene))

    if not scored:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    scene = scored[0][1]
    return {
        "scene": scene,
        "requires_confirmation": True,
        "suggestion": f"Detecte un patron: {scene.get('name')}. Quieres activar esta escena?",
    }
