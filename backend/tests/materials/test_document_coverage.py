from pathlib import Path
from backend.app.services.document_parser import parse_source

def test_csv_tail_is_not_lost(tmp_path: Path):
    source=tmp_path/'台账.csv'; source.write_text('序号,记录\n'+'\n'.join(f'{i},巡检记录{i}' for i in range(1501)),encoding='utf-8')
    result=parse_source(source,source.name)
    text='\n'.join(r.text for u in result.units for r in u.regions)
    assert '巡检记录1500' in text and result.coverage_complete

def test_pdf_scanned_page_is_retained_for_review(tmp_path: Path, monkeypatch):
    class Page:
        def extract_text(self): return ''
    class Reader:
        pages=[Page()]
    import pypdf
    monkeypatch.setattr(pypdf,'PdfReader',lambda _:Reader())
    p=tmp_path/'scan.pdf'; p.write_bytes(b'%PDF')
    result=parse_source(p,p.name)
    assert result.units_total==1 and result.units_failed==1 and '需渲染' in result.units[0].issues[0]
