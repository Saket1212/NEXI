import asyncio
import sounddevice as sd
import numpy as np
import websockets
import base64
import json
import threading
from queue import Queue

# 🔑 OpenAI API Key
OPENAI_API_KEY = ""
# Audio Settings
SAMPLE_RATE = 24000
CHANNELS = 1
BLOCKSIZE = 1024

# Audio queue for thread-safe communication
audio_queue = Queue()

def encode_audio_pcm16(audio_data):
    int16_audio = (audio_data * 32767).astype(np.int16)
    return base64.b64encode(int16_audio.tobytes()).decode("utf-8")

def decode_audio_pcm16(base64_audio):
    audio_bytes = base64.b64decode(base64_audio)
    audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32767.0
    return audio_array

# Audio callback - runs in separate thread
def audio_callback(indata, frames, time, status):
    if status:
        print(f"Audio status: {status}")
    
    audio_data = np.squeeze(indata)
    encoded_audio = encode_audio_pcm16(audio_data)
    audio_queue.put(encoded_audio)

async def realtime_conversation():
    # WebSocket URL with authentication
    uri = f"wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"
    
    # Connect with authentication headers
    headers = [
        ("Authorization", f"Bearer {OPENAI_API_KEY}"),
        ("OpenAI-Beta", "realtime=v1")
    ]
    
    async with websockets.connect(uri, additional_headers=headers) as ws:
        
        # Configure session
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": "You are a helpful AI assistant. Keep responses brief and natural.",
                "voice": "alloy",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "silence_duration_ms": 200
                }
            }
        }
        
        await ws.send(json.dumps(session_config))
        print("🎤 Session configured. Start speaking...")
        
        # Start audio input stream
        stream = sd.InputStream(
            callback=audio_callback,
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            blocksize=BLOCKSIZE,
            dtype=np.float32
        )
        stream.start()
        
        # Audio sender task
        async def send_audio():
            while True:
                try:
                    # Get audio from queue (non-blocking)
                    if not audio_queue.empty():
                        encoded_audio = audio_queue.get_nowait()
                        await ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": encoded_audio
                        }))
                    
                    await asyncio.sleep(0.001)  # Small delay to prevent busy waiting
                
                except Exception as e:
                    print(f"Audio send error: {e}")
                    break
        
        # Message handler task
        async def handle_messages():
            while True:
                try:
                    message = await ws.recv()
                    data = json.loads(message)
                    msg_type = data.get("type")
                    
                    # Debug: Print all message types and data
                    print(f"📨 Message type: {msg_type}")
                    
                    # Print full data for debugging (only for specific types)
                    if msg_type in ["response.output_item.added", "response.content_part.added", "conversation.item.created"]:
                        print(f"🔍 Data: {json.dumps(data, indent=2)}")
                    
                    if msg_type == "session.created":
                        print("✅ Connected successfully")
                    
                    elif msg_type == "input_audio_buffer.speech_started":
                        print("🎙️ Listening...")
                    
                    elif msg_type == "input_audio_buffer.speech_stopped":
                        print("⏸️ Processing...")
                    
                    elif msg_type == "response.audio.delta":
                        # Play audio immediately
                        audio_b64 = data.get("delta", "")
                        if audio_b64:
                            audio_data = decode_audio_pcm16(audio_b64)
                            sd.play(audio_data, samplerate=SAMPLE_RATE)
                    
                    elif msg_type == "conversation.item.created":
                        # Check if it's assistant's response text
                        item = data.get("item", {})
                        if item.get("role") == "assistant" and item.get("type") == "message":
                            content = item.get("content", [])
                            for c in content:
                                if c.get("type") == "text":
                                    text = c.get("text", "")
                                    print(f"\n🤖 Full Response: {text}")
                    
                    elif msg_type == "response.text.delta":
                        text = data.get("delta", "")
                        print(f"🤖 {text}", end="", flush=True)
                    
                    elif msg_type == "response.text.done":
                        # Complete text response
                        text = data.get("text", "")
                        if text:
                            print(f"\n🤖 Complete Response: {text}")
                    
                    elif msg_type == "response.output_item.added":
                        # Check for text content in response
                        item = data.get("item", {})
                        if item.get("type") == "message":
                            content = item.get("content", [])
                            for c in content:
                                if c.get("type") == "text":
                                    text = c.get("text", "")
                                    if text:
                                        print(f"\n🗣️ TTS Text: {text}")
                    
                    elif msg_type == "response.content_part.added":
                        # Another way to catch text content
                        part = data.get("part", {})
                        if part.get("type") == "text":
                            text = part.get("text", "")
                            if text:
                                print(f"\n🗣️ TTS Content: {text}")
                    
                    elif msg_type == "conversation.item.input_audio_transcription.completed":
                        # Your speech transcription
                        transcript = data.get("transcript", "")
                        if transcript:
                            print(f"\n👤 You said: {transcript}")
                    
                    elif msg_type == "response.audio_transcript.delta":
                        # Audio transcript delta
                        delta = data.get("delta", "")
                        if delta:
                            print(f"🎵 Audio transcript: {delta}", end="", flush=True)
                    
                    elif msg_type == "response.audio_transcript.done":
                        # Complete audio transcript
                        transcript = data.get("transcript", "")
                        if transcript:
                            print(f"\n🎵 Full TTS transcript: {transcript}")
                    
                    elif msg_type == "response.done":
                        print("\n🤖 Response complete")
                    
                    elif msg_type == "error":
                        error_msg = data.get("error", {}).get("message", "Unknown error")
                        print(f"❌ Error: {error_msg}")
                
                except websockets.exceptions.ConnectionClosed:
                    print("Connection closed")
                    break
                except Exception as e:
                    print(f"Message handling error: {e}")
                    break
        
        # Run both tasks
        try:
            await asyncio.gather(send_audio(), handle_messages())
        finally:
            stream.stop()
            stream.close()

if __name__ == "__main__":
    if not OPENAI_API_KEY:
        print("❌ Please add your OpenAI API key!")
        exit(1)
    
    try:
        asyncio.run(realtime_conversation())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {e}")