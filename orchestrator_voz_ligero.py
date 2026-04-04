#!/usr/bin/env python3
"""
Asistente Local por Voz - Versión Ultra Ligera
STT: Vosk | LLM: phi3-fast | TTS: eSpeak
"""

import os
import json
import requests
import wave
import pyaudio
import vosk
import subprocess

# Configuración
STT_MODEL = "modelo_stt"
LLM_URL = "http://localhost:11434/api/generate"
LLM_MODEL = "phi3-fast"

FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 4000
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 1.5

def speak(text):
    if text:
        subprocess.run(['espeak', '-v', 'es', text])

def transcribe(file_path):
    model = vosk.Model(STT_MODEL)
    rec = vosk.KaldiRecognizer(model, RATE)
    wf = wave.open(file_path, "rb")
    while True:
        data = wf.readframes(4000)
        if not data:
            break
        rec.AcceptWaveform(data)
    result = json.loads(rec.FinalResult())
    wf.close()
    return result.get("text", "")

def record():
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    print("🎤 Escuchando...")
    frames = []
    silent = 0
    recording = False
    
    for _ in range(1000):
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)
        level = max(abs(int.from_bytes(data[i:i+2], 'little', signed=True)) for i in range(0, len(data), 2))
        if level > SILENCE_THRESHOLD:
            if not recording:
                print("🔴 Grabando...")
                recording = True
            silent = 0
        elif recording:
            silent += 1
            if silent > (SILENCE_DURATION * RATE / CHUNK):
                break
    
    stream.stop_stream()
    stream.close()
    p.terminate()
    
    temp = "/tmp/input.wav"
    wf = wave.open(temp, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(p.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()
    return temp

def query_llm(prompt):
    try:
        r = requests.post(LLM_URL, json={"model": LLM_MODEL, "prompt": prompt, "stream": False}, timeout=45)
        return r.json().get("response", "Error") if r.status_code == 200 else "Error"
    except:
        return "Error de conexión"

def main():
    print("=" * 50)
    print("🎤 ASISTENTE LOCAL (versión ligera)")
    print("=" * 50)
    print("Di 'adiós' para salir\n")
    
    while True:
        try:
            audio = record()
            texto = transcribe(audio)
            os.remove(audio)
            if not texto:
                continue
            print(f"\n📝 Tú: {texto}")
            if texto.lower() in ["adiós", "salir", "chao"]:
                speak("¡Hasta luego!")
                break
            print("🤔 Pensando...")
            resp = query_llm(texto)
            print(f"🤖 Asistente: {resp}")
            speak(resp)
        except KeyboardInterrupt:
            speak("¡Hasta luego!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
