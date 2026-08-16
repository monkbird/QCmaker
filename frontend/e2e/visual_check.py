from pathlib import Path
from playwright.sync_api import sync_playwright

output = Path(__file__).resolve().parents[1] / "test-results"
output.mkdir(exist_ok=True)
errors: list[str] = []
failed_responses: list[str] = []
ready_config = {"llm_provider":"openai","openai_base_url":"https://api.openai.com/v1","openai_model":"gpt-4o-mini","use_local_llm":False,"local_llm_url":"http://localhost:11434/v1","local_llm_model":"llama3","max_budget_usd":5,"has_openai_key":True,"has_tavily_key":False,"status":"ready","config_revision":1}
usage = {"budget_usd":"5","reserved_usd":"0","known_cost_usd":"0.12","remaining_usd":"4.88","unknown_cost":False,"usage_by_model":[]}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width":1440,"height":1000}, device_scale_factor=1)
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("response", lambda response: failed_responses.append(f"{response.status} {response.url}") if response.status >= 400 else None)
    page.route("**/api/config/usage", lambda route: route.fulfill(json=usage))
    page.route("**/api/config/", lambda route: route.fulfill(json=ready_config))
    page.goto("http://127.0.0.1:5173/config")
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="模型与预算").wait_for()
    page.screenshot(path=output / "config.png", full_page=True)
    page.goto("http://127.0.0.1:5173/topic")
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="界定课题").wait_for()
    page.screenshot(path=output / "topic.png", full_page=True)
    page.evaluate("""sessionStorage.setItem('qcmaker_wizard', JSON.stringify({currentProjectId:crypto.randomUUID(),topic:'降低排涝站设备故障率',dataRef:null,datasetRevision:null,dataConfirmed:false,lastEventSeq:0,currentPath:'/data'}))""")
    page.goto("http://127.0.0.1:5173/data")
    page.wait_for_load_state("networkidle")
    page.get_by_role("heading", name="检测与确认数据").wait_for()
    page.screenshot(path=output / "data.png", full_page=True)
    oversized = page.locator("button").evaluate_all("els => els.map(e => ({text:(e.textContent||'').trim(),width:e.getBoundingClientRect().width})).filter(x => x.text.length > 0 && x.text.length <= 4 && x.width > 160)")
    assert not oversized, f"oversized short buttons: {oversized}"
    assert not errors, f"console errors: {errors}; failed responses: {failed_responses}"
    print({"screenshots": 3, "oversized_short_buttons": oversized, "console_errors": errors, "failed_responses": failed_responses})
    browser.close()
