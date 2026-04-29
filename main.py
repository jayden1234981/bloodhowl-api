from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import json
import asyncio
import os
from contextlib import suppress

app = FastAPI(title="BLOODHOWL API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Thread-safe connection manager
class ConnectionManager:
    def __init__(self):
        self.active: List = []
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, client_data: dict):
        async with self.lock:
            self.active.append({
                "websocket": websocket,
                "info": client_data,
                "is_mentor": client_data.get('role') == 'mentor'
            })

    async def disconnect(self, websocket: WebSocket):
        async with self.lock:
            self.active[:] = [c for c in self.active if c["websocket"]!= websocket]

    async def broadcast_to_broker(self, signal_data: dict):
        async with self.lock:
            for client in self.active:
                if not client["is_mentor"] and client['info']['broker'] == signal_data['broker']:
                    with suppress(Exception):
                        await client['websocket'].send_json(signal_data)

manager = ConnectionManager()
mentor_token = os.getenv("MENTOR_TOKEN",BLOODHOWL_PLACEHOLDER_123")
approved_brokers = ["Razor Markets", "Trade245", "XM", "RCG MARKET", "Exness", "Just Markets", "Headway", "Profin Wealth"]

class Signal(BaseModel):
    broker: str
    symbol: str
    action: str # buy/sell
    volume: float
    stop_loss: float
    take_profit: float
    token: str
    strategy: str = "Reversal Pattern"
    reward: int = 0 # 0-100%

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        # 1. Get client info with 10s timeout
        client_info = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        client_data = json.loads(client_info)

        # 2. Validate broker before adding
        if client_data.get('role')!= 'mentor':
            if client_data.get('broker') not in approved_brokers:
                await websocket.close(code=1008, reason="Broker not supported")
                return

        await manager.connect(websocket, client_data)

        # 3. Heartbeat every 25s to prevent Render killing idle WS
        while True:
            await asyncio.sleep(25)
            await websocket.send_json({"type": "ping"})

    except asyncio.TimeoutError:
        await websocket.close(code=1001, reason="No client info sent in 10s")
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as e:
        await manager.disconnect(websocket)
        with suppress(Exception):
            await websocket.close(code=1011, reason=str(e)[:123])

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

    asyncio.create_task(manager.broadcast_to_broker(signal_data))
    return {"status": "success", "message": "Signal broadcasted"}

@app.get("/")
def root():
    return {"status": "BLOODHOWL API Live", "clients_connected": len(manager.active)}

@app.get("/health")
def health():
    return {"status": "ok"} # Ping this with UptimeRobot to prevent sleep

# NOTE: MT5/MT4 execution happens on CLIENT SIDE app, not server
# Server can't run terminal64.exe. The app receives signal via WS and executes locally
