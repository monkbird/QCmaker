from __future__ import annotations
import csv, io
from pathlib import Path
from backend.app.core.errors import AppException
from backend.app.models.materials import ParseManifest, ParseUnit, Region
TEXT_SUFFIXES={'.txt','.md','.markdown'}; SUPPORTED_SUFFIXES=TEXT_SUFFIXES|{'.csv','.xlsx','.xls','.pdf','.docx','.pptx','.png','.jpg','.jpeg'}
def decode_text(raw):
    for enc in ('utf-8-sig','utf-8','gb18030'):
        try:return raw.decode(enc)
        except UnicodeDecodeError: pass
    raise AppException('DATA_FORMAT_UNSUPPORTED','文本编码无法识别，请另存为 UTF-8 后重试',400)
def _grid(rows): return '\n'.join(' | '.join(str(c).replace('\n',' ').strip() for c in row) for row in rows if any(str(c).strip() for c in row))
def _unit(kind,n,loc,regions,issues=None,status='parsed'): return ParseUnit(unit_id=f'{kind}_{n}',kind=kind,ordinal=n,locator=loc,regions=regions,status=status,issues=issues or [])
def parse_source(path:Path,filename=None,recognizer=None):
    path=Path(path); name=filename or path.name; s=path.suffix.lower(); units=[]
    if recognizer is None and s in {'.png','.jpg','.jpeg'}:
        from backend.app.services.material_recognition import RecognitionAdapter
        recognizer=RecognitionAdapter()
    if s not in SUPPORTED_SUFFIXES: raise AppException('DATA_FORMAT_UNSUPPORTED','暂不支持该文件格式；请转换为 PDF、DOCX、PPTX、XLSX、CSV、PNG、JPEG 或文本',400)
    try:
        if s in TEXT_SUFFIXES: units=[_unit('block',1,'文本第1块',[Region(region_id='text_1',kind='text',text=decode_text(path.read_bytes()))])]
        elif s=='.csv':
            rows=list(csv.reader(io.StringIO(decode_text(path.read_bytes())))); units=[_unit('sheet',1,'CSV工作表',[Region(region_id='table_1',kind='table',text=_grid(rows),table_cells=rows)])]
        elif s in {'.xlsx','.xls'}:
            import pandas as pd
            for i,(sheet,frame) in enumerate(pd.read_excel(path,sheet_name=None,header=None,dtype=object).items(),1):
                rows=[['' if pd.isna(c) else str(c) for c in row] for row in frame.values.tolist()]; units.append(_unit('sheet',i,f'工作表[{sheet}]',[Region(region_id=f'table_{i}',kind='table',text=_grid(rows),table_cells=rows)]))
        elif s=='.docx':
            from docx import Document
            doc=Document(str(path)); regs=[Region(region_id=f'text_{i}',kind='text',text=p.text) for i,p in enumerate(doc.paragraphs,1)]
            for i,t in enumerate(doc.tables,1):
                rows=[[c.text for c in row.cells] for row in t.rows]; regs.append(Region(region_id=f'table_{i}',kind='table',text=_grid(rows),table_cells=rows))
            units=[_unit('block',1,'DOCX正文及表格',regs)]
        elif s=='.pptx':
            from pptx import Presentation
            for i,slide in enumerate( Presentation(str(path)).slides,1):
                regs=[]
                for j,shape in enumerate(slide.shapes,1):
                    if getattr(shape,'has_text_frame',False): regs.append(Region(region_id=f'text_{j}',kind='text',text=shape.text))
                    if getattr(shape,'has_table',False):
                        rows=[[c.text for c in row.cells] for row in shape.table.rows]; regs.append(Region(region_id=f'table_{j}',kind='table',text=_grid(rows),table_cells=rows))
                    if getattr(shape,'shape_type',None)==13: regs.append(Region(region_id=f'image_{j}',kind='image',status='failed',method='pending'))
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip(): regs.append(Region(region_id='notes',kind='notes',text=slide.notes_slide.notes_text_frame.text))
                units.append(_unit('slide',i,f'PPT第{i}页',regs))
        elif s=='.pdf':
            from pypdf import PdfReader
            if recognizer is None:
                from backend.app.services.material_recognition import RecognitionAdapter
                recognizer=RecognitionAdapter()
            pages=list(PdfReader(str(path)).pages)
            rendered=None
            for i,page in enumerate(pages,1):
                text=(page.extract_text() or '').strip(); ok=bool(text)
                if not ok:
                    try:
                        if rendered is None: rendered=recognizer.render(path)
                        result=recognizer.recognize(rendered[i-1]); text='\n'.join(r.text for r in result.regions); ok=bool(text)
                    except AppException: pass
                units.append(_unit('page',i,f'PDF第{i}页',[Region(region_id=f'text_{i}',kind='text',text=text,status='parsed' if ok else 'failed')],[] if ok else ['页面无可提取文本，需渲染并OCR或人工核验'],'parsed' if ok else 'failed'))
        else:
            if recognizer is None: raise AppException('RECOGNITION_UNAVAILABLE','当前环境未配置可用OCR能力，请安装本地OCR运行时后重试',503,{'capability':'ocr'})
            result=recognizer.recognize(path); units=[_unit('page',1,'图片第1页',result.regions,result.issues,'parsed' if not result.issues else 'failed')]
    except AppException: raise
    except Exception as exc: raise AppException('DATA_FORMAT_UNSUPPORTED',f'文档解析失败：{exc}',400) from exc
    complete=bool(units) and all(u.status in {'parsed','verified_blank'} and all(r.status=='parsed' for r in u.regions) for u in units); failed=sum(u.status=='failed' for u in units); pending=sum(u.status=='pending' for u in units)
    return ParseManifest(material_id='',version=1,units_total=len(units),units_completed=len(units)-failed-pending,units_failed=failed,units_pending=pending,coverage_complete=complete,readiness='readable' if complete else ('needs_review' if failed else 'partial'),review_status='unreviewed',units=units)
def extract_documents(file_path,original_filename):
    from langchain_core.documents import Document
    m=parse_source(Path(file_path),original_filename); docs=[Document(page_content='\n'.join(r.text for r in u.regions if r.text),metadata={'source':original_filename,'locator':u.locator}) for u in m.units]; docs=[d for d in docs if d.page_content.strip()]
    if not docs: raise AppException('DOCUMENT_TEXT_EMPTY','未能从文档中提取到文本内容',400)
    return docs
