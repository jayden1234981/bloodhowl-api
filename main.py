from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict
from pydantic import BaseModel
import json
import asyncio

app = FastAPI()

# Allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active connections
clients: List[Dict] = []
mentor_token = "CHANGE_THIS_MENTOR_TOKEN_123" # Move to env var in production

approved_brokers = ["Razor Markets", "Accumarkets", "XM", "RCG MARKET", "Exness", "Just Markets", "Headway", "Profin Wealth"]

class Signal(BaseModel):
    broker: str
    symbol: str
    action: str # buy/sell
    volume: float
    stop_loss: float
    take_profit: float
    token: str
    strategy: str = "Reversal Pattern" # reason for entry
    reward: int = 0 # 0-100%

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        client_info = await websocket.receive_text()
        client_data = json.loads(client_info)

        if client_data.get('role') == 'mentor':
            clients.append({"websocket": websocket, "info": client_data, "is_mentor": True})
        else:
            # Validate MT4/MT5 creds here before adding
            if client_data['broker'] not in approved_brokers:
                await websocket.close(code=1008, reason="Broker not supported")
                return
            clients.append({"websocket": websocket, "info": client_data, "is_mentor": False})

        while True:
            await websocket.receive_text() # Keep alive
    except WebSocketDisconnect:
        clients[:] = [c for c in clients if c["websocket"]!= websocket]
    except Exception as e:
        await websocket.close(code=1011, reason=str(e))

async def broadcast_signal(signal_data: dict):
    disconnected = []
    for client in clients:
        if not client["is_mentor"] and client['info']['broker'] == signal_data['broker']:
            try:
                await client['websocket'].send_json(signal_data)
            except:
                disconnected.append(client)
    for client in disconnected:
        clients.remove(client)

@app.post("/send_signal")
async def send_signal(signal: Signal):
    if signal.token!= mentor_token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if signal.broker not in approved_brokers:
        raise HTTPException(status_code=400, detail="Broker not supported")

    if not 0 <= signal.reward <= 100:
        raise HTTPException(status_code=400, detail="Reward must be 0-100%")

    signal_data = signal.dict()
    del signal_data['token'] # Don't broadcast token

    # Broadcast to all users of that broker in <10s
    asyncio.create_task(broadcast_signal(signal_data))

    return {"status": "success", "message": "Signal broadcasted", "execution_time": "<10s"}

@app.get("/")
def root():
    return {"status": "EA SURGE API Live", "clients_connected": len(clients)}

# NOTE: MT5/MT4 execution happens on CLIENT SIDE app, not server
# Server can't run terminal64.exe. The app receives signal via WS and executes locally