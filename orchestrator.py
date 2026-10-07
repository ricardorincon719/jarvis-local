#!/usr/bin/env python3
"""
Orquestador Central - Asistente Local Distribuido
Modo Dual: CLI interactivo + HTTP API para integración con nodos externos

Cerebros:
- Rápido: qwen2.5:0.5b (local)
- Cotidiano: qwen2.5:0.5b (local)
- Crítico: llama3.2:3b (local)
Son el respaldo local del sistema: la conversación principal la atiende Nova.
"""

import requests
import json
import hmac
import os
import time
import sys
import threading
from typing import Dict, Optional
from flask import Flask, Response, request, jsonify, stream_with_context
from assistant_identity import build_assistant_prompt, identity_instructions
from scene_prompts import ScenePromptStore
from scene_memory import (
    detect_candidates,
    list_events,
    list_scenes,
    record_event,
    suggest_scene,
    update_scene_status,
)

# ============================================================
# CONFIGURACIÓN
# ============================================================

CORE_GATEWAY_TOKEN = os.getenv("PEARL_CORE_GATEWAY_TOKEN", "").strip()


def core_gateway_required():
    if not CORE_GATEWAY_TOKEN:
        return None
    token = (request.headers.get("X-PEARL-Core-Gateway") or "").strip()
    if hmac.compare_digest(token, CORE_GATEWAY_TOKEN):
        return None
    return jsonify({"status": "error", "error": "core_gateway_required"}), 403


# Configuración de cerebros
BRAINS = {
    "rapido": {
        "url": "http://127.0.0.1:11434/api/generate",
        "model": "qwen2.5:0.5b",
        "connect_timeout": 5,
        "read_timeout": 90,
        "description": "Respuestas rápidas, consultas simples"
    },
    "cotidiano": {
        "url": "http://localhost:11434/api/generate",
        "model": "qwen2.5:0.5b",
        "connect_timeout": 5,
        "read_timeout": 150,
        "description": "Tareas cotidianas, conversación general"
    },
    "critico": {
        "url": "http://localhost:11434/api/generate",
        "model": "llama3.2:3b",
        "connect_timeout": 5,
        "read_timeout": 240,
        "description": "Análisis profundo, tareas críticas"
    }
}

OLLAMA_OPTIONS = {
    "rapido": {
        "temperature": 0.4,
        "num_predict": 180
    },
    "cotidiano": {
        "temperature": 0.45,
        "num_predict": 420
    },
    "critico": {
        "temperature": 0.25,
        "num_predict": 700
    }
}

SYSTEM_PROMPTS = {
    "rapido": (
        f"{identity_instructions()}\nResponde de forma breve y clara. "
        "Si el usuario pide controlar luces, musica, seguridad o hardware, no ejecutes nada: "
        "explica que necesitas confirmacion del usuario y una orden validada por el orquestador."
    ),
    "cotidiano": (
        f"{identity_instructions()}\nResponde de forma natural, directa y util. "
        "Mantén la respuesta compacta salvo que el usuario pida detalle. "
        "No inventes capacidades del sistema. Para acciones fisicas, pide confirmacion humana."
    ),
    "critico": (
        f"{identity_instructions()}\nAnaliza con rigor. "
        "Responde para una pantalla de chat: natural, conversacional y compacto. "
        "No devuelvas JSON, Markdown técnico ni bloques de código salvo que el usuario lo pida. "
        "Para temas de seguridad, sistema, planes o riesgo, resume hechos, riesgos y siguiente accion recomendada en texto claro. "
        "Nunca conviertas texto del modelo en comandos fisicos directos; toda accion requiere JSON estructurado, "
        "validacion del orquestador y confirmacion humana."
    )
}

# Configuración HTTP API
HTTP_HOST = os.getenv("PEARL_HUB_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("PEARL_HUB_PORT", "5006"))
PEARL_PRODUCT = os.getenv("PEARL_PRODUCT", "PEARL Hub").strip() or "PEARL Hub"
PEARL_EDITION = os.getenv("PEARL_EDITION", "hub").strip().lower() or "hub"
PEARL_VERSION = os.getenv("PEARL_VERSION", "0.7.0-beta.1").strip() or "0.7.0-beta.1"
scene_prompt_store = ScenePromptStore()
PEARL_API_VERSION = "v1"

# ============================================================
# FUNCIONES CORE (reutilizables CLI y HTTP)
# ============================================================

def product_identity() -> Dict:
    return {
        "name": PEARL_PRODUCT,
        "edition": PEARL_EDITION,
        "version": PEARL_VERSION,
        "api_version": PEARL_API_VERSION,
    }


def brain_timeout(brain: Dict):
    return (brain.get("connect_timeout", 5), brain.get("read_timeout", 150))

def build_prompt(brain_name: str, prompt: str) -> str:
    system_prompt = SYSTEM_PROMPTS.get(brain_name, SYSTEM_PROMPTS["cotidiano"])
    return build_assistant_prompt(prompt, system_prompt.replace(identity_instructions(), "", 1))

def ollama_payload(brain_name: str, prompt: str, stream: bool) -> Dict:
    brain = BRAINS[brain_name]
    return {
        "model": brain["model"],
        "prompt": build_prompt(brain_name, prompt),
        "stream": stream,
        "options": OLLAMA_OPTIONS.get(brain_name, OLLAMA_OPTIONS["cotidiano"])
    }

def ndjson_event(event: Dict) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


def json_object_or_error():
    data = request.get_json(silent=True)
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, (jsonify({"status": "error", "error": "invalid_json_object"}), 400)
    return data, None
def enqueue_candidate_prompts(candidates):
    return [scene_prompt_store.enqueue_candidate(scene) for scene in candidates]

def iter_json_objects(payload: str):
    decoder = json.JSONDecoder()
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")
    text = payload.strip()
    index = 0

    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        obj, next_index = decoder.raw_decode(text, index)
        yield obj
        index = next_index

def query_brain(brain_name: str, prompt: str) -> Optional[Dict]:
    """
    Envía una consulta a un cerebro específico
    """
    brain = BRAINS.get(brain_name)
    if not brain:
        return {"error": f"Cerebro {brain_name} no encontrado", "status": "error"}
    
    print(f"   📡 Conectando a {brain_name} ({brain['model']})...")
    print(f"   ⏱️  Timeout conexión/lectura: {brain_timeout(brain)} segundos")
    print(f"   📝 Prompt: {prompt[:60]}...")
    
    # Siempre en streaming: el read_timeout cuenta entre fragmentos y no para
    # la respuesta entera, así una respuesta larga no se pierde por tiempo y,
    # si se corta a la mitad, se devuelve lo que alcanzó a llegar.
    start_time = time.time()
    parts = []
    try:
        print(f"   🔄 Enviando request a {brain['url']}...")
        with requests.post(
            brain["url"],
            json=ollama_payload(brain_name, prompt, stream=True),
            timeout=brain_timeout(brain),
            stream=True,
        ) as response:
            if response.status_code != 200:
                print(f"   ❌ HTTP Error: {response.status_code}")
                return {
                    "brain": brain_name,
                    "error": f"HTTP {response.status_code}: {response.text[:100]}",
                    "status": "error"
                }
            for payload in response.iter_lines(decode_unicode=True):
                if not payload:
                    continue
                for chunk in iter_json_objects(payload):
                    parts.append(chunk.get("response", ""))
                    if chunk.get("done"):
                        break

        elapsed_time = time.time() - start_time
        print(f"   ✅ Respuesta recibida en {elapsed_time:.2f}s")
        return {
            "brain": brain_name,
            "model": brain["model"],
            "response": "".join(parts),
            "time": round(elapsed_time, 2),
            "status": "success"
        }

    except requests.exceptions.Timeout:
        if parts:
            print(f"   ⚠️  Respuesta cortada tras {brain.get('read_timeout', 150)}s sin datos; "
                  "se devuelve lo recibido")
            return {
                "brain": brain_name,
                "model": brain["model"],
                "response": "".join(parts),
                "time": round(time.time() - start_time, 2),
                "status": "success",
                "truncated": True
            }
        print(f"   ❌ TIMEOUT sin datos después de {brain.get('read_timeout', 150)} segundos")
        return {
            "brain": brain_name,
            "error": f"Timeout de lectura ({brain.get('read_timeout', 150)}s sin datos)",
            "status": "error"
        }
    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ Connection Error: {e}")
        return {
            "brain": brain_name,
            "error": "Error de conexión (¿el cerebro está corriendo?)",
            "status": "error"
        }
    except Exception as e:
        print(f"   ❌ Error: {type(e).__name__}: {e}")
        return {
            "brain": brain_name,
            "error": str(e),
            "status": "error"
        }

def stream_brain_events(brain_name: str, prompt: str):
    """
    Genera eventos NDJSON progresivos desde Ollama.
    Cada linea es JSON: meta, token, done o error.
    """
    brain = BRAINS.get(brain_name)
    if not brain:
        yield ndjson_event({"event": "error", "status": "error", "error": f"Cerebro {brain_name} no encontrado"})
        return

    start_time = time.time()
    yield ndjson_event({
        "event": "meta",
        "status": "streaming",
        "brain": brain_name,
        "model": brain["model"]
    })

    try:
        with requests.post(
            brain["url"],
            json=ollama_payload(brain_name, prompt, stream=True),
            timeout=brain_timeout(brain),
            stream=True
        ) as response:
            if response.status_code != 200:
                yield ndjson_event({
                    "event": "error",
                    "status": "error",
                    "brain": brain_name,
                    "error": f"HTTP {response.status_code}: {response.text[:200]}"
                })
                return

            full_response = []
            for payload in response.iter_lines(decode_unicode=True):
                if not payload:
                    continue
                for chunk in iter_json_objects(payload):
                    token = chunk.get("response", "")
                    if token:
                        full_response.append(token)
                        yield ndjson_event({
                            "event": "token",
                            "status": "streaming",
                            "brain": brain_name,
                            "response": token
                        })
                    if chunk.get("done"):
                        yield ndjson_event({
                            "event": "done",
                            "status": "success",
                            "brain": brain_name,
                            "model": brain["model"],
                            "response": "".join(full_response),
                            "time": round(time.time() - start_time, 2)
                        })
                        return
    except requests.exceptions.Timeout:
        yield ndjson_event({
            "event": "error",
            "status": "error",
            "brain": brain_name,
            "error": f"Timeout de lectura ({brain.get('read_timeout', 150)}s sin datos)"
        })
    except requests.exceptions.ConnectionError:
        yield ndjson_event({
            "event": "error",
            "status": "error",
            "brain": brain_name,
            "error": "Error de conexión (¿Ollama está corriendo?)"
        })
    except Exception as e:
        yield ndjson_event({
            "event": "error",
            "status": "error",
            "brain": brain_name,
            "error": str(e)
        })

def route_intent(prompt: str) -> str:
    """
    Decide qué cerebro usar según la consulta
    """
    prompt_lower = prompt.lower()
    
    # Palabras clave para cerebro rápido (consultas simples)
    rapido_keywords = [
        "hola", "buenas", "saludos", "gracias", "chao", "adiós", "bye",
        "qué hora", "clima", "tiempo", "cómo estás", "qué tal"
    ]
    for kw in rapido_keywords:
        if kw in prompt_lower:
            return "cotidiano"
    
    # Palabras clave para cerebro crítico (tareas importantes)
    critical_keywords = [
        "alarma", "seguridad", "emergencia", "apagar", "reiniciar",
        "analiza", "analizar", "riesgo", "peligro", "critico",
        "evalúa", "evaluar", "investiga", "investigar", "optimiza",
        "estrategia", "plan", "proyecto", "sistema"
    ]
    for kw in critical_keywords:
        if kw in prompt_lower:
            return "critico"
    
    # Por defecto: cerebro cotidiano
    return "cotidiano"

def check_brains_status():
    """
    Verifica qué cerebros están disponibles
    """
    print("\n🔍 Verificando estado de los cerebros...")
    print("-" * 40)
    
    for name, brain in BRAINS.items():
        try:
            response = requests.get(
                brain["url"].replace("/api/generate", "/api/tags"),
                timeout=5
            )
            if response.status_code == 200:
                print(f"   ✅ {name}: ONLINE ({brain['model']})")
            else:
                print(f"   ⚠️  {name}: RESPONDE PERO CON ERROR")
        except:
            print(f"   ❌ {name}: OFFLINE ({brain['model']})")
    
    print("-" * 40)

def get_brains_health():
    """
    Versión programática de check_brains_status para API
    """
    status = {}
    for name, brain in BRAINS.items():
        try:
            response = requests.get(
                brain["url"].replace("/api/generate", "/api/tags"),
                timeout=3
            )
            status[name] = {
                "status": "online" if response.status_code == 200 else "error",
                "model": brain["model"],
                "url": brain["url"]
            }
        except:
            status[name] = {
                "status": "offline",
                "model": brain["model"],
                "url": brain["url"]
            }
    return status

# ============================================================
# MODO CLI (Interactivo)
# ============================================================

def main_cli():
    """
    Bucle principal interactivo (modo terminal)
    """
    print("=" * 60)
    print("🤖 ASISTENTE LOCAL DISTRIBUIDO")
    print("=" * 60)
    print("\n📡 Cerebros configurados:")
    for name, brain in BRAINS.items():
        print(f"   • {name.upper()}: {brain['description']}")
        print(f"     → {brain['model']} @ {brain['url']}")
    
    # Verificar estado
    check_brains_status()
    
    print("\n💬 Escribe tus consultas (escribe 'salir' para terminar)")
    print("-" * 60)
    
    while True:
        try:
            prompt = input("\n🧠 Tú: ").strip()
            
            if prompt.lower() in ['salir', 'exit', 'quit', 'q']:
                print("\n👋 ¡Hasta luego!")
                break
            
            if not prompt:
                continue
            
            # Elegir cerebro según intención
            brain = route_intent(prompt)
            print(f"\n🎯 Intención detectada → usando cerebro: {brain.upper()}")
            
            # Consultar cerebro
            result = query_brain(brain, prompt)
            
            if result["status"] == "success":
                print(f"\n🤖 Asistente: {result['response']}")
                print(f"⏱️  Tiempo de respuesta: {result['time']} segundos")
            else:
                print(f"\n❌ Error: {result.get('error', 'Desconocido')}")
                print("   Sugerencia: Verifica que el cerebro esté corriendo")
                
        except KeyboardInterrupt:
            print("\n\n👋 ¡Hasta luego!")
            break
        except Exception as e:
            print(f"\n❌ Error inesperado: {e}")

# ============================================================
# MODO HTTP API (Flask)
# ============================================================

app = Flask(__name__)


@app.before_request
def require_core_gateway():
    """Todas las rutas HTTP exigen el token compartido con PEARL Core."""
    return core_gateway_required()

@app.route('/process', methods=['POST'])
@app.route('/api/v1/process', methods=['POST'])
def api_process():
    """
    Endpoint principal para procesar consultas desde nodos externos (G05, etc.)
    """
    try:
        data, error = json_object_or_error()
        if error is not None:
            return error
        if not data or 'prompt' not in data:
            return jsonify({
                "status": "error",
                "error": "Se requiere campo 'prompt' en JSON"
            }), 400
        
        prompt = data['prompt']
        stream = data.get('stream', False)
        
        # Reusar lógica de enrutamiento existente
        brain = route_intent(prompt)
        
        if stream:
            return Response(
                stream_with_context(stream_brain_events(brain, prompt)),
                mimetype="application/x-ndjson",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no"
                }
            )

        # Consultar cerebro sin streaming para mantener compatibilidad
        result = query_brain(brain, prompt)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": f"Error interno: {str(e)}"
        }), 500

@app.route('/health', methods=['GET'])
@app.route('/api/v1/health', methods=['GET'])
def api_health():
    """
    Endpoint de salud para monitoreo
    """
    return jsonify({
        "orquestador": "central",
        "version": "2.0.0-dual",
        "product": product_identity(),
        "modo": "http",
        "cerebros": get_brains_health(),
        "timestamp": time.time()
    })

@app.route('/intents', methods=['GET'])
@app.route('/api/v1/intents', methods=['GET'])
def api_intents():
    """
    Devuelve las palabras clave de enrutamiento para sincronización con otros nodos
    """
    return jsonify({
        "rapido": {
            "keywords": ["hola", "buenas", "saludos", "gracias", "chao", "adiós", "bye",
                        "qué hora", "clima", "tiempo", "cómo estás", "qué tal"],
            "description": "Respuestas rápidas, consultas simples"
        },
        "critico": {
            "keywords": ["alarma", "seguridad", "emergencia", "apagar", "reiniciar",
                        "analiza", "analizar", "riesgo", "peligro", "critico",
                        "evalúa", "evaluar", "investiga", "investigar", "optimiza",
                        "estrategia", "plan", "proyecto", "sistema"],
            "description": "Análisis profundo, tareas críticas"
        },
        "cotidiano": {
            "keywords": ["default"],
            "description": "Tareas cotidianas, conversación general (fallback)"
        }
    })

@app.route('/status', methods=['GET'])
@app.route('/api/v1/status', methods=['GET'])
def api_status():
    """
    Estado simple para health checks rápidos
    """
    return jsonify({
        "status": "online",
        "orquestador": "central",
        "product": product_identity(),
        "timestamp": time.time()
    })

@app.route('/memory/event', methods=['POST'])
@app.route('/api/v1/memory/event', methods=['POST'])
def api_memory_event():
    """
    Registra un evento estructurado para aprendizaje de escenas.
    No ejecuta acciones fisicas.
    """
    try:
        data, error = json_object_or_error()
        if error is not None:
            return error
        result = record_event(data)
        prompts = enqueue_candidate_prompts(result["candidates_created"])
        return jsonify({
            "status": "ok",
            "event": result["event"],
            "candidates_created": result["candidates_created"],
            "prompts_created": prompts,
        })
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "error": f"Error interno: {str(e)}"}), 500

@app.route('/memory/events', methods=['GET'])
@app.route('/api/v1/memory/events', methods=['GET'])
def api_memory_events():
    """
    Devuelve eventos recientes registrados por la memoria.
    """
    try:
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 500))
        return jsonify({
            "status": "ok",
            "events": list_events(limit)
        })
    except Exception as e:
        return jsonify({"status": "error", "error": f"Error interno: {str(e)}"}), 500

@app.route('/scenes/detect', methods=['POST'])
@app.route('/api/v1/scenes/detect', methods=['POST'])
def api_scenes_detect():
    """
    Fuerza una pasada de deteccion de patrones y crea candidatas si aplica.
    """
    try:
        candidates = detect_candidates()
        prompts = enqueue_candidate_prompts(candidates)
        return jsonify({
            "status": "ok",
            "candidates_created": candidates,
            "prompts_created": prompts,
        })
    except Exception as e:
        return jsonify({"status": "error", "error": f"Error interno: {str(e)}"}), 500

@app.route('/scenes', methods=['GET'])
@app.route('/api/v1/scenes', methods=['GET'])
def api_scenes():
    """
    Lista escenas aprendidas. Filtro opcional: ?status=candidate|approved|rejected|archived
    """
    try:
        status_filter = request.args.get("status")
        return jsonify({
            "status": "ok",
            "scenes": list_scenes(status_filter)
        })
    except Exception as e:
        return jsonify({"status": "error", "error": f"Error interno: {str(e)}"}), 500

@app.route('/scenes/candidates', methods=['GET'])
@app.route('/api/v1/scenes/candidates', methods=['GET'])
def api_scene_candidates():
    """
    Lista solo escenas candidatas pendientes de aprobacion humana.
    """
    return jsonify({
        "status": "ok",
        "scenes": list_scenes("candidate")
    })

@app.route('/scenes/<scene_id>/approve', methods=['POST'])
@app.route('/api/v1/scenes/<scene_id>/approve', methods=['POST'])
def api_scene_approve(scene_id):
    """
    Aprueba una escena candidata. No la ejecuta.
    """
    try:
        scene = update_scene_status(scene_id, "approved")
        if not scene:
            return jsonify({"status": "error", "error": "Escena no encontrada"}), 404
        return jsonify({"status": "ok", "scene": scene})
    except Exception as e:
        return jsonify({"status": "error", "error": f"Error interno: {str(e)}"}), 500

@app.route('/scenes/<scene_id>/reject', methods=['POST'])
@app.route('/api/v1/scenes/<scene_id>/reject', methods=['POST'])
def api_scene_reject(scene_id):
    """
    Rechaza una escena candidata.
    """
    try:
        scene = update_scene_status(scene_id, "rejected")
        if not scene:
            return jsonify({"status": "error", "error": "Escena no encontrada"}), 404
        return jsonify({"status": "ok", "scene": scene})
    except Exception as e:
        return jsonify({"status": "error", "error": f"Error interno: {str(e)}"}), 500

@app.route('/scenes/suggest', methods=['POST'])
@app.route('/api/v1/scenes/suggest', methods=['POST'])
def api_scene_suggest():
    """
    Sugiere una escena segun contexto. Siempre requiere confirmacion humana.
    """
    try:
        context, error = json_object_or_error()
        if error is not None:
            return error
        suggestion = suggest_scene(context)
        prompt = None
        if not suggestion:
            return jsonify({
                "status": "ok",
                "suggestion": None,
                "requires_confirmation": True
            })
        scene = suggestion.get("scene") or {}
        if scene.get("status") == "candidate":
            prompt = scene_prompt_store.enqueue_candidate(scene)
        elif scene.get("status") == "approved":
            prompt = scene_prompt_store.enqueue_activation(scene, suggestion.get("suggestion") or "Escena sugerida")
        return jsonify({
            "status": "ok",
            **suggestion,
            "prompt": prompt,
        })
    except Exception as e:
        return jsonify({"status": "error", "error": f"Error interno: {str(e)}"}), 500


@app.route('/scene-prompts/pending', methods=['GET'])
@app.route('/api/v1/scene-prompts/pending', methods=['GET'])
def api_scene_prompts_pending():
    """Lista propuestas pendientes para PEARL Client."""
    try:
        kind = request.args.get("kind")
        return jsonify({
            "status": "ok",
            "prompts": scene_prompt_store.list_pending(kind=kind),
        })
    except Exception as e:
        return jsonify({"status": "error", "error": f"Error interno: {str(e)}"}), 500


@app.route('/scene-prompts/<prompt_id>/decision', methods=['POST'])
@app.route('/api/v1/scene-prompts/<prompt_id>/decision', methods=['POST'])
def api_scene_prompt_decision(prompt_id):
    """Registra una decision idempotente. Nunca ejecuta acciones fisicas."""
    try:
        data, error = json_object_or_error()
        if error is not None:
            return error
        prompt, changed = scene_prompt_store.decide(
            prompt_id=prompt_id,
            decision=data.get("decision"),
            idempotency_key=data.get("idempotency_key"),
        )
        if not prompt:
            return jsonify({"status": "error", "error": "Propuesta no encontrada"}), 404

        scene = None
        if changed and prompt.get("kind") == "candidate_approval":
            scene_status = "approved" if prompt.get("decision") == "accept" else "rejected"
            scene = update_scene_status(prompt.get("scene_id"), scene_status)

        return jsonify({
            "status": "ok",
            "prompt": prompt,
            "scene": scene,
            "decision_applied": changed,
            "executed": False,
        })
    except ValueError as e:
        return jsonify({"status": "error", "error": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "error": f"Error interno: {str(e)}"}), 500


def run_http_server():
    """
    Inicia el servidor Flask
    """
    if not CORE_GATEWAY_TOKEN:
        raise SystemExit("Falta PEARL_CORE_GATEWAY_TOKEN: el Hub no abre HTTP sin token.")
    print(f"\n🌐 Iniciando {PEARL_PRODUCT} {PEARL_VERSION} en {HTTP_HOST}:{HTTP_PORT}")
    print(f"   Endpoints disponibles:")
    print(f"   • POST /process  - Procesar consulta")
    print(f"   • GET  /health   - Estado de cerebros")
    print(f"   • GET  /intents  - Palabras clave de enrutamiento")
    print(f"   • GET  /status   - Health check simple")
    print(f"   • POST /memory/event - Registrar evento de escena")
    print(f"   • GET  /scenes   - Listar escenas aprendidas")
    print(f"   • POST /scenes/suggest - Sugerir escena")
    print(f"\n   Presiona Ctrl+C para detener\n")
    
    from waitress import serve

    # Waitress: servidor de producción, un proceso con varios hilos.
    serve(app, host=HTTP_HOST, port=HTTP_PORT, threads=8)

# ============================================================
# ENTRY POINT - SELECCIÓN DE MODO
# ============================================================

if __name__ == "__main__":
    # Detectar modo según argumentos
    if len(sys.argv) > 1:
        modo = sys.argv[1]
        
        if modo == '--http':
            # Solo modo servidor HTTP
            run_http_server()
            
        elif modo == '--dual':
            # Ambos modos: HTTP en thread + CLI interactivo
            print("🔄 Modo DUAL: HTTP API + CLI interactivo")
            server_thread = threading.Thread(target=run_http_server, daemon=True)
            server_thread.start()
            time.sleep(1)  # Dar tiempo a que inicie el servidor
            main_cli()
            
        elif modo == '--cli' or modo == '-h' or modo == '--help':
            # Modo CLI explícito o ayuda
            main_cli()
            
        else:
            print(f"Modo desconocido: {modo}")
            print("Uso: python orchestrator.py [--http|--dual|--cli]")
            print("  --http   : Solo servidor HTTP (producción)")
            print("  --dual   : HTTP + CLI simultáneo (debug)")
            print("  --cli    : Solo CLI interactivo (default)")
            sys.exit(1)
    else:
        # Default: modo CLI (compatible con versión anterior)
        main_cli()
