import { Alert, Button } from 'antd'
import { Component, type ErrorInfo, type ReactNode } from 'react'
export class ErrorBoundary extends Component<{children:ReactNode},{failed:boolean}>{state={failed:false};static getDerivedStateFromError(){return{failed:true}}componentDidCatch(error:Error,info:ErrorInfo){console.error(error,info)}render(){return this.state.failed?<div className="fatal-state"><Alert type="error" showIcon message="页面加载失败" description="本地状态已保留，请刷新后重试。"/><Button onClick={()=>location.reload()}>刷新页面</Button></div>:this.props.children}}

