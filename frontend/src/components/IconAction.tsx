import { Button, Tooltip } from 'antd'
import type { ReactNode } from 'react'
export function IconAction({label,icon,onClick,danger=false,disabled=false}:{label:string;icon:ReactNode;onClick?:()=>void;danger?:boolean;disabled?:boolean}){return <Tooltip title={label}><Button className="icon-action" type="text" danger={danger} icon={icon} aria-label={label} onClick={onClick} disabled={disabled}/></Tooltip>}

