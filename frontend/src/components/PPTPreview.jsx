import React, { useState } from 'react';
import { Card, Button, message, Result, Spin } from 'antd';
import { FilePptOutlined, DownloadOutlined, CheckCircleOutlined } from '@ant-design/icons';
import apiClient from '../api/client';

const PPTPreview = ({ projectData }) => {
    const [loading, setLoading] = useState(false);
    const [downloadUrl, setDownloadUrl] = useState(null);
    const [filename, setFilename] = useState(null);

    const generatePPT = async () => {
        setLoading(true);
        try {
            // Mock data for demo purposes
            // In a real app, these would come from the discussion history and analysis results
            const payload = {
                project_name: "Smart QC Project",
                topic: "降低XX车间XX机器故障率",
                data_summary: "数据分析显示过去一个月的不良率为 15%。",
                discussion_summary: "团队确定了3个根本原因：温度、振动和操作员失误。",
                chart_images: [] // Would need to capture chart images from frontend
            };

            const res = await apiClient.post('/ppt/generate', payload);

            if (res.data.status === 'success') {
                setFilename(res.data.filename);
                setDownloadUrl(`http://localhost:8000/api/ppt/download/${res.data.filename}`);
                message.success('PPT 生成成功！');
            }
        } catch (error) {
            message.error('生成 PPT 失败');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex justify-center items-center min-h-screen bg-gray-50 p-4">
            <Card title="终稿生成 (Final Draft Generation)" className="w-full max-w-3xl shadow-lg text-center">
                {!downloadUrl ? (
                    <div className="py-12">
                        <FilePptOutlined style={{ fontSize: '64px', color: '#faad14', marginBottom: 24 }} />
                        <h2 className="text-xl font-bold mb-4">准备生成报告</h2>
                        <p className="text-gray-500 mb-8">
                            系统将汇总所有数据、图表和讨论记录，生成一份专业的 QC 成果报告。
                        </p>
                        <Button
                            type="primary"
                            size="large"
                            onClick={generatePPT}
                            loading={loading}
                            icon={<FilePptOutlined />}
                        >
                            生成 PPT
                        </Button>
                    </div>
                ) : (
                    <Result
                        status="success"
                        icon={<CheckCircleOutlined style={{ color: '#52c41a' }} />}
                        title="报告生成成功！"
                        subTitle={`文件: ${filename}`}
                        extra={[
                            <Button
                                type="primary"
                                key="download"
                                icon={<DownloadOutlined />}
                                size="large"
                                href={downloadUrl}
                                target="_blank"
                            >
                                下载 PPT
                            </Button>,
                            <Button key="regenerate" onClick={() => setDownloadUrl(null)}>
                                重新生成
                            </Button>,
                        ]}
                    />
                )}
            </Card>
        </div>
    );
};

export default PPTPreview;
