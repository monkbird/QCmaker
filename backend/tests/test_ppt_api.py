from io import BytesIO

from pptx import Presentation


def test_ppt_file_id_download(client):
    response = client.post("/api/ppt/generate", json={"project_name": "降低/故障率", "topic": "降低设备故障率", "data_summary": "共xx行数据", "discussion_summary": {"problem": "故障率偏高", "root_causes": ["维护不及时"], "countermeasures": ["建立点检清单"], "summary": "措施可执行"}, "chart_images": []})
    assert response.status_code == 200, response.text
    result = response.json()
    assert "file_id" in result and "/" not in result["display_name"]
    download = client.get(f"/api/ppt/download/{result['file_id']}")
    assert download.status_code == 200
    assert download.content.startswith(b"PK")
    assert len(Presentation(BytesIO(download.content)).slides) == 6
    assert client.get("/api/ppt/download/../../etc").status_code in {404, 422}
