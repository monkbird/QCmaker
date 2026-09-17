from pathlib import Path
from functools import lru_cache
from threading import Lock
from backend.app.core.errors import AppException
from backend.app.models.materials import RecognitionResult,Region

_recognition_lock = Lock()
@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()

class RecognitionAdapter:
    def recognize(self, image_path: Path, *, language: str = 'chi_sim+eng') -> RecognitionResult:
        try:
            with _recognition_lock:
                result,_=_engine()(str(image_path))
            regions=[]
            for i,row in enumerate(result or [],1):
                regions.append(Region(region_id=f'ocr_{i}',kind='text',text=str(row[1]),bbox=[float(v) for point in row[0] for v in point],confidence=float(row[2]),method='rapidocr'))
            return RecognitionResult(method='rapidocr',regions=regions,issues=[] if regions else ['OCR未识别到文字'])
        except Exception:
          try:
            import pytesseract
            from PIL import Image
            text=pytesseract.image_to_string(Image.open(image_path),lang=language)
            return RecognitionResult(method='tesseract',regions=[Region(region_id='ocr_1',kind='text',text=text)] if text.strip() else [],issues=[] if text.strip() else ['OCR未识别到文字'])
          except Exception as inner:
            raise AppException('RECOGNITION_UNAVAILABLE','当前环境未配置可用OCR能力，请安装本地OCR运行时后重试',503,{'capability':'ocr'}) from inner
    def render(self, source_path: Path) -> list[Path]:
        try:
            import fitz
            doc=fitz.open(str(source_path)); out=[]
            for i,page in enumerate(doc):
                p=source_path.parent/(source_path.stem+f'.page-{i+1}.png'); pix=page.get_pixmap(matrix=fitz.Matrix(2,2)); pix.save(str(p)); out.append(p)
            return out
        except Exception as exc: raise AppException('RECOGNITION_UNAVAILABLE','当前环境未配置文档渲染能力',503,{'capability':'render'}) from exc
