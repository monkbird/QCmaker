import React, { useState, useRef, useEffect } from 'react';
import { Card, Input, Button, List, Avatar, Typography, Spin, message } from 'antd';
import { SendOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';
import apiClient from '../api/client';

const { Text } = Typography;

const TopicChat = ({ onTopicSelected }) => {
    const [messages, setMessages] = useState([
        { role: 'assistant', content: '你好！我是你的 QC 选题顾问。请告诉我你初步的想法，或者你想解决什么问题？（例如：“最近车间里那个机器老是坏”）' }
    ]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const handleSend = async () => {
        if (!input.trim()) return;

        const userMsg = { role: 'user', content: input };
        setMessages(prev => [...prev, userMsg]);
        setInput('');
        setLoading(true);

        try {
            // Construct history string
            const history = messages.map(m => `${m.role}: ${m.content}`).join('\n');

            const res = await apiClient.post('/topic/chat', {
                message: userMsg.content,
                history: history
            });

            const aiMsg = { role: 'assistant', content: res.data.response };
            setMessages(prev => [...prev, aiMsg]);
        } catch (error) {
            message.error('获取 AI 响应失败');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex justify-center items-center min-h-screen bg-gray-50 p-4">
            <Card title="QC 选题顾问 (Topic Consultant)" className="w-full max-w-3xl shadow-lg h-[80vh] flex flex-col">
                <div className="flex-1 overflow-y-auto p-4 mb-4 bg-gray-50 rounded-lg border border-gray-200">
                    <List
                        itemLayout="horizontal"
                        dataSource={messages}
                        renderItem={item => (
                            <List.Item className={`flex ${item.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                <div className={`flex max-w-[80%] ${item.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                                    <Avatar
                                        icon={item.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                                        className={`flex-shrink-0 ${item.role === 'user' ? 'ml-2 bg-blue-500' : 'mr-2 bg-green-500'}`}
                                    />
                                    <div className={`p-3 rounded-lg ${item.role === 'user' ? 'bg-blue-100' : 'bg-white border border-gray-200'}`}>
                                        <Text className="whitespace-pre-wrap">{item.content}</Text>
                                    </div>
                                </div>
                            </List.Item>
                        )}
                    />
                    <div ref={messagesEndRef} />
                </div>

                <div className="flex gap-2">
                    <Input.TextArea
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        onPressEnter={e => {
                            if (!e.shiftKey) {
                                e.preventDefault();
                                handleSend();
                            }
                        }}
                        placeholder="输入你的想法..."
                        autoSize={{ minRows: 1, maxRows: 4 }}
                        disabled={loading}
                    />
                    <Button
                        type="primary"
                        icon={loading ? <Spin /> : <SendOutlined />}
                        onClick={handleSend}
                        disabled={loading}
                        className="h-auto"
                    >
                        发送
                    </Button>
                    <Button
                        onClick={() => onTopicSelected(input || "默认选题")}
                        className="h-auto"
                    >
                        确认选题
                    </Button>
                </div>
            </Card>
        </div>
    );
};

export default TopicChat;
