# PEARL Hub (jarvis-local)

Orquestador local de PEARL HOME en la laptop (`jarvis-node`). Atiende al Core
(`jarvis_core`, :5004) en el puerto **5006** con dos funciones:

- **Respaldo de IA local**: responde consultas con modelos de Ollama cuando la
  conversación no la atiende Nova (Jinnex Next).
- **Memoria de escenas**: registra eventos de música y luces, detecta rutinas
  repetidas y propone escenas que siempre requieren confirmación humana.

Versión: `0.7.0-beta.1`.

```text
PEARL Core :5004 ──X-PEARL-Core-Gateway──▶ PEARL Hub :5006
                                             ├─▶ Ollama :11434 (qwen2.5:0.5b, llama3.2:3b)
                                             └─▶ ~/.local/share/pearl-home/scene-memory/
```

Regla del sistema: **la IA propone, la persona confirma, el Core valida, el nodo
ejecuta**. El Hub nunca ejecuta música, luces ni hardware: solo responde texto,
guarda eventos y encola propuestas.

## Cerebros locales

| Cerebro | Modelo | Timeout de lectura | Uso |
| --- | --- | --- | --- |
| `rapido` | `qwen2.5:0.5b` | 90 s | Respuestas breves |
| `cotidiano` | `qwen2.5:0.5b` | 150 s | Conversación general (por defecto) |
| `critico` | `llama3.2:3b` | 240 s | Seguridad, sistema, planes, análisis |

`route_intent()` elige el cerebro con palabras clave: términos como `alarma`,
`seguridad`, `analiza`, `plan` o `sistema` van a `critico`; el resto, incluidos
los saludos, va a `cotidiano`. En la práctica `rapido` no lo elige el enrutador,
aunque sigue definido y aparece en `/health`.

Las consultas a Ollama van **siempre en streaming**: el timeout de lectura corre
entre fragmentos y no sobre la respuesta completa. Si se corta a la mitad, se
devuelve lo recibido con `"truncated": true`.

Todos los prompts llevan las instrucciones de identidad de
`assistant_identity.py`: el asistente se llama **JARVIS** (`PEARL_ASSISTANT_NAME`),
es el asistente local de **PEARL HOME** (`PEARL_SYSTEM_NAME`), no se presenta como
Qwen y responde en español.

En esta laptop los modelos son lentos (llama3.2:3b da alrededor de 1 token por
segundo), por eso son el respaldo y no la vía principal.

## Memoria de escenas

1. El Core manda eventos a `POST /api/v1/memory/event` con `intent`, `music`
   (`genre`/`query`) y `lights` (`color`/`scene`/`brightness`).
2. Cada evento se agrupa por firma: intención, música, color, brillo
   (`low` ≤ 25, `medium` ≤ 60, `high`) y franja horaria (`morning`, `afternoon`,
   `evening`, `night`).
3. Si una firma se repite **6 veces en 6 días distintos**, se crea una escena
   `candidate` y se encola una propuesta `candidate_approval` (vence en 7 días).
4. La persona acepta o cancela desde PEARL Client. Aceptar aprueba la escena,
   pero **no la ejecuta**.
5. `POST /api/v1/scenes/suggest` elige la escena más probable para el contexto;
   si está aprobada, encola una `activation_suggestion` (vence en 30 minutos).

Toda escena lleva `requires_confirmation: true` y `auto_execute: false`. Las
decisiones son idempotentes y exigen `idempotency_key`.

Los datos viven fuera de Git, con permisos `600`:

```text
~/.local/share/pearl-home/scene-memory/
├── events.json
├── learned_scenes.json
└── scene_prompts.json
```

La ruta se cambia con `JARVIS_LOCAL_SCENE_MEMORY_DIR`. Si existe la carpeta
antigua `memory/` dentro del repo, sus archivos se copian la primera vez.

## API

Todas las rutas exigen la cabecera `X-PEARL-Core-Gateway` con el mismo
`PEARL_CORE_GATEWAY_TOKEN` del Core; si no coincide responden `403
core_gateway_required`. Sin ese token configurado el servidor HTTP no arranca.

Cada ruta existe en versión `/api/v1/...` y en la ruta antigua sin prefijo,
que se mantiene durante la Beta.

| Método | Ruta | Qué hace |
| --- | --- | --- |
| `POST` | `/api/v1/process` | Responde `{"prompt": "...", "stream": false}`; con `stream: true` devuelve NDJSON (`meta`, `token`, `done`, `error`) |
| `GET` | `/api/v1/health` | Identidad del producto y estado de cada cerebro en Ollama |
| `GET` | `/api/v1/status` | Health check simple |
| `GET` | `/api/v1/intents` | Palabras clave de enrutamiento |
| `POST` | `/api/v1/memory/event` | Registra un evento y crea candidatas si corresponde |
| `GET` | `/api/v1/memory/events?limit=50` | Eventos recientes (máximo 500) |
| `POST` | `/api/v1/scenes/detect` | Fuerza la detección de patrones |
| `GET` | `/api/v1/scenes?status=` | Escenas (`candidate`, `approved`, `rejected`, `archived`) |
| `GET` | `/api/v1/scenes/candidates` | Solo candidatas |
| `POST` | `/api/v1/scenes/<id>/approve` | Aprueba una escena (no la ejecuta) |
| `POST` | `/api/v1/scenes/<id>/reject` | Rechaza una escena |
| `POST` | `/api/v1/scenes/suggest` | Sugiere una escena para el contexto |
| `GET` | `/api/v1/scene-prompts/pending?kind=` | Propuestas pendientes para PEARL Client |
| `POST` | `/api/v1/scene-prompts/<id>/decision` | `{"decision": "accept"\|"cancel", "idempotency_key": "..."}` |

Ejemplo:

```bash
curl -s http://127.0.0.1:5006/api/v1/status \
  -H "X-PEARL-Core-Gateway: $PEARL_CORE_GATEWAY_TOKEN"
```

## Instalación

```bash
cd ~/asistente_local
python3 -m venv venv
venv/bin/pip install -r requirements.txt
./scripts/install_hub_service.sh
```

El instalador genera `~/.config/systemd/user/pearl-hub.service` desde
`deploy/systemd/pearl-hub.service.in`, crea `~/.config/pearl-home/hub.env` y la
carpeta de memoria, y habilita la unidad de **usuario** `pearl-hub`. Después hay
que poner el token en `hub.env`:

```bash
PEARL_CORE_GATEWAY_TOKEN=<el mismo valor que en jarvis_core/.env>
```

Para que arranque sin sesión gráfica: `loginctl enable-linger "$USER"`.

Requiere Ollama en `127.0.0.1:11434` con los modelos:

```bash
ollama pull qwen2.5:0.5b
ollama pull llama3.2:3b
```

### Operación

```bash
systemctl --user status pearl-hub
journalctl --user -u pearl-hub -n 100 --no-pager
```

El servidor corre con waitress (8 hilos). En el despliegue actual hay un
override de aislamiento en `~/.config/systemd/user/pearl-hub.service.d/`
(auditoría 2026-10-07): `ProtectSystem=strict`, `ProtectHome=read-only`,
escritura solo en la memoria de escenas, `PrivateTmp=true` y `MemoryMax=768M`.

Antes de tocar el servicio, confirmar qué proceso ocupa el 5006
(`/proc/<pid>/cgroup`): hasta el 2026-10-06 lo corría una unidad de sistema
`jarvis-orchestrator`, ya retirada.

### Modos de ejecución

```bash
venv/bin/python orchestrator.py --http   # solo servidor (producción)
venv/bin/python orchestrator.py --dual   # servidor + CLI interactivo (depuración)
venv/bin/python orchestrator.py          # solo CLI interactivo
```

## Configuración

Ver `.env.example`. Las variables se leen del entorno; la unidad las toma de
`~/.config/pearl-home/hub.env`.

| Variable | Por defecto | Uso |
| --- | --- | --- |
| `PEARL_CORE_GATEWAY_TOKEN` | — (obligatoria para HTTP) | Token compartido con el Core |
| `PEARL_HUB_HOST` | `0.0.0.0` | Interfaz de escucha |
| `PEARL_HUB_PORT` | `5006` | Puerto |
| `PEARL_PRODUCT` / `PEARL_EDITION` / `PEARL_VERSION` | `PEARL Hub` / `hub` / `0.7.0-beta.1` | Identidad del producto |
| `JARVIS_LOCAL_SCENE_MEMORY_DIR` | `~/.local/share/pearl-home/scene-memory` | Carpeta de la memoria |
| `PEARL_ASSISTANT_NAME` / `PEARL_SYSTEM_NAME` | `JARVIS` / `PEARL HOME` | Identidad conversacional |

## Pruebas

```bash
venv/bin/python -m unittest discover -s tests
```

Cubren el contrato de la API, la identidad, el streaming de `query_brain`, el
almacenamiento de la memoria y las propuestas.

## Archivos

| Archivo | Contenido |
| --- | --- |
| `orchestrator.py` | Servidor HTTP, CLI y enrutamiento de cerebros |
| `scene_memory.py` | Eventos, detección de patrones y escenas |
| `scene_prompts.py` | Cola de propuestas y decisiones idempotentes |
| `assistant_identity.py` | Instrucciones de identidad de JARVIS |
| `docs/hub-operations.md` | Operación del servicio |
| `docs/auditoria-2026-09-29.md` | Auditoría del Hub |
| `freeze-antes-de-actualizar.txt` | Paquetes antes de la actualización de 2026-09-29 |
| `orchestrator_voz_*.py`, `modelo_stt/` | Prototipos antiguos de voz (Vosk + eSpeak + `phi3-fast`); no los usa el servicio y el modelo `phi3-fast` ya no está instalado |

`modelo_stt/` es el modelo pequeño de español de Vosk (© AC Technologies LLC),
con su propia licencia en `modelo_stt/README`.
