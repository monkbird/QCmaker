import base64
import io
import os
import time

import pytest
from PIL import Image
from pptx import Presentation

from backend.app.core.errors import AppException
from backend.app.models.contracts import ChartRequest, CleaningRule, DataRow
from backend.app.services.chart import generate
from backend.app.services.data_cleaning import analyze, apply_rules, parse_file


def test_duplicate_headers_rejected():
    with pytest.raises(AppException): parse_file(b' A,A \n1,2\n', 'x.csv')

@pytest.mark.parametrize('name,content', [('x.csv', b''), ('x.xlsx', b'broken')])
def test_invalid_upload_is_business_error(name, content):
    with pytest.raises(AppException): parse_file(content, name)

def test_percent_and_boolean_types():
    rows = [DataRow(row_id='1', values={'rate':'90%', 'ok':True}), DataRow(row_id='2',values={'rate':'80%', 'ok':False})]
    cols, report = analyze(rows)
    assert cols[1].inferred_type == 'boolean'
    assert any('convert_percent' in x.suggested_actions for x in report.issues)
    cleaned, columns, _ = apply_rules(rows, [CleaningRule(action='convert_percent', column='rate')])
    assert cleaned[0].values['rate'] == .9
    assert columns[0].display_format == 'percent'

def test_chart_axes_count_and_pie():
    rows = [DataRow(row_id='1', values={'x':'A','y':'ok'}), DataRow(row_id='2', values={'x':'A','y':None})]
    def req(**kw): return ChartRequest(dataset_id='d',revision=0,chart_type='bar',x_axis='x',y_axis='y',**kw)
    assert generate(req(aggregation='count'), rows).option['series'][0]['data'] == [2]
    with pytest.raises(AppException): generate(req().model_copy(update={'x_axis':'absent'}), rows)
    for vals in [[-1, 2], [0,0]]:
        with pytest.raises(AppException): generate(req().model_copy(update={'chart_type':'pie'}), [DataRow(row_id=str(i), values={'x':str(i),'y':v}) for i,v in enumerate(vals)])

def test_validation_errors_are_422(client):
    res = client.post('/api/data/preview', json={'dataset_id':'x','base_revision':0,'rules':[{'action':'median'}]})
    assert res.status_code == 422
    assert res.json()['code'] == 'REQUEST_INVALID'

def test_ppt_images_bounds_pagination_and_validation(client):
    buf=io.BytesIO(); Image.new('RGB',(400,200)).save(buf,format='PNG')
    payload={'project_name':'测试','topic':'课题','data_summary':'长文本'*1000,'discussion_summary':{'problem':'问题','root_causes':[],'countermeasures':[],'summary':'总结'},'chart_images':[base64.b64encode(buf.getvalue()).decode()]*5}
    res=client.post('/api/ppt/generate',json=payload); assert res.status_code==200
    prs=Presentation(io.BytesIO(client.get('/api/ppt/download/'+res.json()['file_id']).content))
    pictures=[shape for slide in prs.slides for shape in slide.shapes if shape.shape_type==13]
    assert len(pictures)==5 and len(prs.slides)>6
    for shape in pictures:
        assert shape.left+shape.width<=prs.slide_width and shape.top+shape.height<=prs.slide_height
        assert abs(shape.width/shape.height-2)<.01
    payload['chart_images']=[base64.b64encode(b'\x89PNG\r\n\x1a\ninvalid').decode()]
    assert client.post('/api/ppt/generate',json=payload).status_code==400

def test_ppt_cleanup_only_old_orphans(isolated_storage):
    from backend.app.services import ppt
    ppt.OUTPUT_DIR.mkdir(); fresh=ppt.OUTPUT_DIR/'.fresh.tmp.pptx'; old=ppt.OUTPUT_DIR/'.old.tmp.pptx'
    fresh.write_bytes(b'x'); old.write_bytes(b'x'); os.utime(old,(time.time()-90000,)*2)
    assert ppt._purge_stale_temp_files()==1
    assert fresh.exists() and not old.exists()

def test_percent_metadata_survives_followup_cleaning(client):
    uploaded=client.post('/api/data/upload',files={'file':('x.csv',b'category,rate\na,90%\na,80%\n','text/csv')}).json()
    payload={'dataset_id':uploaded['dataset_id'],'base_revision':0,'rules':[{'action':'convert_percent','column':'rate'}]}
    result=client.post('/api/data/apply',json=payload).json()
    payload.update(base_revision=1,rules=[{'action':'keep'}])
    result=client.post('/api/data/apply',json=payload).json()
    assert result['columns'][1]['display_format']=='percent'
    client.post('/api/data/confirm',json={'dataset_id':uploaded['dataset_id'],'revision':2})
    chart=client.post('/api/visualization/generate',json={'dataset_id':uploaded['dataset_id'],'revision':2,'chart_type':'bar','x_axis':'category','y_axis':'rate'}).json()
    assert chart['processing']['aggregation']=='mean'
    assert chart['option']['series'][0]['data']==[pytest.approx(.85)]

@pytest.mark.parametrize('content',[b'A,A\n1,2\n',b'A,B\n1,2,3\n',b'A\n'+b'1\n'*5001])
def test_parse_limits(content):
    with pytest.raises(AppException): parse_file(content,'x.csv')

def test_ai_recommendation_preserves_mean():
    from types import SimpleNamespace

    from backend.app.api.endpoints.visualization import _validate_recommendation
    from backend.app.models.contracts import ColumnInfo
    dataset=SimpleNamespace(columns=[ColumnInfo(name='x',inferred_type='string',missing_count=0,outlier_count=0),ColumnInfo(name='y',inferred_type='percent',missing_count=0,outlier_count=0)])
    assert _validate_recommendation({'chart_type':'bar','x_axis':'x','y_axis':'y','aggregation':'mean'},dataset).aggregation=='mean'

def test_excel_zip_expansion_limit_applies_to_disguised_extension(monkeypatch):
    import zipfile
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('xl/worksheets/sheet1.xml',b' '*(41*1024*1024))
    import pandas as pd
    calls=[]
    monkeypatch.setattr(pd,'read_excel',lambda *a,**kw: calls.append(True))
    with pytest.raises(AppException) as exc: parse_file(buf.getvalue(),'data.xls')
    assert not calls
    assert exc.value.status_code==400

def test_percent_conversion_does_not_scale_twice():
    rows=[DataRow(row_id='1',values={'rate':'90%'})]
    rules=[CleaningRule(action='convert_percent',column='rate')]
    first,columns,_=apply_rules(rows,rules)
    second,_,report=apply_rules(first,rules,source_columns=columns)
    assert second[0].values['rate']==.9 and report.type_conversions==0

def test_percent_fill_and_conversion_selection_order():
    rows=[DataRow(row_id='1',values={'rate':'90%'}),DataRow(row_id='2',values={'rate':None})]
    _,report=analyze(rows)
    rules=[CleaningRule(action=issue.suggested_actions[0],column=issue.column,row_ids=issue.row_ids) for issue in report.issues if issue.column=='rate']
    result,_,_=apply_rules(rows,rules)
    assert [row.values['rate'] for row in result]==[.9,.9]
