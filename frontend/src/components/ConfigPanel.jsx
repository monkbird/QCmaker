import React, { useState, useEffect } from 'react';
import { Card, Form, Input, Button, Switch, InputNumber, message, Divider, Alert } from 'antd';
import { CheckCircleOutlined, SyncOutlined, ApiOutlined } from '@ant-design/icons';
import apiClient from '../api/client';

const ConfigPanel = ({ onConfigComplete }) => {
    const [form] = Form.useForm();
    const [loading, setLoading] = useState(false);
    const [checking, setChecking] = useState(false);
    const [useLocalLLM, setUseLocalLLM] = useState(false);

    useEffect(() => {
        fetchConfig();
    }, []);

    const fetchConfig = async () => {
        try {
            const res = await apiClient.get('/config/');
            form.setFieldsValue({
                openai_base_url: res.data.openai_base_url,
                openai_api_key: res.data.openai_api_key,
                use_local_llm: res.data.use_local_llm,
                local_llm_url: res.data.local_llm_url,
                tavily_api_key: res.data.tavily_api_key,
                max_budget: res.data.max_budget,
            });
            setUseLocalLLM(res.data.use_local_llm);
        } catch (error) {
            message.error('Failed to load configuration');
        }
    };

    const onFinish = async (values) => {
        setLoading(true);
        try {
            await apiClient.post('/config/update', values);
            message.success('配置已保存');
            if (onConfigComplete) onConfigComplete();
        } catch (error) {
            message.error('保存配置失败');
        } finally {
            setLoading(false);
        }
    };

    const checkConnectivity = async () => {
        setChecking(true);
        try {
            const values = form.getFieldsValue();
            const baseUrl = values.use_local_llm ? values.local_llm_url : values.openai_base_url;
            const apiKey = values.openai_api_key || "dummy";

            await apiClient.post('/config/check-connectivity', {
                base_url: baseUrl,
                api_key: apiKey,
                model: values.use_local_llm ? "llama3" : "gpt-3.5-turbo"
            });
            message.success('连接成功！');
        } catch (error) {
            message.error('连接失败，请检查设置。');
        } finally {
            setChecking(false);
        }
    };

    return (
        <div className="flex justify-center items-center min-h-screen bg-gray-50 p-4">
            <Card title="系统配置 (System Configuration)" className="w-full max-w-md shadow-lg">
                <Alert
                    message="API 优先策略"
                    description="本系统不内置大模型，请配置您的 API Key 或本地 Ollama 地址。"
                    type="info"
                    showIcon
                    className="mb-6"
                />

                <Form
                    form={form}
                    layout="vertical"
                    onFinish={onFinish}
                    initialValues={{
                        use_local_llm: false,
                        local_llm_url: 'http://localhost:11434/v1',
                        max_budget: 5.0
                    }}
                >
                    <Form.Item label="使用本地 LLM (Ollama)" name="use_local_llm" valuePropName="checked">
                        <Switch checkedChildren="开启" unCheckedChildren="关闭" onChange={setUseLocalLLM} />
                    </Form.Item>

                    <Form.Item
                        noStyle
                        shouldUpdate={(prevValues, currentValues) => prevValues.use_local_llm !== currentValues.use_local_llm}
                    >
                        {({ getFieldValue }) =>
                            getFieldValue('use_local_llm') ? (
                                <Form.Item
                                    label="本地 LLM URL"
                                    name="local_llm_url"
                                    rules={[{ required: true, message: '请输入本地 LLM URL' }]}
                                >
                                    <Input placeholder="http://localhost:11434/v1" />
                                </Form.Item>
                            ) : (
                                <>
                                    <Form.Item
                                        label="OpenAI API Key"
                                        name="openai_api_key"
                                        rules={[{ required: true, message: '请输入 OpenAI API Key' }]}
                                    >
                                        <Input.Password placeholder="sk-..." />
                                    </Form.Item>
                                    <Form.Item label="OpenAI Base URL" name="openai_base_url">
                                        <Input placeholder="https://api.openai.com/v1" />
                                    </Form.Item>
                                </>
                            )
                        }
                    </Form.Item>

                    <Form.Item label="Tavily API Key (搜索功能)" name="tavily_api_key">
                        <Input.Password placeholder="tvly-..." />
                    </Form.Item>

                    <Form.Item label="最大预算 (USD)" name="max_budget">
                        <InputNumber min={0.1} step={0.1} prefix="$" style={{ width: '100%' }} />
                    </Form.Item>

                    <Form.Item>
                        <div className="flex gap-2">
                            <Button type="default" onClick={checkConnectivity} loading={checking} icon={<ApiOutlined />}>
                                检查连接
                            </Button>
                            <Button type="primary" htmlType="submit" loading={loading} block>
                                保存并继续
                            </Button>
                        </div>
                    </Form.Item>
                </Form>
            </Card>
        </div>
    );
};

export default ConfigPanel;
