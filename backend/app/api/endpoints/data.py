from fastapi import APIRouter, UploadFile, File, HTTPException
from backend.app.services.data_cleaning import data_cleaning_service

router = APIRouter()

@router.post("/upload")
async def upload_data(file: UploadFile = File(...)):
    try:
        content = await file.read()
        data = data_cleaning_service.clean_data(content, file.filename)
        return {"data": data, "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
