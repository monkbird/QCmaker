from pathlib import Path
import pytest
from PIL import Image,ImageDraw,ImageFont
from backend.app.services.material_recognition import RecognitionAdapter
from backend.app.services.document_parser import parse_source

pytestmark = pytest.mark.skipif(not Path('C:/Windows/Fonts/msyh.ttc').exists(), reason='真实中文OCR验收需要中文字体')

def test_local_rapidocr_reads_generated_chinese(tmp_path):
    font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',42)
    image=Image.new('RGB',(1000,180),'white'); ImageDraw.Draw(image).text((30,35),'汤浦水库清淤项目 安全巡检',font=font,fill='black')
    path=tmp_path/'sample.png'; image.save(path)
    result=RecognitionAdapter().recognize(path)
    text=''.join(r.text for r in result.regions)
    assert '汤浦' in text and result.regions[0].confidence is not None

def test_real_rapidocr_reads_unicode_safe_png_and_scanned_pdf(tmp_path):
    pytest.importorskip('rapidocr_onnxruntime')
    import fitz
    font_path = Path('C:/Windows/Fonts/msyh.ttc')
    if not font_path.exists(): pytest.skip('Windows 中文字体不可用')
    font=ImageFont.truetype(str(font_path),42)
    image=Image.new('RGB',(1000,180),'white')
    ImageDraw.Draw(image).text((30,35),'\u6c64\u6d66\u6c34\u5e93\u6e05\u6de4\u9879\u76ee \u5b89\u5168\u5de1\u68c0',font=font,fill='black')
    png=tmp_path/'scan.png'; image.save(png)
    pdf=tmp_path/'scan.pdf'; image.save(pdf,'PDF',resolution=150)
    adapter=RecognitionAdapter()
    png_text=''.join(r.text for r in adapter.recognize(png).regions)
    manifest=parse_source(pdf,pdf.name,adapter)
    pdf_text=''.join(r.text for u in manifest.units for r in u.regions)
    (tmp_path/'ocr-output.txt').write_text(f'PNG: {png_text}\nPDF: {pdf_text}\n',encoding='utf-8')
    assert '\u6c64\u6d66' in png_text
    assert '\u6c64\u6d66' in pdf_text
