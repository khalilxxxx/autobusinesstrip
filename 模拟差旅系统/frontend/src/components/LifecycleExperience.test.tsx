// @vitest-environment jsdom
import { cleanup, fireEvent, render, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  lifecycle: vi.fn(), lifecycleQuery: vi.fn(), lifecycleDetail: vi.fn(), lifecycleOptions: vi.fn(),
  lifecyclePrepare: vi.fn(), lifecycleSave: vi.fn(), lifecycleSubmit: vi.fn(),
  lifecycleProposeAction: vi.fn(), lifecycleCancelAction: vi.fn(), lifecycleAction: vi.fn(), lifecycleRecover: vi.fn(), lifecycleReceipt: vi.fn(), lifecycleCancelDraft: vi.fn(),
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
import { DocumentPanel, LifecycleCards } from './DocumentPanel';

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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  api.lifecycle.mockResolvedValue(state());
  api.lifecycleOptions.mockResolvedValue({ uuid: 'O', code: 'SUCCESS', message: {}, data: options });
  api.lifecycleDetail.mockImplementation(async (_cid: string, reference: string) => ({ ...state(), selectedDocument: document({ applicationId: reference }) }));
  api.lifecycleProposeAction.mockImplementation(async (_cid, body) => {
    const current = await api.lifecycle.mock.results[api.lifecycle.mock.results.length - 1].value;
    const doc = current.documents.find((d: LifecycleDocument) => d.applicationId === body.reference) || current.selectedDocument;
    return { ...current, pendingAction: { id: 'proposal', reference: body.reference, action: body.action, targetVersion: doc.version, targetDocument: doc, reason: body.reason || null } };
  });
  api.lifecycleCancelAction.mockResolvedValue(state());
  api.lifecycleRecover.mockResolvedValue(state());
  api.lifecycleCancelDraft.mockResolvedValue(state());
});

afterEach(cleanup);

describe('语义单据卡片', () => {
  it('连续两轮查询的卡片各自展示在对应回复位置', async () => {
    const first = document(); const second = document({ applicationId: 'APP-2', applicationNo: 'DEMO-CL-002', request: { ...first.request, remark: '项目驻场' } });
    api.lifecycle.mockResolvedValue({ ...state([second]), cardGroups: [
      { id: 'g1', turnId: 't1', title: '相关差旅单据', documents: [first], total: 1 },
      { id: 'g2', turnId: 't2', title: '相关差旅单据', documents: [second], total: 1 },
    ] });
    const view = render(<DocumentPanel conversationId="CID" refreshToken={0}>
      <div data-testid="first-reply"><LifecycleCards turnId="t1" /></div>
      <div data-testid="second-reply"><LifecycleCards turnId="t2" /></div>
    </DocumentPanel>);
    await within(view.getByTestId('first-reply')).findByRole('article', { name: '差旅单据 DEMO-CL-001' });
    expect(within(view.getByTestId('first-reply')).queryByText('项目驻场')).toBeNull();
    expect(within(view.getByTestId('second-reply')).getByRole('article', { name: '差旅单据 DEMO-CL-002' })).not.toBeNull();
  });

  it('查询结果直接显示卡片且系统按钮不发起业务写入', async () => {
    api.lifecycle.mockResolvedValue(state([document()]));
    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    const card = await view.findByRole('article', { name: '差旅单据 DEMO-CL-001' });
    expect(card.textContent).toContain('客户拜访');
    expect(view.queryByLabelText('历史当前未来')).toBeNull();
    fireEvent.click(view.getByRole('button', { name: '查看系统单据' }));
    expect(api.lifecycleAction).not.toHaveBeenCalled();
  });

  it('撤回先核对目标，取消不写入，第二次确认才办理', async () => {
    const doc = document({ status: 'S002', actions: { ...document().actions, withdraw: { allowed: true, reason: null } } });
    api.lifecycle.mockResolvedValue(state([doc]));
    api.lifecycleProposeAction.mockResolvedValue({ ...state([doc]), pendingAction: {
      id: 'confirm-1', reference: doc.applicationId, action: 'withdraw', targetVersion: doc.version, targetDocument: doc, reason: null,
    } });
    api.lifecycleCancelAction.mockResolvedValue(state([doc]));
    api.lifecycleAction.mockImplementation(async (_cid, body) => ({ ...state([doc]), lastReceipt: {
      clientRequestId: body.clientRequestId, status: 'SUCCEEDED', result: { document: { ...doc, status: 'S005' } },
    } }));
    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await view.findByRole('button', { name: '撤回本次提交' }));
    expect((await view.findByRole('alertdialog', { name: '确认撤回' })).textContent).toContain('DEMO-CL-001');
    expect(api.lifecycleAction).not.toHaveBeenCalled();
    fireEvent.click(view.getByRole('button', { name: '取消' }));
    await waitFor(() => expect(view.queryByRole('alertdialog')).toBeNull());
    expect(api.lifecycleAction).not.toHaveBeenCalled();
    fireEvent.click(view.getByRole('button', { name: '撤回本次提交' }));
    fireEvent.click(await view.findByRole('button', { name: '确认撤回' }));
    await waitFor(() => expect(api.lifecycleAction).toHaveBeenCalledWith('CID', expect.objectContaining({ action: 'withdraw', expectedVersion: 3 })));
  });

  it('作废弹窗说明影响并将填写的原因传入办理记录', async () => {
    const doc = document();
    api.lifecycle.mockResolvedValue(state([doc]));
    api.lifecycleProposeAction.mockResolvedValue({ ...state([doc]), pendingAction: {
      id: 'confirm-void', reference: doc.applicationId, action: 'void', targetVersion: doc.version, targetDocument: doc, reason: null,
    } });
    api.lifecycleAction.mockResolvedValue(state());
    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await view.findByRole('button', { name: '作废当前有效单据' }));
    expect((await view.findByRole('alertdialog', { name: '作废差旅单据' })).textContent).toContain('不恢复旧版本');
    fireEvent.change(view.getByLabelText('作废原因（选填）'), { target: { value: '客户取消会议' } });
    fireEvent.click(view.getByRole('button', { name: '确认作废' }));
    await waitFor(() => expect(api.lifecycleAction).toHaveBeenCalledWith('CID', expect.objectContaining({ action: 'void', reason: '客户取消会议' })));
  });
});

describe('员工单据卡片办理', () => {
  it('从查询卡片按后端资格确认撤回到 S005，员工侧没有审批按钮', async () => {
    const pending = document({ status: 'S002', version: 1, isEffective: false, currentEffectiveId: null,
      actions: { withdraw: { allowed: true, reason: null }, void: { allowed: false, reason: '当前不可作废。' },
        change: { allowed: false, reason: '当前不可变更。' }, resubmit: { allowed: false, reason: '当前不可重提。' } } });
    const withdrawn = document({ ...pending, status: 'S005', version: 2,
      history: [...pending.history, { action: 'withdraw', at: '2026-09-13T10:00:00+08:00', fromStatus: 'S002', toStatus: 'S005', role: 'EMPLOYEE', submissionRound: 1 }],
      actions: { ...pending.actions, withdraw: { allowed: false, reason: '仅 S002 可撤回。' }, resubmit: { allowed: true, reason: null } } });
    api.lifecycle.mockResolvedValue(state([pending]));
    api.lifecycleDetail.mockResolvedValue({ ...state([pending]), selectedDocument: pending });
    api.lifecycleAction.mockResolvedValue({ ...state([withdrawn]), selectedDocument: withdrawn });

    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    await waitFor(() => expect(view.getByRole('button', { name: '撤回本次提交' }).hasAttribute('disabled')).toBe(false));
    fireEvent.click(view.getByRole('button', { name: '撤回本次提交' }));
    fireEvent.click(await view.findByRole('button', { name: '确认撤回' }));

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
    fireEvent.click(await first.findByRole('button', { name: '撤回本次提交' }));
    fireEvent.click(await first.findByRole('button', { name: '确认撤回' }));
    expect(await first.findByText(/结果待核对/)).not.toBeNull();
    expect(first.queryByRole('alertdialog')).toBeNull();
    const originalId = JSON.parse(localStorage.getItem('travelLifecyclePendingOperation') || '{}').CID.body.clientRequestId;
    first.unmount();

    const second = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await second.findByRole('button', { name: '查询办理结果' }));
    await waitFor(() => expect(api.lifecycleAction).toHaveBeenCalledTimes(2));
    expect(api.lifecycleReceipt.mock.invocationCallOrder[0]).toBeLessThan(api.lifecycleAction.mock.invocationCallOrder[1]);
    expect(api.lifecycleAction.mock.calls[1][1].clientRequestId).toBe(originalId);
  });

  it('过期写请求会调用刷新但仍由原写操作可靠释放 loading', async () => {
    const target = document();
    const initial = { ...state([target]), selectedDocument: target, draft: draft(target) };
    api.lifecycle.mockResolvedValue(initial);
    api.lifecycleSave.mockRejectedValue(new ApiError('草稿已变化', 409, 'CONFIRMATION_STALE'));

    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await view.findByRole('button', { name: '继续编辑变更' }));
    fireEvent.change(view.getByLabelText('出差事由'), { target: { value: '保留这次修改' } });
    fireEvent.click(view.getByRole('button', { name: '保存并查看差异' }));

    await waitFor(() => expect(api.lifecycle).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(view.getByRole('button', { name: '保存并查看差异' }).hasAttribute('disabled')).toBe(false));
  });

  it('切换到新会话时立即移除旧会话单据并等待新状态', async () => {
    const old = document({ applicationId: 'APP-A', applicationNo: '会话-A-单据' });
    const next = deferred<LifecycleState>();
    api.lifecycle.mockImplementation((_id: string) => _id === 'A' ? Promise.resolve(state([old])) : next.promise);

    const view = render(<DocumentPanel conversationId="A" refreshToken={0} />);
    expect(await view.findByText('会话-A-单据')).not.toBeNull();

    view.rerender(<DocumentPanel conversationId="B" refreshToken={0} />);

    expect(view.queryByText('会话-A-单据')).toBeNull();
    expect(view.queryByRole('button', { name: '作废当前有效单据' })).toBeNull();
  });

  it('未知提交结果锁定编辑器中的保存、提交和放弃入口', async () => {
    const target = document();
    api.lifecycle.mockResolvedValue({ ...state([target]), selectedDocument: target, draft: draft(target) });
    api.lifecycleSubmit.mockRejectedValue(new ApiError('断网', 0, 'NETWORK_ERROR'));

    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await view.findByRole('button', { name: '继续编辑变更' }));
    fireEvent.click(view.getByRole('button', { name: '确认提交变更' }));
    expect(await view.findByText(/结果待核对/)).not.toBeNull();

    expect(view.getByRole('button', { name: '保存并查看差异' }).hasAttribute('disabled')).toBe(true);
    expect(view.getByRole('button', { name: '确认提交变更' }).hasAttribute('disabled')).toBe(true);
    expect(view.getByRole('button', { name: '放弃本次编辑' }).hasAttribute('disabled')).toBe(true);
  });

  it('不同会话分别保留未知操作，后一会话不会覆盖前一会话请求号', async () => {
    const actionable = document({ status: 'S002', version: 1, isEffective: false,
      actions: { withdraw: { allowed: true, reason: null }, void: { allowed: false, reason: '不可作废' },
        change: { allowed: false, reason: '不可变更' }, resubmit: { allowed: false, reason: '不可重提' } } });
    api.lifecycle.mockResolvedValue({ ...state([actionable]), selectedDocument: actionable });
    api.lifecycleAction.mockRejectedValue(new ApiError('断网', 0, 'NETWORK_ERROR'));

    const first = render(<DocumentPanel conversationId="A" refreshToken={0} />);
    fireEvent.click(await first.findByRole('button', { name: '撤回本次提交' }));
    fireEvent.click(await first.findByRole('button', { name: '确认撤回' }));
    expect(await first.findByText(/结果待核对/)).not.toBeNull();
    expect(first.queryByRole('alertdialog')).toBeNull();
    first.unmount();

    const second = render(<DocumentPanel conversationId="B" refreshToken={0} />);
    fireEvent.click(await second.findByRole('button', { name: '撤回本次提交' }));
    fireEvent.click(await second.findByRole('button', { name: '确认撤回' }));
    expect(await second.findByText(/结果待核对/)).not.toBeNull();
    second.unmount();

    const restored = render(<DocumentPanel conversationId="A" refreshToken={0} />);
    expect(await restored.findByRole('button', { name: '查询办理结果' })).not.toBeNull();
  });

  it('收起编辑器后查询同一草稿，继续编辑仍保留未保存输入', async () => {
    const target = document();
    const initial = { ...state([target]), selectedDocument: target, draft: draft(target) };
    api.lifecycle.mockResolvedValue(initial);
    api.lifecycleQuery.mockResolvedValue(initial);

    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await view.findByRole('button', { name: '继续编辑变更' }));
    fireEvent.change(view.getByLabelText('出差事由'), { target: { value: '收起后仍需保留' } });
    fireEvent.click(view.getByRole('button', { name: '关闭生命周期编辑' }));
    view.rerender(<DocumentPanel conversationId="CID" refreshToken={1} />);
    await waitFor(() => expect(api.lifecycle).toHaveBeenCalledTimes(2));
    fireEvent.click(view.getByRole('button', { name: '继续编辑变更' }));

    expect((view.getByLabelText('出差事由') as HTMLTextAreaElement).value).toBe('收起后仍需保留');
  });

  it('基础选项加载失败会在编辑器提示并允许原地重试', async () => {
    const target = document();
    api.lifecycle.mockResolvedValue({ ...state([target]), selectedDocument: target, draft: draft(target) });
    api.lifecycleOptions.mockRejectedValueOnce(new ApiError('主数据暂时不可用', 503, 'OPTIONS_UNAVAILABLE'))
      .mockResolvedValueOnce({ uuid: 'O', code: 'SUCCESS', message: {}, data: options });

    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await view.findByRole('button', { name: '继续编辑变更' }));
    expect(await view.findByText(/基础选项加载失败.*主数据暂时不可用/)).not.toBeNull();
    fireEvent.click(view.getByRole('button', { name: '重试加载基础选项' }));

    await waitFor(() => expect(api.lifecycleOptions).toHaveBeenCalledTimes(2));
    expect(await view.findByRole('option', { name: '研发部' })).not.toBeNull();
  });

  it('服务器以 HTTP 200 返回 UNKNOWN 时仍保留原请求和恢复入口', async () => {
    const target = document(); const initial = { ...state([target]), selectedDocument: target, draft: draft(target) };
    api.lifecycle.mockResolvedValue(initial);
    api.lifecycleSubmit.mockImplementation(async (_cid, body) => ({ ...initial,
      draft: { ...initial.draft!, requestId: body.clientRequestId },
      lastReceipt: { clientRequestId: body.clientRequestId, status: 'UNKNOWN', result: { message: '待核对' } },
    }));

    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await view.findByRole('button', { name: '继续编辑变更' }));
    fireEvent.click(view.getByRole('button', { name: '确认提交变更' }));

    await waitFor(() => expect(api.lifecycleSubmit).toHaveBeenCalledTimes(1));
    await view.findByText(/办理结果待核对，已保留原请求号/);
    expect(localStorage.getItem('travelLifecyclePendingOperation')).not.toBeNull();
    expect(view.queryByRole('button', { name: '查询办理结果' })).not.toBeNull();
  });

  it('同一草稿经自然语言更新 revision 后，无本地编辑的表单显示最新内容', async () => {
    const target = document(); const initial = { ...state([target]), selectedDocument: target, draft: draft(target) };
    api.lifecycle.mockResolvedValueOnce(initial);
    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    await view.findByRole('button', { name: '继续编辑变更' });
    api.lifecycle.mockResolvedValue({ ...initial, draft: { ...initial.draft!, revision: 2, fingerprint: 'fingerprint-2',
      differences: [{ field: 'remark', before: '客户拜访', after: '自然语言新说明' }],
      payload: { ...initial.draft!.payload, remark: '自然语言新说明' } } });
    view.rerender(<DocumentPanel conversationId="CID" refreshToken={1} />);

    await waitFor(() => expect(api.lifecycle).toHaveBeenCalledTimes(2));
    fireEvent.click(view.getByRole('button', { name: '继续编辑变更' }));
    await view.findByText('客户拜访 → 自然语言新说明');
    expect((view.getByLabelText('出差事由') as HTMLTextAreaElement).value).toBe('自然语言新说明');
  });

  it('同一草稿 revision 更新时保留未保存输入并要求显式采用最新内容', async () => {
    const target = document(); const initial = { ...state([target]), selectedDocument: target, draft: draft(target) };
    api.lifecycle.mockResolvedValueOnce(initial);
    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await view.findByRole('button', { name: '继续编辑变更' }));
    fireEvent.change(view.getByLabelText('出差事由'), { target: { value: '本地未保存说明' } });
    api.lifecycle.mockResolvedValue({ ...initial, draft: { ...initial.draft!, revision: 2, fingerprint: 'fingerprint-2',
      differences: [{ field: 'remark', before: '客户拜访', after: '自然语言新说明' }],
      payload: { ...initial.draft!.payload, remark: '自然语言新说明' } } });
    view.rerender(<DocumentPanel conversationId="CID" refreshToken={1} />);

    await waitFor(() => expect(api.lifecycle).toHaveBeenCalledTimes(2));
    expect((view.getByLabelText('出差事由') as HTMLTextAreaElement).value).toBe('本地未保存说明');
    expect(await view.findByText(/草稿已更新到 revision 2/)).not.toBeNull();
    expect(view.getByRole('button', { name: '保存并查看差异' }).hasAttribute('disabled')).toBe(true);
    expect(view.getByRole('button', { name: '确认提交变更' }).hasAttribute('disabled')).toBe(true);
    fireEvent.click(view.getByRole('button', { name: '使用最新草稿内容' }));
    expect((view.getByLabelText('出差事由') as HTMLTextAreaElement).value).toBe('自然语言新说明');
    expect(view.queryByText(/草稿已更新到 revision 2/)).toBeNull();
    expect(view.getByRole('button', { name: '保存并查看差异' }).hasAttribute('disabled')).toBe(false);
  });

  it('失败回执恢复会先同步助手请求终态再清除本地 pending', async () => {
    const target = document(); const initial = { ...state([target]), selectedDocument: target, draft: draft(target) };
    api.lifecycle.mockResolvedValueOnce(initial);
    api.lifecycleSubmit.mockRejectedValueOnce(new ApiError('断网', 0, 'NETWORK_ERROR'));
    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await view.findByRole('button', { name: '继续编辑变更' }));
    fireEvent.click(view.getByRole('button', { name: '确认提交变更' }));
    await view.findByRole('button', { name: '查询办理结果' });
    const requestId = api.lifecycleSubmit.mock.calls[0][1].clientRequestId;
    const failed = { ...initial, draft: initial.draft,
      lastReceipt: { clientRequestId: requestId, status: 'FAILED' as const, result: { message: '单据已变化' } } };
    api.lifecycleReceipt.mockResolvedValue({ data: failed.lastReceipt });
    api.lifecycleRecover.mockRejectedValueOnce(new ApiError('单据已变化', 409, 'VERSION_CONFLICT'));
    api.lifecycle.mockResolvedValue(failed);

    fireEvent.click(view.getByRole('button', { name: '查询办理结果' }));

    await waitFor(() => expect(api.lifecycleRecover).toHaveBeenCalledWith('CID'));
    await waitFor(() => expect(api.lifecycle).toHaveBeenCalledTimes(2));
    expect(localStorage.getItem('travelLifecyclePendingOperation')).toBeNull();
    expect(view.queryByRole('button', { name: '查询办理结果' })).toBeNull();
    expect(view.getByRole('button', { name: '保存并查看差异' }).hasAttribute('disabled')).toBe(false);
  });

  it('浏览器无记录时会从服务端 UNKNOWN 恢复原请求入口', async () => {
    const target = document(); const requestId = 'server-request';
    const unknown = { ...state([target]), selectedDocument: target, draft: { ...draft(target), requestId },
      lastReceipt: { clientRequestId: requestId, status: 'UNKNOWN' as const, result: { message: '待核对' } } };
    const succeeded = { ...state([target]), selectedDocument: target, draft: null,
      lastReceipt: { clientRequestId: requestId, status: 'SUCCEEDED' as const, result: { message: '已完成' } } };
    api.lifecycle.mockResolvedValue(unknown);
    api.lifecycleRecover.mockResolvedValue(succeeded);

    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    const recoverButton = await view.findByRole('button', { name: '查询办理结果' });
    expect(JSON.parse(localStorage.getItem('travelLifecyclePendingOperation') || '{}').CID).toMatchObject({
      conversationId: 'CID', kind: 'recover', body: { clientRequestId: requestId },
    });
    fireEvent.click(recoverButton);

    await waitFor(() => expect(api.lifecycleRecover).toHaveBeenCalledWith('CID'));
    expect(localStorage.getItem('travelLifecyclePendingOperation')).toBeNull();
  });

  it('助手返回其他请求的终态时不会清除当前原请求', async () => {
    const target = document(); const initial = { ...state([target]), selectedDocument: target, draft: draft(target) };
    api.lifecycle.mockResolvedValue(initial);
    api.lifecycleSubmit.mockRejectedValueOnce(new ApiError('断网', 0, 'NETWORK_ERROR'));
    const view = render(<DocumentPanel conversationId="CID" refreshToken={0} />);
    fireEvent.click(await view.findByRole('button', { name: '继续编辑变更' }));
    fireEvent.click(view.getByRole('button', { name: '确认提交变更' }));
    const recoverButton = await view.findByRole('button', { name: '查询办理结果' });
    const requestId = api.lifecycleSubmit.mock.calls[0][1].clientRequestId;
    api.lifecycleReceipt.mockResolvedValue({ data: { clientRequestId: requestId, status: 'FAILED', result: { message: '失败' } } });
    api.lifecycleRecover.mockResolvedValue({ ...initial, draft: initial.draft,
      lastReceipt: { clientRequestId: 'another-request', status: 'SUCCEEDED', result: { message: '其他请求已完成' } } });

    fireEvent.click(recoverButton);

    await view.findByText(new RegExp(`尚未取得原请求 ${requestId} 的终态`));
    expect(JSON.parse(localStorage.getItem('travelLifecyclePendingOperation') || '{}').CID.body.clientRequestId).toBe(requestId);
    expect(view.queryByRole('button', { name: '查询办理结果' })).not.toBeNull();
  });
});
