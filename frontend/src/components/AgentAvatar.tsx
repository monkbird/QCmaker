import { Avatar } from 'antd'
import { AuditOutlined, BarChartOutlined, EditOutlined, ExperimentOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import type { AgentRole } from '../types/discussion'
const config:Record<AgentRole,{label:string;color:string;icon:React.ReactNode}>={moderator:{label:'主持人',color:'#164e63',icon:<AuditOutlined/>},researcher:{label:'研究员',color:'#0f766e',icon:<ExperimentOutlined/>},analyst:{label:'分析师',color:'#1d4ed8',icon:<BarChartOutlined/>},critic:{label:'评审员',color:'#b45309',icon:<SafetyCertificateOutlined/>},writer:{label:'撰稿人',color:'#7c3aed',icon:<EditOutlined/>}}
export const agentMeta=(role:AgentRole)=>config[role]
export function AgentAvatar({role}:{role:AgentRole}){const item=config[role];return <Avatar style={{background:item.color}} icon={item.icon}/>} 

