from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from backend.app.agents.discussion import discussion_orchestrator
from langchain_core.messages import HumanMessage

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            # Initial user input starts the chain
            inputs = {"messages": [HumanMessage(content=data)], "iteration_count": 0}
            
            async for event in discussion_orchestrator.graph.astream(inputs):
                for key, value in event.items():
                    if "messages" in value:
                        # Send the last message from the agent
                        last_msg = value["messages"][-1]
                        await websocket.send_json({
                            "agent": key,
                            "content": last_msg.content
                        })
            
            await websocket.send_json({"status": "done"})
            
    except WebSocketDisconnect:
        print("Client disconnected")
