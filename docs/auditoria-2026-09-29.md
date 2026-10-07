# Auditoría de PEARL Hub (`asistente_local`), solo lectura

Fecha: **29 de septiembre de 2026**. Revisión estática del código, la configuración y
el despliegue, más la ejecución de la suite de pruebas. No se modificó implementación,
configuración, servicios ni datos, y no se hicieron pruebas activas contra el servicio.

Referencia: commit `79cd493 Unify PEARL assistant identity prompts`, worktree limpio.
~2.000 líneas Python; el núcleo es `orchestrator.py` (803 líneas, Flask).

**Pruebas:** 12 pasan con `unittest`, 0 fallos.

## Dictamen

El Hub no tiene autenticación y está **publicado completo en internet**
(`hub.pearlhome.com.br → localhost:5006`, además de `0.0.0.0:5006` en la LAN).
La única protección prevista, el token de gateway del Core, **no está activa**:
el proceso en ejecución no es la unidad `pearl-hub.service` preparada, sino una unidad
de sistema antigua que no carga su configuración.

No ejecuta acciones físicas (las decisiones devuelven `executed: false`), así que el
impacto es abuso de recursos, fuga de hábitos domésticos y envenenamiento de escenas,
no control directo de dispositivos.

## Despliegue real

| Elemento | Estado |
|---|---|
| Proceso en `:5006` | `/usr/bin/python3 orchestrator.py --http`, lanzado por **`/etc/systemd/system/jarvis-orchestrator.service`** (unidad de sistema antigua, fuera del repo) |
| `pearl-hub.service` (usuario, con `venv` y `hub.env`) | **inactive / disabled** |
| `~/.config/pearl-home/hub.env` | Existe (permisos 600) y define `PEARL_CORE_GATEWAY_TOKEN`, pero ningún servicio activo lo carga |
| `PEARL_CORE_GATEWAY_TOKEN` en el proceso activo | **Ausente** → `core_gateway_required()` deja pasar todo |
| `PEARL_CORE_GATEWAY_TOKEN` en `jarvis_core/.env` | Ausente → el Core tampoco lo envía |
| Directorio de memoria | Por defecto `~/.local/share/pearl-home/scene-memory` (ahora vacío) |

## Hallazgos

| # | Sev. | Hallazgo | Dónde |
|---|---|---|---|
| **H1** | **Alta** | **API sin autenticación publicada en internet.** Cualquiera puede usar `/process` (Ollama local), leer `/memory/events` y `/scenes` (patrones de uso del hogar: horarios, luces, música), inyectar eventos con `/memory/event` y forzar `/scenes/detect`. | `orchestrator.py:455-697`, `~/.cloudflared/config.yml` |
| **H2** | **Alta** | **La protección de decisiones está desactivada.** Aprobar o rechazar escenas y decidir propuestas depende de `PEARL_CORE_GATEWAY_TOKEN`; si está vacío, `core_gateway_required()` devuelve `None`. El token no está ni en el Hub activo ni en el Core, así que cualquiera puede aprobar escenas envenenadas que luego se ofrecen al usuario. | `orchestrator.py:36-45,634-748` |
| **H3** | **Alta** | **Servicio desplegado equivocado.** Corre la unidad antigua `jarvis-orchestrator.service` con el Python del sistema, sin `EnvironmentFile`, sin `venv` y sin endurecimiento. La unidad prevista `pearl-hub.service` está deshabilitada. | `/etc/systemd/system/jarvis-orchestrator.service`, `deploy/systemd/pearl-hub.service.in` |
| H4 | Media | **Denegación de servicio.** `/process` no tiene límite de tamaño ni de concurrencia (`threaded=True`) y cada petición puede ocupar Ollama hasta 240 s. `events.json` crece sin límite y se reescribe entero en cada evento (disco y CPU O(n²)). | `orchestrator.py:455-496,767`, `scene_memory.py` (`record_event`) |
| H5 | Media | Las respuestas de error devuelven el texto de la excepción y fragmentos de respuestas de Ollama; `/health` expone las URLs internas de los modelos. | `orchestrator.py:215,236,495,573...`, `386-392` |
| H6 | Baja | Servidor de desarrollo de Flask en `0.0.0.0`. | `orchestrator.py:767` |
| H7 | Baja | `route_intent` manda las palabras "rápidas" al cerebro `cotidiano`, así que `rapido` nunca se usa; `/intents` anuncia lo contrario. | `orchestrator.py:332-334,519-536` |
| H8 | Baja | Scripts de voz heredados: `orchestrator_voz_fixed.py` ejecuta `sudo apt install sox -y` y usa `shell=True` (con ruta temporal propia, no explotable por entrada externa). Hay tres variantes casi duplicadas. | `orchestrator_voz_fixed.py:36,111-113` |
| H9 | Info | `memory/` del repo son archivos heredados vacíos y está en `.gitignore`; `modelo_stt/` (modelo Vosk) sí está versionado y pesa en el repo. | `.gitignore`, `modelo_stt/` |

## Puntos fuertes

- Nunca ejecuta acciones físicas: las decisiones sólo cambian estado y lo declaran.
- Escritura atómica de JSON (`os.replace`) con lock; propuestas limitadas a 1.000 y
  decisiones idempotentes.
- Comparación del token de gateway con `hmac.compare_digest`.
- La memoria se movió fuera del repo, con migración desde la ruta antigua.

## Plan de corrección (por orden)

1. **Quitar el Hub del túnel** (`hub.pearlhome.com.br`) si ningún cliente externo lo
   necesita; el Core ya hace de gateway. Si se necesita, protegerlo con Cloudflare Access.
2. **Cambiar el servicio:** deshabilitar `jarvis-orchestrator.service` y activar
   `pearl-hub.service` (con `venv` y `hub.env`), escuchando en `127.0.0.1`.
3. **Activar el gateway en ambos lados:** mismo `PEARL_CORE_GATEWAY_TOKEN` en `hub.env`
   y en `jarvis_core/.env`, y hacer que el Hub **falle cerrado** si el token está vacío.
4. Exigir autenticación también en `/process`, `/memory/*` y `/scenes*`, no sólo en
   las decisiones.
5. Limitar tamaño de prompt, concurrencia hacia Ollama y número de eventos guardados.
6. Devolver errores genéricos y quitar las URLs internas de `/health`.

## Relación con otras auditorías

- `jarvis_core/docs/auditoria-2026-09-29.md`: el Core usa este Hub como backend de
  escenas y comparte el token de gateway.
- `A_proyecto_nuevo/Jinnex_Next/docs/auditoria-2026-09-29.md`.
