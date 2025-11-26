import React, { useState, useEffect, useRef } from 'react';
import { Card, List, Avatar, Input, Button, Tag, Typography } from 'antd';
import { UserOutlined, RobotOutlined, SearchOutlined, BarChartOutlined, FormOutlined, SafetyCertificateOutlined } from '@ant-design/icons';

const { Text } = Typography;

const AGENT_CONFIG = {
    moderator: { name: '主持人', color: '#f50', icon: <SafetyCertificateOutlined /> },
    researcher: { name: '研究员', color: '#87d068', icon: <SearchOutlined /> },
    analyst: { name: '数据分析师', color: '#108ee9', icon: <BarChartOutlined /> },
    critic: { name: '反方', color: '#2db7f5', icon: <RobotOutlined /> },
    writer: { name: '撰稿人', color: '#722ed1', icon: <FormOutlined /> },
    user: { name: '用户', color: '#faad14', icon: <UserOutlined /> },
};

const DiscussionRoom = ({ onDiscussionFinished }) => {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [ws, setWs] = useState(null);
    const [connected, setConnected] = useState(false);
    const messagesEndRef = useRef(null);

    useEffect(() => {
        const socket = new WebSocket('ws://localhost:8000/api/discussion/ws');

        socket.onopen = () => {
            console.log('Connected to discussion room');
            setConnected(true);
        };

        socket.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.status === 'done') {
                // Discussion finished for this round
            } else {
                setMessages(prev => [...prev, {
                    role: data.agent,
                    content: data.content,
                    timestamp: new Date().toLocaleTimeString()
                }]);
            }
        };

        socket.onclose = () => {
            console.log('Disconnected');
            setConnected(false);
        };

        setWs(socket);

        return () => {
            socket.close();
        };
    }, []);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages]);

    const handleSend = () => {
        if (!input.trim() || !ws) return;

        // Add user message locally
        setMessages(prev => [...prev, {
            role: 'user',
            content: input,
            timestamp: new Date().toLocaleTimeString()
        }]);

        ws.send(input);
        setInput('');
    };

    return (
        <div className="flex justify-center items-center min-h-screen bg-gray-50 p-4">
            <Card title="多模型研讨室 (Multi-Model Discussion Room)" className="w-full max-w-4xl shadow-lg h-[80vh] flex flex-col">
                <div className="flex-1 overflow-y-auto p-4 mb-4 bg-gray-50 rounded-lg border border-gray-200">
                    <List
                        itemLayout="horizontal"
                        dataSource={messages}
                        renderItem={item => {
                            const config = AGENT_CONFIG[item.role] || AGENT_CONFIG.user;
                            return (
                                <List.Item className={`flex ${item.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                    <div className={`flex max-w-[80%] ${item.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                                        <Avatar
                                            style={{ backgroundColor: config.color }}
                                            icon={config.icon}
                                            className={`flex-shrink-0 ${item.role === 'user' ? 'ml-2' : 'mr-2'}`}
                                        />
                                        <div className="flex flex-col">
                                            <span className={`text-xs text-gray-400 mb-1 ${item.role === 'user' ? 'text-right' : 'text-left'}`}>
                                                {config.name} • {item.timestamp}
                                            </span>
                                            <div className={`p-3 rounded-lg ${item.role === 'user' ? 'bg-blue-100' : 'bg-white border border-gray-200'}`}>
                                                <Text className="whitespace-pre-wrap">{item.content}</Text>
                                            </div>
                                        </div>
                                    </div>
                                </List.Item>
                            );
                        }}
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
                        placeholder="输入你的指令或观点..."
                        autoSize={{ minRows: 1, maxRows: 4 }}
                        disabled={!connected}
                    />
                    <Button
                        type="primary"
                        onClick={handleSend}
                        disabled={!connected}
                        className="h-auto"
                    >
                        发送
                    </Button>
                    <Button onClick={onDiscussionFinished}>
                        结束研讨
                    </Button>
                </div>
            </Card>
        </div>
    );
};

export default DiscussionRoom;
