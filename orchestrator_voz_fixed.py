#!/usr/bin/env python3
"""
Asistente Local por Voz - Versión Corregida
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
        subprocess.run(['espeak', '-v', 'es', text], stderr=subprocess.DEVNULL)

def record():
    """Graba y convierte a formato correcto (16kHz mono)"""
    temp_raw = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_raw.close()
    
    temp_converted = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_converted.close()
    
    print("\n🎤 Presiona Enter para empezar a grabar (5 segundos)...")
    input("   (preparado?) ")
    
    print("🔴 Grabando... (habla ahora)")
    subprocess.run(f'arecord -d 5 -f cd -t wav {temp_raw.name}', shell=True, stderr=subprocess.DEVNULL)
    
    print("🔄 Convirtiendo formato...")
    # Convertir a 16kHz mono (formato que Vosk espera)
    subprocess.run([
        'sox', temp_raw.name, '-r', '16000', '-c', '1', temp_converted.name
    ], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    
    os.unlink(temp_raw.name)
    print("✅ Grabación completada")
    return temp_converted.name

def transcribe(file_path):
    """STT con Vosk"""
    from vosk import Model, KaldiRecognizer
    import wave
    
    if not os.path.exists(file_path):
        return ""
    
    model = Model(STT_MODEL)
    rec = KaldiRecognizer(model, 16000)
    
    wf = wave.open(file_path, "rb")
    print(f"   Formato audio: {wf.getnchannels()} canales, {wf.getframerate()} Hz")
    
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        rec.AcceptWaveform(data)
    
    result = json.loads(rec.FinalResult())
    wf.close()
    os.unlink(file_path)
    
    text = result.get("text", "")
    print(f"   Texto reconocido: '{text}'")
    return text

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
    print("=" * 60)
    print("🎤 ASISTENTE LOCAL POR VOZ (versión corregida)")
    print("=" * 60)
    print("\n📝 Instrucciones:")
    print("   1. Escribe 'grabar' para empezar")
    print("   2. Presiona Enter cuando estés listo")
    print("   3. Habla durante 5 segundos")
    print("   4. Espera la respuesta en voz")
    print("   5. Escribe 'salir' para terminar\n")
    
    while True:
        try:
            comando = input("📋 ¿Qué deseas hacer? (grabar/salir): ").strip().lower()
            
            if comando == "salir":
                speak("¡Hasta luego!")
                break
            
            if comando == "grabar":
                # Verificar que sox está instalado
                if not os.system("which sox > /dev/null 2>&1") == 0:
                    print("❌ Instalando sox...")
                    os.system("sudo apt install sox -y")
                
                # Grabar y convertir
                audio_file = record()
                
                # Transcribir
                print("📝 Transcribiendo...")
                texto = transcribe(audio_file)
                
                if not texto:
                    print("   ❌ No te entendí, intenta de nuevo")
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
        exit(1)
    
    main()

