from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any
from backend.app.services.chart import chart_service

router = APIRouter()

class ChartRequest(BaseModel):
    chart_type: str
    data: List[Dict[str, Any]]
    x_axis: str
    y_axis: str

@router.post("/generate")
async def generate_chart(request: ChartRequest):
    try:
        option = chart_service.generate_chart_option(
            request.chart_type, 
            request.data, 
            request.x_axis, 
            request.y_axis
        )
        return option
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
