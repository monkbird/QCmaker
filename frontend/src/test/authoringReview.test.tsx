import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ChapterReview } from '../components/authoring/ChapterReview';
import type { ChapterSnapshot } from '../types/authoring';

const snapshot: ChapterSnapshot = { project_id:'p', chapter_id:'c1', revision:0, path_version:'2020', content_blocks:[], metrics:[], evidence_refs:[], content_state:'empty', review_state:'pending', evidence_state:'missing', stale:false, stale_reasons:[] };
describe('ChapterReview',()=>{
 it('allows editing and emits a manual draft without conflating review and evidence',async()=>{const user=userEvent.setup();const save=vi.fn();const review=vi.fn();render(<ChapterReview snapshot={snapshot} onGenerate={vi.fn()} onSave={save} onReview={review} onVerify={vi.fn()}/>);await user.type(screen.getByLabelText('章节正文'),'现场问题草稿');await user.click(screen.getByText('保存草稿'));expect(save).toHaveBeenCalledWith('现场问题草稿',[],[]);await user.click(screen.getByRole('combobox',{name:'审核状态'}));await user.click(await screen.findByText('作者接受'));expect(review).toHaveBeenCalledWith('approved','');expect(screen.getByText('证据：missing')).toBeInTheDocument()});
 it('keeps evidence verification as a separate action',async()=>{const user=userEvent.setup();const verify=vi.fn();render(<ChapterReview snapshot={{...snapshot,review_state:'approved'}} onGenerate={vi.fn()} onSave={vi.fn()} onReview={vi.fn()} onVerify={verify}/>);await user.click(screen.getByText('保留待核实项继续'));expect(verify).toHaveBeenCalledWith('partial',['请补充现场确认记录']);expect(screen.getByText('审核：approved')).toBeInTheDocument()});
});
