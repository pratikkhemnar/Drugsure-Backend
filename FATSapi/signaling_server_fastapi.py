from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import logging
from typing import Dict

app = FastAPI(title="WebRTC Signaling Server")

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.room_users: Dict[str, set] = {}

    async def connect(self, websocket: WebSocket, room_id: str, user_id: str):
        await websocket.accept()
        
        # Store connection
        key = f"{room_id}:{user_id}"
        self.active_connections[key] = websocket
        
        # Add to room
        if room_id not in self.room_users:
            self.room_users[room_id] = set()
        self.room_users[room_id].add(user_id)
        
        print(f"✅ {user_id} connected to room {room_id}")
        
        # Notify other users in room
        for uid in self.room_users[room_id]:
            if uid != user_id:
                other_key = f"{room_id}:{uid}"
                if other_key in self.active_connections:
                    await self.send_message(
                        self.active_connections[other_key],
                        {"type": "peer-joined", "userId": user_id}
                    )

    def disconnect(self, room_id: str, user_id: str):
        key = f"{room_id}:{user_id}"
        if key in self.active_connections:
            del self.active_connections[key]
        
        if room_id in self.room_users:
            self.room_users[room_id].discard(user_id)
            if not self.room_users[room_id]:
                del self.room_users[room_id]
        
        print(f"❌ {user_id} disconnected from room {room_id}")

    async def send_message(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_json(message)
        except Exception as e:
            print(f"Error sending message: {e}")

    async def broadcast_to_room(self, room_id: str, message: dict, exclude_user: str = None):
        if room_id in self.room_users:
            for user_id in self.room_users[room_id]:
                if user_id != exclude_user:
                    key = f"{room_id}:{user_id}"
                    if key in self.active_connections:
                        await self.send_message(self.active_connections[key], message)

manager = ConnectionManager()

@app.websocket("/ws/{room_id}/{user_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, user_id: str):
    await manager.connect(websocket, room_id, user_id)
    
    try:
        while True:
            data = await websocket.receive_json()
            print(f"📨 From {user_id} in {room_id}: {data['type']}")
            
            # Handle different message types
            if data["type"] == "offer":
                await manager.broadcast_to_room(
                    room_id, 
                    {"type": "offer", "from": user_id, "sdp": data["sdp"]},
                    exclude_user=user_id
                )
            elif data["type"] == "answer":
                await manager.broadcast_to_room(
                    room_id,
                    {"type": "answer", "from": user_id, "sdp": data["sdp"]},
                    exclude_user=user_id
                )
            elif data["type"] == "ice-candidate":
                await manager.broadcast_to_room(
                    room_id,
                    {"type": "ice-candidate", "from": user_id, "candidate": data["candidate"]},
                    exclude_user=user_id
                )
            elif data["type"] == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        manager.disconnect(room_id, user_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(room_id, user_id)

@app.get("/")
async def root():
    return {
        "status": "active",
        "service": "WebRTC Signaling Server",
        "endpoints": {
            "websocket": "/ws/{room_id}/{user_id}",
            "health": "/health"
        }
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "connections": len(manager.active_connections)}

@app.get("/rooms")
async def get_rooms():
    return {
        "active_rooms": len(manager.room_users),
        "rooms": {room: list(users) for room, users in manager.room_users.items()}
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "signaling_server_fastapi:app",
        host="0.0.0.0",
        port=4000,
        reload=True
    )