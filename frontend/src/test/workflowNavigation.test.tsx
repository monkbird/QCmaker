import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import { WizardLayout } from '../layouts/WizardLayout';
vi.mock('../context/WizardContext',()=>({useWizard:()=>({state:{currentProjectId:'p',topic:'课题'},reset:vi.fn(),openProject:vi.fn()})}));
vi.mock('../storage/db',()=>({listSavedProjects:async()=>[]}));
describe('chapter-first workflow',()=>{
  it('keeps three main stages separate from optional tools without fake completion',()=>{
    render(<MemoryRouter initialEntries={['/ppt']}><WizardLayout/></MemoryRouter>);
    const stages=screen.getByRole('navigation',{name:'课题步骤'});
    expect(within(stages).getAllByRole('button')).toHaveLength(3);
    expect(within(stages).getByRole('button',{name:/逐章编写/})).not.toHaveClass('is-complete');
    expect(within(stages).getByRole('button',{name:/成果检查/})).toHaveAttribute('aria-current','step');
    expect(within(screen.getByRole('navigation',{name:'辅助工具'})).getByRole('button',{name:/资料与数据/})).toBeInTheDocument();
  });
});
