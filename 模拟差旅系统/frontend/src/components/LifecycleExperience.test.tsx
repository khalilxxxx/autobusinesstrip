// @vitest-environment jsdom
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  lifecycle: vi.fn(), lifecycleQuery: vi.fn(), lifecycleDetail: vi.fn(), lifecycleOptions: vi.fn(),
  lifecyclePrepare: vi.fn(), lifecycleSave: vi.fn(), lifecycleSubmit: vi.fn(),
  lifecycleAction: vi.fn(), lifecycleReceipt: vi.fn(), lifecycleCancelDraft: vi.fn(),
}));

vi.mock('../api', () => ({
  assistantApi: api,
  ApiError: class ApiError extends Error {
    status: number; code?: string; issues: unknown[];
    constructor(message: string, status: number, code?: string) {
      super(message); this.status = status; this.code = code; this.issues = [];
    }
  },
}));

import type { LifecycleDocument, LifecycleDraft, LifecycleState } from '../types';
import { ApiError } from '../api';
import { DocumentPanel } from './DocumentPanel';

const options = {
  departments: [{ id: 'D1', name: '业务部' }, { id: 'D2', name: '研发部' }],
  payerCompanies: [{ id: 'C1', name: '科技公司' }, { id: 'C2', name: '服务公司' }],
  travelTypes: [{ value: null, label: '普通差旅' }, { value: 'Y' as const, label: '短期异地办公' }],
  transports: [{ category: '火车', option: '二等座', value: '火车-二等座' }],
  cities: [
    { cityId: 'HZ', cityName: '杭州', upCityId: '', upCityName: '', countryId: 'CN', provinceId: 'ZJ', provinceName: '浙江' },
    { cityId: 'SH', cityName: '上海', upCityId: '', upCityName: '', countryId: 'CN', provinceId: 'SH', provinceName: '上海' },
    { cityId: 'BJ', cityName: '北京', upCityId: '', upCityName: '', countryId: 'CN', provinceId: 'BJ', provinceName: '北京' },
  ],
  demoOnly: true,
};

function document(overrides: Partial<LifecycleDocument> = {}): LifecycleDocument {
  return {
    applicationId: 'APP-1', applicationNo: 'DEMO-CL-001', createdAt: '2026-09-13T09:00:00+08:00',
    submittedAt: '2026-09-13T09:00:00+08:00', demoOnly: true, status: 'S004', tflag: 'D',
    documentType: 'APPLICATION', version: 3, submissionRound: 1, rootId: 'APP-1', rootNo: 'DEMO-CL-001',
    predecessorId: null, currentEffectiveId: 'APP-1', pendingChangeId: null, isEffective: true, isSuperseded: false,
    tripStart: '2026-11-20', tripEnd: '2026-11-25',
    request: { applicantId: 'EMP', departmentId: 'D1', payerCompanyId: 'C1', remark: '客户拜访', dqydbg: null,
      trips: [{ cityFrom: 'HZ', cityTo: 'SH', dateFrom: '2026-11-20', dateTo: '2026-11-20', tool: '火车-二等座' }] },
    history: [{ action: 'create', at: '2026-09-13T09:00:00+08:00', fromStatus: null, toStatus: 'S002', role: 'EMPLOYEE', submissionRound: 1 }],
    actions: {
      withdraw: { allowed: false, reason: '仅 S002 可撤回。' }, void: { allowed: true, reason: null },
      change: { allowed: true, reason: null }, resubmit: { allowed: false, reason: '仅 S005 可重提。' },
    },
    ...overrides,
  };
}

function state(documents: LifecycleDocument[] = []): LifecycleState {
  return { documents, selectedDocument: null, draft: null, lastReceipt: null,
    querySummary: { filters: { dateBasis: 'trip', temporal: 'future' }, total: documents.length, limit: 20, offset: 0 } };
}

function draft(target = document()): LifecycleDraft {
  return { id: 'draft-1', revision: 1, mode: 'change', targetId: target.applicationId,
    targetVersion: target.version, targetDocument: target, payload: structuredClone(target.request),
    original: structuredClone(target.request), differences: [], fingerprint: 'fingerprint-1' };
}

beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  api.lifecycle.mockResolvedValue(state());
  api.lifecycleOptions.mockResolvedValue({ uuid: 'O', code: 'SUCCESS', message: {}, data: options });
  api.lifecycleDetail.mockImplementation(async (_cid: string, reference: string) => ({ ...state(), selectedDocument: document({ applicationId: reference }) }));
  api.lifecycleCancelDraft.mockResolvedValue(state());
});

afterEach(cleanup);

describe('员工单据办理面板', () => {
  it('从查询列表打开详情并按后端资格撤回到 S005，员工侧没有审批按钮', async () => {
    const pending = document({ status: 'S002', version: 1, isEffective: false, currentEffectiveId: null,
      actions: { withdraw: { allowed: true, reason: null }, void: { allowed: false, reason: '当前不可作废。' },
        change: { allowed: false, reason: '当前不可变更。' }, resubmit: { allowed: false, reason: '当前不可重提。' } } });
    const withdrawn = document({ ...pending, status: 'S005', version: 2,
      history: [...pending.history, { action: 'withdraw', at: '2026-09-13T10:00:00+08:00', fromStatus: 'S002', toStatus: 'S005', role: 'EMPLOYEE', submissionRound: 1 }],
      actions: { ...pending.actions, withdraw: { allowed: false, reason: '仅 S002 可撤回。' }, resubmit: { allowed: true, reason: null } } });
    api.lifecycleQuery.mockResolvedValue(state([pending]));
    api.lifecycleDetail.mockResolvedValue({ ...state([pending]), selectedDocument: pending });
    api.lifecycleAction.mockResolvedValue({ ...state([withdrawn]), selectedDocument: withdrawn });

    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    const queryButton = await view.findByRole('button', { name: '查询单据' });
    expect(queryButton.hasAttribute('disabled')).toBe(false);
    fireEvent.click(queryButton);
    expect((await view.findByLabelText('单据查询与办理')).parentElement).toBe(globalThis.document.body);
    fireEvent.click(await view.findByRole('button', { name: '开始查询' }));
    fireEvent.click(await view.findByRole('button', { name: /DEMO-CL-001/ }));
    await waitFor(() => expect(api.lifecycleDetail).toHaveBeenCalled());
    await waitFor(() => expect(view.getByRole('button', { name: '撤回本次提交' }).hasAttribute('disabled')).toBe(false));
    fireEvent.click(view.getByRole('button', { name: '撤回本次提交' }));

    await waitFor(() => expect(api.lifecycleAction).toHaveBeenCalledWith('CID', expect.objectContaining({
      reference: 'APP-1', action: 'withdraw', expectedVersion: 1,
    })));
    expect((await view.findAllByText('已撤回／退回')).some((item) => item.tagName === 'SPAN')).toBe(true);
    expect(view.queryByRole('button', { name: '审批通过' })).toBeNull();
    expect(view.queryByText(/旧版|恢复旧单/)).toBeNull();
  });

  it('编辑部门公司、日期并增段，保存后展示差异和完整新安排，再用最新 revision 与 fingerprint 提交', async () => {
    const current = document(); const prepared = { ...state([current]), selectedDocument: current, draft: draft(current) };
    const savedDraft = { ...draft(current), revision: 2, fingerprint: 'fingerprint-2',
      payload: { ...current.request, departmentId: 'D2', payerCompanyId: 'C2', remark: '延期拜访', trips: [
        { ...current.request.trips[0], dateFrom: '2026-11-21', dateTo: '2026-11-21' },
        { cityFrom: 'SH', cityTo: 'BJ', dateFrom: '2026-11-23', dateTo: '2026-11-23', tool: '火车-二等座' },
      ] }, differences: [
        { field: 'departmentId', before: 'D1', after: 'D2' }, { field: 'payerCompanyId', before: 'C1', after: 'C2' },
        { field: 'trips', before: current.request.trips, after: [] },
      ] } as LifecycleDraft;
    api.lifecycle.mockResolvedValue(state([current]));
    api.lifecycleDetail.mockResolvedValue({ ...state([current]), selectedDocument: current });
    api.lifecyclePrepare.mockResolvedValue(prepared);
    api.lifecycleSave.mockResolvedValue({ ...prepared, draft: savedDraft });
    api.lifecycleSubmit.mockResolvedValue({ ...state([document({ status: 'S002', isEffective: false })]), draft: null });

    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await view.findByRole('button', { name: '查询单据' }));
    fireEvent.click(await view.findByRole('button', { name: /DEMO-CL-001/ }));
    await waitFor(() => expect(api.lifecycleDetail).toHaveBeenCalled());
    await waitFor(() => expect(view.getByRole('button', { name: '发起行程变更' }).hasAttribute('disabled')).toBe(false));
    fireEvent.click(view.getByRole('button', { name: '发起行程变更' }));
    expect((await view.findByRole('dialog', { name: '编辑行程变更' })).parentElement?.parentElement).toBe(globalThis.document.body);
    fireEvent.change(await view.findByLabelText('部门'), { target: { value: 'D2' } });
    fireEvent.change(view.getByLabelText('付款公司'), { target: { value: 'C2' } });
    fireEvent.change(view.getByLabelText('出差事由'), { target: { value: '延期拜访' } });
    fireEvent.change(view.getByLabelText('第 1 段出发日期'), { target: { value: '2026-11-21' } });
    fireEvent.change(view.getByLabelText('第 1 段到达日期'), { target: { value: '2026-11-21' } });
    fireEvent.click(view.getByRole('button', { name: '添加行程段' }));
    fireEvent.change(view.getByLabelText('第 2 段出发城市'), { target: { value: 'SH' } });
    fireEvent.change(view.getByLabelText('第 2 段到达城市'), { target: { value: 'BJ' } });
    fireEvent.change(view.getByLabelText('第 2 段出发日期'), { target: { value: '2026-11-23' } });
    fireEvent.change(view.getByLabelText('第 2 段到达日期'), { target: { value: '2026-11-23' } });
    fireEvent.click(view.getByRole('button', { name: '保存并查看差异' }));

    await waitFor(() => expect(api.lifecycleSave).toHaveBeenCalledWith('CID', expect.objectContaining({
      draftId: 'draft-1', revision: 1, payload: expect.objectContaining({ departmentId: 'D2', payerCompanyId: 'C2' }),
    })));
    expect(await view.findByText('业务部 → 研发部')).not.toBeNull();
    expect(view.getByText((_, item) => item?.tagName === 'STRONG' && item.textContent?.replace(/\s+/g, '') === '上海北京')).not.toBeNull();
    fireEvent.click(view.getByRole('button', { name: '确认提交变更' }));
    await waitFor(() => expect(api.lifecycleSubmit).toHaveBeenCalledWith('CID', expect.objectContaining({
      draftId: 'draft-1', revision: 2, fingerprint: 'fingerprint-2', clientRequestId: expect.any(String),
    })));
  });

  it('后台刷新不覆盖未保存编辑，目标版本变化后禁止直接保存或提交', async () => {
    const target = document(); const initial = { ...state([target]), selectedDocument: target, draft: draft(target) };
    api.lifecycle.mockResolvedValue(initial);
    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await view.findByRole('button', { name: '继续编辑变更' }));
    fireEvent.change(view.getByLabelText('出差事由'), { target: { value: '尚未保存的本地说明' } });

    const changed = document({ version: 4, status: 'S003' });
    api.lifecycle.mockResolvedValue({ ...initial, draft: { ...draft(target), targetDocument: changed } });
    view.rerender(<DocumentPanel conversationId="CID" refreshToken={1} />);

    await waitFor(() => expect(api.lifecycle).toHaveBeenCalledTimes(2));
    expect((view.getByLabelText('出差事由') as HTMLTextAreaElement).value).toBe('尚未保存的本地说明');
    expect(view.getByText(/原目标已变化/)).not.toBeNull();
    expect(view.getByRole('button', { name: '保存并查看差异' }).hasAttribute('disabled')).toBe(true);
  });

  it('网络未知结果持久化原请求号，继续办理先查回执再沿用同号同步', async () => {
    const pending = document({ status: 'S002', version: 1, isEffective: false,
      actions: { withdraw: { allowed: true, reason: null }, void: { allowed: false, reason: '不可作废' },
        change: { allowed: false, reason: '不可变更' }, resubmit: { allowed: false, reason: '不可重提' } } });
    api.lifecycle.mockResolvedValue({ ...state([pending]), selectedDocument: pending });
    api.lifecycleAction.mockRejectedValueOnce(new ApiError('断网', 0, 'NETWORK_ERROR'))
      .mockResolvedValueOnce({ ...state([document({ status: 'S005' })]), draft: null });
    api.lifecycleReceipt.mockRejectedValue(new ApiError('未找到', 404, 'RECEIPT_NOT_FOUND'));

    const first = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await first.findByRole('button', { name: '查询单据' }));
    fireEvent.click(await first.findByRole('button', { name: '撤回本次提交' }));
    expect(await first.findByText(/结果待核对/)).not.toBeNull();
    const originalId = JSON.parse(localStorage.getItem('travelLifecyclePendingOperation') || '{}').body.clientRequestId;
    first.unmount();

    const second = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await second.findByRole('button', { name: '查询办理结果' }));
    await waitFor(() => expect(api.lifecycleAction).toHaveBeenCalledTimes(2));
    expect(api.lifecycleReceipt.mock.invocationCallOrder[0]).toBeLessThan(api.lifecycleAction.mock.invocationCallOrder[1]);
    expect(api.lifecycleAction.mock.calls[1][1].clientRequestId).toBe(originalId);
  });
});
