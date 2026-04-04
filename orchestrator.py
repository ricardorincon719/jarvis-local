#!/usr/bin/env python3
"""
Orquestador Central - Asistente Local Distribuido
Cerebros:
- Rápido: Moto G05 (qwen2.5:0.5b) - IP: 192.168.100.100
- Cotidiano: Laptop local (gemma2:2b)
- Crítico: Laptop local (phi3:mini)
"""

import requests
import json
import time
from typing import Dict, Optional

# Configuración de cerebros
BRAINS = {
    "rapido": {
        "url": "http://192.168.100.100:11434/api/generate",
        "model": "qwen2.5:0.5b",
        "timeout": 20,
        "description": "Respuestas rápidas, consultas simples"
    },
    "cotidiano": {
        "url": "http://localhost:11434/api/generate",
        "model": "phi3-fast",
        "timeout": 45,
        "description": "Tareas cotidianas, conversación general"
    },
    "critico": {
        "url": "http://localhost:11434/api/generate",
        "model": "phi3-fast",
        "timeout": 30,
        "description": "Análisis profundo, tareas críticas"
    }
}

def query_brain(brain_name: str, prompt: str, stream: bool = False) -> Optional[Dict]:
    """
    Envía una consulta a un cerebro específico
    """
    brain = BRAINS.get(brain_name)
    if not brain:
        return {"error": f"Cerebro {brain_name} no encontrado", "status": "error"}
    
    print(f"   📡 Conectando a {brain_name} ({brain['model']})...")
    print(f"   ⏱️  Timeout: {brain['timeout']} segundos")
    print(f"   📝 Prompt: {prompt[:60]}...")
    
    try:
        start_time = time.time()
        
        print(f"   🔄 Enviando request a {brain['url']}...")
        response = requests.post(
            brain["url"],
            json={
                "model": brain["model"],
                "prompt": prompt,
                "stream": stream
            },
            timeout=brain["timeout"]
        )
        
        elapsed_time = time.time() - start_time
        print(f"   ✅ Respuesta recibida en {elapsed_time:.2f}s")
        
        if response.status_code == 200:
            result = response.json()
            return {
                "brain": brain_name,
                "model": brain["model"],
                "response": result.get("response", ""),
                "time": round(elapsed_time, 2),
                "status": "success"
            }
        else:
            print(f"   ❌ HTTP Error: {response.status_code}")
            return {
                "brain": brain_name,
                "error": f"HTTP {response.status_code}: {response.text[:100]}",
                "status": "error"
            }
            
    except requests.exceptions.Timeout:
        print(f"   ❌ TIMEOUT después de {brain['timeout']} segundos")
        return {
            "brain": brain_name,
            "error": f"Timeout ({brain['timeout']}s)",
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

def route_intent(prompt: str) -> str:
    """
    Decide qué cerebro usar según la consulta
    """
    prompt_lower = prompt.lower()
    
    # Palabras clave para cerebro rápido (consultas simples)
    rapid_keywords = [
        "hola", "buenas", "saludos", "gracias", "chao", "adiós", "bye",
        "qué hora", "clima", "tiempo", "cómo estás", "qué tal"
    ]
    for kw in rapid_keywords:
        if kw in prompt_lower:
            return "rapido"
    
    # Palabras clave para cerebro crítico (tareas importantes)
    critical_keywords = [
        "alarma", "seguridad", "emergencia", "apagar", "reiniciar",
        "analiza", "analizar", "riesgo", "peligro", "critico"
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
                print(f"   ⚠️ {name}: RESPONDE PERO CON ERROR")
        except:
            print(f"   ❌ {name}: OFFLINE ({brain['model']})")
    
    print("-" * 40)

def main():
    """
    Bucle principal interactivo
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

if __name__ == "__main__":
    main()
