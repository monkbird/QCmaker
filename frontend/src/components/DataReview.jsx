import React, { useState } from 'react';
import { Card, Upload, Table, Form, Input, Button, message, Typography } from 'antd';
import { InboxOutlined, SaveOutlined } from '@ant-design/icons';
import apiClient from '../api/client';

const { Dragger } = Upload;
const { Title } = Typography;

const EditableCell = ({
    editing,
    dataIndex,
    title,
    inputType,
    record,
    index,
    children,
    ...restProps
}) => {
    return (
        <td {...restProps}>
            {editing ? (
                <Form.Item
                    name={dataIndex}
                    style={{ margin: 0 }}
                    rules={[
                        {
                            required: true,
                            message: `Please Input ${title}!`,
                        },
                    ]}
                >
                    <Input />
                </Form.Item>
            ) : (
                children
            )}
        </td>
    );
};

const DataReview = ({ onDataConfirmed }) => {
    const [data, setData] = useState([]);
    const [columns, setColumns] = useState([]);
    const [loading, setLoading] = useState(false);
    const [form] = Form.useForm();
    const [editingKey, setEditingKey] = useState('');

    const isEditing = (record) => record.key === editingKey;

    const edit = (record) => {
        form.setFieldsValue({ ...record });
        setEditingKey(record.key);
    };

    const cancel = () => {
        setEditingKey('');
    };

    const save = async (key) => {
        try {
            const row = await form.validateFields();
            const newData = [...data];
            const index = newData.findIndex((item) => key === item.key);

            if (index > -1) {
                const item = newData[index];
                newData.splice(index, 1, { ...item, ...row });
                setData(newData);
                setEditingKey('');
            } else {
                newData.push(row);
                setData(newData);
                setEditingKey('');
            }
        } catch (errInfo) {
            console.log('Validate Failed:', errInfo);
        }
    };

    const handleUpload = async (options) => {
        const { file, onSuccess, onError } = options;
        const formData = new FormData();
        formData.append('file', file);

        setLoading(true);
        try {
            const res = await apiClient.post('/data/upload', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });

            const rawData = res.data.data;
            if (rawData.length > 0) {
                // Generate columns dynamically
                const cols = Object.keys(rawData[0])
                    .filter(key => key !== 'key')
                    .map(key => ({
                        title: key,
                        dataIndex: key,
                        editable: true,
                    }));

                cols.push({
                    title: '操作',
                    dataIndex: 'operation',
                    render: (_, record) => {
                        const editable = isEditing(record);
                        return editable ? (
                            <span>
                                <Typography.Link onClick={() => save(record.key)} style={{ marginRight: 8 }}>
                                    保存
                                </Typography.Link>
                                <Typography.Link onClick={cancel}>
                                    取消
                                </Typography.Link>
                            </span>
                        ) : (
                            <Typography.Link disabled={editingKey !== ''} onClick={() => edit(record)}>
                                编辑
                            </Typography.Link>
                        );
                    },
                });

                setColumns(cols);
                setData(rawData);
                message.success(`${file.name} 上传并清洗成功。`);
                onSuccess("ok");
            }
        } catch (err) {
            message.error(`${file.name} 上传失败。`);
            onError(err);
        } finally {
            setLoading(false);
        }
    };

    const mergedColumns = columns.map((col) => {
        if (!col.editable) {
            return col;
        }
        return {
            ...col,
            onCell: (record) => ({
                record,
                inputType: 'text',
                dataIndex: col.dataIndex,
                title: col.title,
                editing: isEditing(record),
            }),
        };
    });

    return (
        <div className="flex justify-center items-center min-h-screen bg-gray-50 p-4">
            <Card title="数据清洗与预览 (Data Cleaning & Preview)" className="w-full max-w-5xl shadow-lg">
                <div className="mb-6">
                    <Dragger customRequest={handleUpload} showUploadList={false}>
                        <p className="ant-upload-drag-icon">
                            <InboxOutlined />
                        </p>
                        <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
                        <p className="ant-upload-hint">
                            支持 CSV 或 Excel 文件。系统将自动清洗数据。
                        </p>
                    </Dragger>
                </div>

                {data.length > 0 && (
                    <>
                        <Form form={form} component={false}>
                            <Table
                                components={{
                                    body: {
                                        cell: EditableCell,
                                    },
                                }}
                                bordered
                                dataSource={data}
                                columns={mergedColumns}
                                rowClassName="editable-row"
                                pagination={{
                                    onChange: cancel,
                                }}
                                scroll={{ x: true }}
                            />
                        </Form>
                        <div className="mt-4 flex justify-end">
                            <Button type="primary" size="large" onClick={() => onDataConfirmed(data)}>
                                确认数据并继续
                            </Button>
                        </div>
                    </>
                )}
            </Card>
        </div>
    );
};

export default DataReview;
