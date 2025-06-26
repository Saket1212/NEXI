

# import socketio
# import uvicorn
# from fastapi import FastAPI
# from bot import (
#     get_user_profile,
#     force_jlr_context_reply_with_llm,
#     interruption_manager  # Importing the global interruption manager
# )

# sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
# app = FastAPI()
# asgi_app = socketio.ASGIApp(sio, app)

# # Dictionary to track users by socket ID
# connected_users = {}

# @sio.event
# async def connect(sid, environ):
#     print(f"✅ Client connected: {sid}")
#     connected_users[sid] = get_user_profile(user_id=sid)
#     await sio.emit('connected', {'message': 'You are connected to Nexi'}, to=sid)

# @sio.event
# async def disconnect(sid):
#     print(f"❌ Client disconnected: {sid}")
#     connected_users.pop(sid, None)

# @sio.event
# async def user_query(sid, data):
#     print(f"🎤 Received from {sid}: {data}")

#     if not isinstance(data, str) or not data.strip():
#         await sio.emit('bot_response', {'error': 'Empty input'}, to=sid)
#         return

#     user_profile = connected_users.get(sid)
#     if not user_profile:
#         user_profile = get_user_profile(sid)
#         connected_users[sid] = user_profile

#     session_id = interruption_manager.get_new_session_id()

#     # Async response generation in thread
#     def run_response():
#         response = force_jlr_context_reply_with_llm(data, user_profile, session_id)
#         if response and interruption_manager.should_continue_processing(session_id):
#             print(f"🤖 Nexi to {sid}: {response}")
#             import asyncio
#             asyncio.run(sio.emit('bot_response', {'text': response}, to=sid))

#     import threading
#     threading.Thread(target=run_response).start()

# # Optional: Interruption handling
# @sio.event
# async def interrupt(sid):
#     print(f"🔚 Interruption requested by {sid}")
#     interruption_manager.interrupt_current_response()
#     await sio.emit('bot_response', {'text': 'Okay, stopping current response...'}, to=sid)

# # # # # # # To run:
# # # # # # # uvicorn nexi_socket_server:asgi_app --host 0.0.0.0 --port 8000
# # nexi_socket_server.py (real-time interruptible TTS + STT integration)

import socketio
import uvicorn
from fastapi import FastAPI
import threading
import audioop
import asyncio
from bot import (
    get_user_profile,
    force_jlr_context_reply_with_llm,
    interruption_manager  
)

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = FastAPI()
asgi_app = socketio.ASGIApp(sio, app)

connected_users = {}
active_sessions = {}  


@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")
    connected_users[sid] = get_user_profile(user_id=sid)
    await sio.emit('connected', {'message': 'You are connected to Nexi'}, to=sid)


@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")
    connected_users.pop(sid, None)
    active_sessions.pop(sid, None)


@sio.event
async def user_query(sid, data):
    print(f"Received from {sid}: {data}")

    if not isinstance(data, str) or not data.strip():
        await sio.emit('bot_response', {'error': 'Empty input'}, to=sid)
        return

    user_profile = connected_users.get(sid)
    if not user_profile:
        user_profile = get_user_profile(sid)
        connected_users[sid] = user_profile

    session_id = interruption_manager.get_new_session_id()
    active_sessions[sid] = session_id  

    def run_response():
        response = force_jlr_context_reply_with_llm(data, user_profile, session_id)

        if not interruption_manager.should_continue_processing(session_id):
            print(f"Session {session_id} was interrupted, skipping response.")
            return

        if response:
            print(f"🤖 Nexi to {sid}: {response}")
            asyncio.run(sio.emit('bot_response', {'text': response}, to=sid))

    threading.Thread(target=run_response, daemon=True).start()


@sio.event
async def interrupt(sid):
    print(f"🔚 Interruption requested by {sid}")
    interruption_manager.interrupt_current_response()
    await sio.emit('bot_response', {'text': 'Okay, stopping current response...'}, to=sid)





if __name__ == "__main__":
    print("🚀 Nexi server running at: http://0.0.0.0:8000")
    uvicorn.run(asgi_app, host="0.0.0.0", port=8000)
