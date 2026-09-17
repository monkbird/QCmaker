import {Alert,Progress,Tag} from 'antd'; import type {ParseManifest} from '../../types/materials'
export function ParseCoveragePanel({manifest}:{manifest:ParseManifest}){
 const pct=manifest.units_total?Math.round(manifest.units_completed/manifest.units_total*100):0
 return <section className="parse-coverage"><Progress percent={pct}/><Tag>{manifest.units_completed} / {manifest.units_total}</Tag>
 <p>读取覆盖情况与人工核验分别记录。OCR 和直接提取的结果均需对照原文。</p>
 {!manifest.coverage_complete&&<Alert type="warning" showIcon message="仍有未完整解析内容，请核验标记区域"/>}
 {manifest.units.map(unit=><details key={unit.unit_id}><summary>{unit.locator} · {unit.status==='parsed'?'已解析':unit.status==='verified_blank'?'空白页已记录':unit.status==='failed'?'解析失败':'待处理'}</summary>
 {unit.issues.map((issue,index)=><Alert key={index} type="warning" message={issue}/>)}
 {unit.regions.map(region=><div key={region.region_id} style={{margin:'12px 0'}}><Tag>{region.region_id}</Tag><Tag>{region.method}</Tag><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{region.text}{region.table_cells.length?JSON.stringify(region.table_cells,null,2):''}</pre></div>)}
 </details>)}
 {manifest.next_cursor&&<Alert type="info" message="当前为分页展示，完整内容仍保留在资料版本中。"/>}
 </section>
}
