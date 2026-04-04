#!/usr/bin/env python3
"""
Asistente Local por Voz - Con arecord
STT: Vosk | LLM: phi3-fast | TTS: eSpeak
"""

import os
import json
import requests
import subprocess
import tempfile

# Configuración
STT_MODEL = "modelo_stt"
LLM_URL = "http://localhost:11434/api/generate"
LLM_MODEL = "phi3-fast"

def speak(text):
    """TTS con eSpeak"""
    if text:
        subprocess.run(['espeak', '-v', 'es', text])

def record():
    """Graba usando arecord (más estable)"""
    temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_file.close()
    
    print("🎤 Escuchando... (presiona Enter cuando termines de hablar)")
    input("   Presiona Enter para empezar a grabar...")
    
    print("🔴 Grabando... (habla ahora)")
    cmd = f'arecord -d 5 -f cd -t wav {temp_file.name}'
    subprocess.run(cmd, shell=True)
    
    print("✅ Grabación completada")
    return temp_file.name

def transcribe(file_path):
    """STT con Vosk"""
    from vosk import Model, KaldiRecognizer
    import wave
    
    model = Model(STT_MODEL)
    rec = KaldiRecognizer(model, 16000)
    
    wf = wave.open(file_path, "rb")
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        rec.AcceptWaveform(data)
    
    result = json.loads(rec.FinalResult())
    wf.close()
    return result.get("text", "")

def query_llm(prompt):
    """Consulta al LLM"""
    try:
        response = requests.post(
            LLM_URL,
            json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
            timeout=45
        )
        if response.status_code == 200:
            return response.json().get("response", "Lo siento, no pude procesar tu consulta")
        return "Error en la conexión con el modelo"
    except Exception as e:
        return f"Error: {e}"

def main():
    print("=" * 50)
    print("🎤 ASISTENTE LOCAL POR VOZ")
    print("=" * 50)
    print("📝 Instrucciones:")
    print("   1. Escribe 'grabar' para empezar")
    print("   2. Habla después de que empiece la grabación")
    print("   3. Espera la respuesta en voz")
    print("   4. Escribe 'salir' para terminar\n")
    
    while True:
        try:
            comando = input("📋 ¿Qué deseas hacer? (grabar/salir): ").strip().lower()
            
            if comando == "salir":
                speak("¡Hasta luego!")
                break
            
            if comando == "grabar":
                # Grabar audio
                audio_file = record()
                
                # Transcribir
                print("📝 Transcribiendo...")
                texto = transcribe(audio_file)
                os.unlink(audio_file)
                
                if not texto:
                    print("   No te entendí, intenta de nuevo")
                    continue
                
                print(f"\n📝 Tú: {texto}")
                
                # Procesar con LLM
                print("🤔 Pensando...")
                respuesta = query_llm(texto)
                print(f"🤖 Asistente: {respuesta}\n")
                
                # Responder con voz
                speak(respuesta)
            
        except KeyboardInterrupt:
            speak("¡Hasta luego!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            continue

if __name__ == "__main__":
    # Verificar que el modelo STT existe
    if not os.path.exists(STT_MODEL):
        print(f"❌ Modelo STT no encontrado en {STT_MODEL}")
        print("   Descárgalo con: wget https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip")
        exit(1)
    
    main()
