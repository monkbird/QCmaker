import React, { useState } from 'react';
import { Card, Select, Button, message, Alert } from 'antd';
import ReactECharts from 'echarts-for-react';
import { BarChartOutlined, LineChartOutlined, PieChartOutlined } from '@ant-design/icons';
import apiClient from '../api/client';

const { Option } = Select;

const VisualizationPanel = ({ data, onFinished }) => {
    const [chartType, setChartType] = useState('bar');
    const [xAxis, setXAxis] = useState('');
    const [yAxis, setYAxis] = useState('');
    const [chartOption, setChartOption] = useState(null);
    const [loading, setLoading] = useState(false);
    const [errorMsg, setErrorMsg] = useState(null);

    // Extract columns from data keys
    const columns = data && data.length > 0 ? Object.keys(data[0]).filter(k => k !== 'key') : [];

    const generateChart = async () => {
        if (!xAxis || !yAxis) {
            message.warning('请选择 X 轴和 Y 轴');
            return;
        }

        setLoading(true);
        setErrorMsg(null);
        setChartOption(null);

        try {
            const res = await apiClient.post('/visualization/generate', {
                chart_type: chartType,
                data: data,
                x_axis: xAxis,
                y_axis: yAxis
            });

            if (res.data.error) {
                setErrorMsg(res.data.message);
                if (res.data.recommendation) {
                    message.info(`建议：尝试使用 ${res.data.recommendation} 图表。`);
                }
            } else {
                setChartOption(res.data);
            }
        } catch (error) {
            message.error('生成图表失败');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex justify-center items-center min-h-screen bg-gray-50 p-4">
            <Card title="可视化与决策 (Visualization & Decision)" className="w-full max-w-5xl shadow-lg">
                <div className="flex gap-4 mb-6 flex-wrap">
                    <Select
                        value={chartType}
                        onChange={setChartType}
                        style={{ width: 120 }}
                    >
                        <Option value="bar"><BarChartOutlined /> 柱状图</Option>
                        <Option value="line"><LineChartOutlined /> 折线图</Option>
                        <Option value="pie"><PieChartOutlined /> 饼图</Option>
                    </Select>

                    <Select
                        placeholder="选择 X 轴"
                        style={{ width: 150 }}
                        onChange={setXAxis}
                        value={xAxis}
                    >
                        {columns.map(col => <Option key={col} value={col}>{col}</Option>)}
                    </Select>

                    <Select
                        placeholder="选择 Y 轴"
                        style={{ width: 150 }}
                        onChange={setYAxis}
                        value={yAxis}
                    >
                        {columns.map(col => <Option key={col} value={col}>{col}</Option>)}
                    </Select>

                    <Button type="primary" onClick={generateChart} loading={loading}>
                        生成图表
                    </Button>
                </div>

                {errorMsg && (
                    <Alert
                        message="图表拦截器提示"
                        description={errorMsg}
                        type="warning"
                        showIcon
                        className="mb-4"
                    />
                )}

                <div className="h-[400px] w-full border border-gray-100 rounded-lg p-4 bg-white flex justify-center items-center">
                    {chartOption ? (
                        <ReactECharts option={chartOption} style={{ height: '100%', width: '100%' }} />
                    ) : (
                        <span className="text-gray-400">图表预览区域</span>
                    )}
                </div>

                <div className="mt-6 flex justify-end">
                    <Button type="primary" onClick={onFinished}>
                        确认并生成报告
                    </Button>
                </div>
            </Card>
        </div>
    );
};

export default VisualizationPanel;
