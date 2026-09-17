from __future__ import annotations
import hashlib
from dataclasses import dataclass

@dataclass(frozen=True)
class ChapterPathItem:
    chapter_id: str
    slug: str
    title: str
    purpose: str
    expected_conclusion: str = ''
    analysis_methods: tuple[str, ...] = ()
    next_input: str = ''
    standard_basis: str = ''

# Baseline: T/CAQ 10201-2020 4.1.2–4.1.12; richer deliverables are user preferences.
_GUIDANCE = {
    'overview': ('说明小组、人员分工和活动安排，未知实名与注册信息保留待填', '活动范围、职责、计划；不替代选题理由', ('成员职责表','活动计划表'), '课题适用对象与组织边界'),
    'select_topic': ('围绕用户已有意向，用当前指标与有来源的标准、同行或组织历史最佳水平作同口径比较，量化差距并说明选题必要性；没有实据时可拟模拟对标数据并标注。不得提前转向原因、对策或要求重新选方向', '明确课题名称、选题理由、现状/对标/差值/来源比较表及结论', ('差距比较表','基线与对标柱状图'), '选定课题、核心指标及单位、基线、对标依据、调查范围'),
    'current_situation': ('课题选定后调查不良表现，按大方面分层统计频次、比例和累计比例，定位影响最大的症结。此处不是细化人机料法环末端原因', '调查对象、时期、样本口径、分层统计表、排列图及明确的最大症结与占比', ('调查表','分层法','排列图'), '最大症结及其指标、频次/分母/占比，基线及目标测算输入'),
    'set_goal': ('目标与课题一致；依据对标、组织历史最佳水平或症结预期解决程度给测算过程。频次占比不直接等于产量提升比例，使用贡献比例须解释关系和假设；自定目标无需独立目标可行性论证章', '基线、目标值、单位、时限/统计期；依据与算式；简洁明确的目标陈述', ('目标依据表','基线与目标对比图'), '固定目标与口径、最大症结、预期改善程度'),
    'feasibility': ('仅指令性目标使用：依据同行先进、组织历史最佳、现状症结论证目标可达，明确要解决的症结与实现路径', '目标可行性、最大症结、依据与限制', ('现状分层表','目标测算表'), '固定目标、最大症结与实现条件'),
    'cause_analysis': ('严格针对前章最大症结展开因果链。按用户偏好从人、机、料、法、环五方面逐层细化，每方面通常1至3项具体、可验证、可采取措施的末端因素，必要时补测量维度。禁止只写管理不到位、意识不强等大词；此阶段不能直接判要因。五方面与数量是用户模板偏好而非标准硬规定', '中心症结→维度→中间原因→末端因素的因果图/原因树，以及带编号的完整末端因素清单', ('原因树','末端因素表'), '唯一最大症结、每个末端因素编号及因果路径'),
    'cause_confirmation': ('逐一对应原因分析的全部末端因素，识别能力范围外因素。先做确认计划表：末端因素/确认内容/方法/影响程度指标/确认标准及依据/负责人/时间；再按因素逐项展开实施：设计对照、对象样本、控制条件、实测或模拟数据表、图、影响程度计算、按预设判据判要因或非要因。确认的是对最大症结的影响程度，不是只看因素是否存在或是否合格；不预设结论、不先做对策再倒推原因。最后必须独立给要因确认汇总表，归档要因', '全部末端因素逐项确认记录+数据图表+影响程度判定；要因/非要因/待确认汇总及已确认要因列表', ('要因确认计划表','逐项对照数据表','影响程度对比图','要因确认汇总表'), '已确认要因及编号、影响程度、证据、未确认项'),
    'countermeasure': ('只围绕确认的要因制定5W1H对策表：要因/对策/简明可测目标/分点措施/地点/时间/负责人。措施必须写具体操作、设备参数、顺序及检查办法，可直接交现场执行；不以加强管理、提高意识代替措施。必要时比较多种对策', '每项要因对应的可执行对策表，措施逐项编号，目标与验收口径明确', ('方案比较表','5W1H对策表'), '编号对策与编号措施、局部目标、验收方法'),
    'implementation': ('严格按照对策表每项分点措施依次展开实施，写操作对象、步骤、参数、责任/时间和现场记录。每项对策完成后给数据表与图，对比其局部目标；未达目标写调整及复查。必要时补安全、环境、质量、成本等负面影响验证，不编造检测报告', '逐项实施叙述、对应数据表/图、局部效果结论和可选照片说明；模拟过程明确标注', ('实施过程表','对策目标与结果对比图','调整复查表'), '每项对策实施结果、最终效果检查的对象和统计期'),
    'effect_check': ('同时检查课题总目标与最大症结：实施前/目标/实施后三组指标数据图表，以及症结前后频次或比例变化；统一分母、观察期、单位，不能用样本量变化制造改善。给计算与达标结论，照片可辅助不能替代数据', '课题达标对比表与图+最大症结改善对比表与图+改善幅度、限制和必要的效益分析', ('前后对比表','目标达成柱状图','症结变化图'), '有效措施、达标情况、需要持续观察的症结指标'),
    'standardize': ('将已证明有效措施转化为作业标准/制度及批准状态，围绕最大症结设置持续监测。给多个后续观察期数据和趋势图，按明确容许波动说明有无反弹；未经过巩固期只能写计划或模拟，不能冒称已巩固', '标准化措施表、批准/执行状态、巩固期跟踪表与趋势结论', ('巩固措施表','跟踪数据表','趋势图'), '稳定性结论、保留的问题与后续改进方向'),
    'summary': ('按专业技术、管理方法、成员素质等方面简洁总结收获与不足，用表格呈现；下一步研究方向从本次不足或尚未解决问题提出，不重复全篇，不无依据保证未来效果', '收获与不足表，下一步方向及理由', ('总结对照表',), '下一轮拟研究方向'),
}

_SELF_DEFINED = [('overview','小组概况'),('select_topic','选择课题'),('current_situation','现状调查'),('set_goal','设定目标'),('cause_analysis','原因分析'),('cause_confirmation','要因确认'),('countermeasure','制定对策'),('implementation','对策实施'),('effect_check','效果检查'),('standardize','巩固措施'),('summary','总结和下一步打算')]
_DIRECTIVE = [('overview','小组概况'),('select_topic','选择课题'),('set_goal','设定目标'),('feasibility','目标可行性论证'),('cause_analysis','原因分析'),('cause_confirmation','要因确认'),('countermeasure','制定对策'),('implementation','对策实施'),('effect_check','效果检查'),('standardize','巩固措施'),('summary','总结和下一步打算')]

def build_chapter_id(path_version: str, objective_source: str, slug: str) -> str:
    return 'ch_' + hashlib.sha1(f'{path_version}|{objective_source}|{slug}'.encode()).hexdigest()[:12]

def chapter_path(topic_type: str='problem_solving', objective_source: str='self_defined', path_version: str='T/CAQ 10201-2020') -> list[ChapterPathItem]:
    if topic_type == 'innovation':
        raise ValueError('创新型路径尚未核定，不能自动生成')
    items = _DIRECTIVE if objective_source == 'directive' else _SELF_DEFINED
    clauses = {'select_topic':'4.1.2（PDF第10页）','current_situation':'4.1.3（PDF第10–11页）','set_goal':'4.1.4（PDF第11页）','feasibility':'4.1.5（PDF第11页，仅指令性目标）','cause_analysis':'4.1.6（PDF第11页）','cause_confirmation':'4.1.7（PDF第11–12页）','countermeasure':'4.1.8（PDF第12页）','implementation':'4.1.9（PDF第12页）','effect_check':'4.1.10（PDF第12页）','standardize':'4.1.11（PDF第12页）','summary':'4.1.12（PDF第12页）'}
    return [ChapterPathItem(build_chapter_id(path_version, objective_source, slug), slug, title, *_GUIDANCE[slug], f'T/CAQ 10201-2020 {clauses[slug]}' if slug in clauses else '项目组织信息，不作为问题解决流程的独立标准步骤') for slug,title in items]
