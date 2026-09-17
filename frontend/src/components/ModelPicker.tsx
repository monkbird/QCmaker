import { Select } from 'antd';
import { useState } from 'react';

/** Keep the selected ID separate from the query so an old ID cannot hide new models. */
export function ModelPicker({ label, value, models, disabled, placeholder, onChange }: {
  label: string;
  value: string;
  models: string[];
  disabled?: boolean;
  placeholder?: string;
  onChange: (model: string) => void;
}) {
  const [query, setQuery] = useState('');
  const typed = query.trim();
  const options = models.filter(model => model.toLowerCase().includes(typed.toLowerCase()))
    .map(model => ({ value: model, label: model }));
  if (typed && !models.includes(typed)) options.push({ value: typed, label: `使用自定义模型：${typed}` });
  return <Select
    aria-label={label}
    showSearch
    disabled={disabled}
    value={value || undefined}
    searchValue={query}
    onSearch={setQuery}
    onOpenChange={() => setQuery('')}
    filterOption={false}
    options={options}
    placeholder={placeholder ?? '选择或输入模型 ID'}
    notFoundContent="请先获取模型，或输入模型 ID 后选择"
    onChange={model => { setQuery(''); onChange(model); }}
  />;
}
