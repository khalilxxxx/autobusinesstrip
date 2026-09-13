// @vitest-environment jsdom
import { cleanup, fireEvent, render, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  status: vi.fn(),
  conversations: vi.fn(),
  createConversation: vi.fn(),
  conversation: vi.fn(),
  sendMessage: vi.fn(),
  turn: vi.fn(),
  formOptions: vi.fn(),
  cities: vi.fn(),
  submitDraft: vi.fn(),
  lifecycle: vi.fn(),
  lifecycleQuery: vi.fn(),
  lifecycleOptions: vi.fn(),
}));

vi.mock('../api', () => ({ assistantApi: api }));

import type { ConversationDetail, ConversationState, DraftView } from '../types';
import { AssistantPage } from './AssistantPage';

const draft = (revision = 2): DraftView => ({
  draftId: 'draft-current',
  revision,
  applicantName: '普通演示员工',
  department: '产品研发部',
  payerCompany: '示例科技有限公司',
  travelType: 'NORMAL',
  reason: '拜访客户',
  trips: [{
    id: 'trip-1', fromCity: '杭州', toCity: '上海', departDate: '2026-10-18',
    arriveDate: '2026-10-20', transport: 'TRAIN_SECOND_CLASS',
  }],
});

const state = (overrides: Partial<ConversationState> = {}): ConversationState => ({
  phase: 'READY_TO_CONFIRM', canSubmit: true, draftId: 'draft-current', revision: 2,
  fingerprint: 'fingerprint-current', lastSubmission: null, pending: [],
  draft: draft(), synchronized: true, ...overrides,
});

const summary = { id: 'A', title: '上海出差', createdAt: '2026-09-12T09:00:00+08:00', updatedAt: '2026-09-12T09:00:00+08:00', phase: 'READY_TO_CONFIRM' };

function detail(currentState = state()): ConversationDetail {
  return {
    id: 'A', title: '上海出差', createdAt: '2026-09-12T09:00:00+08:00',
    updatedAt: '2026-09-12T09:00:00+08:00', activeTurnId: null, state: currentState,
    messages: [
      {
        id: 'm-old', role: 'assistant', content: '第一版草稿。', createdAt: '2026-09-12T09:00:00+08:00', status: 'succeeded',
        draftState: state({ draftId: 'draft-old', revision: 1, draft: { ...draft(1), draftId: 'draft-old' } }),
      },
      {
        id: 'm-current', role: 'assistant', content: '请核对这份草稿。', createdAt: '2026-09-12T09:05:00+08:00', status: 'succeeded',
        draftState: currentState,
      },
    ],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, '', '/assistant');
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
  api.status.mockResolvedValue({ ready: true, appName: '差旅申请助手', employeeName: '普通演示员工', bridgeConfigured: true });
  api.conversations.mockResolvedValue({ items: [summary] });
  api.conversation.mockResolvedValue(detail());
  api.formOptions.mockResolvedValue({
    transports: [
      { category: '火车', option: '高铁/动车二等座', value: 'TRAIN_SECOND_CLASS' },
      { category: '飞机', option: '经济舱', value: 'FLIGHT_ECONOMY' },
    ],
  });
  api.cities.mockResolvedValue({ items: [{ id: '310100', name: '上海市' }] });
  api.turn.mockImplementation(() => new Promise(() => {}));
  api.lifecycle.mockResolvedValue({ documents: [], selectedDocument: null, draft: null, lastReceipt: null, querySummary: null });
  api.lifecycleQuery.mockResolvedValue({ documents: [], selectedDocument: null, draft: null, lastReceipt: null,
    querySummary: { filters: { dateBasis: 'trip' }, total: 0, limit: 20, offset: 0 } });
  api.lifecycleOptions.mockResolvedValue({ data: { departments: [], payerCompanies: [], travelTypes: [], transports: [], cities: [], demoOnly: true } });
});

afterEach(cleanup);

describe('差旅草稿卡片', () => {
  it('显示每轮草稿快照且仅当前版本提供操作', async () => {
    const view = render(<AssistantPage />);

    const oldCard = await view.findByLabelText('差旅申请草稿（历史版本）');
    const currentCard = await view.findByLabelText('差旅申请草稿（当前版本）');
    expect(within(oldCard).queryByRole('button')).toBeNull();
    expect(within(oldCard).getByText('历史版本')).not.toBeNull();
    expect(within(currentCard).getByText('普通演示员工')).not.toBeNull();
    expect(within(currentCard).getByText('普通差旅')).not.toBeNull();
    expect(within(currentCard).getByText((_, node) => node?.tagName === 'STRONG' && node.textContent?.includes('杭州') === true && node.textContent?.includes('上海') === true)).not.toBeNull();
    expect(currentCard.querySelector('.lucide-arrow-right')).not.toBeNull();
    expect(currentCard.querySelector('.lucide-arrow-right-left')).toBeNull();
    expect(within(currentCard).getByRole('button', { name: '编辑申请' })).not.toBeNull();
    expect(view.queryByRole('button', { name: '继续对话' })).toBeNull();
    expect(within(currentCard).getByRole('button', { name: '提交单据' })).not.toBeNull();
    expect(view.getAllByText(/你可以直接回复补充或修改信息/)).toHaveLength(1);
    expect(currentCard.closest('article')?.querySelector('.message-bubble')?.textContent).toContain('点击“编辑申请”填写表单');
  });

  it('不完整草稿通过回复文字引导补充或编辑，但不能提交', async () => {
    const incomplete = state({ phase: 'COLLECTING', canSubmit: false, pending: [{ field: 'reason', question: '请补充出差事由' }] });
    api.conversation.mockResolvedValue(detail(incomplete));
    const view = render(<AssistantPage />);

    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    expect(within(card).getByText('待补充')).not.toBeNull();
    expect(within(card).getByRole('button', { name: '编辑申请' }).hasAttribute('disabled')).toBe(false);
    expect(within(card).getByRole('button', { name: '提交单据' }).hasAttribute('disabled')).toBe(true);

    expect(view.getByText(/你可以直接回复补充或修改信息/)).not.toBeNull();
    expect(view.getByLabelText('发送给小智的消息').hasAttribute('disabled')).toBe(false);
  });

  it('卡片直接提交沿用确认消息及当前版本', async () => {
    api.sendMessage.mockResolvedValue({ turnId: 'turn-card', status: 'running' });
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '提交单据' }));

    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith('A', expect.objectContaining({
      text: '确认提交',
      confirmation: { draftId: 'draft-current', revision: 2, fingerprint: 'fingerprint-current' },
    })));
  });

  it('卡片提交在成功响应无法解析时沿用请求号查询结果', async () => {
    api.sendMessage
      .mockRejectedValueOnce(Object.assign(new Error('服务返回了无法识别的内容。'), { code: 'INVALID_RESPONSE', status: 202 }))
      .mockResolvedValueOnce({ turnId: 'turn-card-query', status: 'running' });
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '提交单据' }));

    const query = await within(card).findByRole('button', { name: '查询提交结果' });
    const firstRequestId = api.sendMessage.mock.calls[0][1].clientRequestId;
    fireEvent.click(query);

    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledTimes(2));
    expect(api.sendMessage.mock.calls[1][1].clientRequestId).toBe(firstRequestId);
  });

  it('明确失败的最新草稿只读并说明可前往系统编辑', async () => {
    const failed = state({
      phase: 'COLLECTING', canSubmit: false,
      lastSubmission: { status: 'FAILED', requestId: 'request-failed', message: '模拟创建失败' },
    });
    api.conversation.mockResolvedValue(detail(failed));
    const view = render(<AssistantPage />);

    const card = await view.findByLabelText('差旅申请草稿（提交失败）');
    expect(within(card).queryByRole('button')).toBeNull();
    expect(within(card).getByText(/完整信息已保留为草稿/)).not.toBeNull();
    expect(within(card).getByText(/可前往差旅系统进一步编辑/)).not.toBeNull();
    expect(view.queryByText(/你可以直接回复补充或修改信息/)).toBeNull();
  });

  it('已提交草稿显示已提交并完全只读', async () => {
    const submitted = state({
      phase: 'SUBMITTED', canSubmit: false,
      lastSubmission: { status: 'SUCCEEDED', requestId: 'request-done', applicationNo: 'TA20260912001' },
    });
    api.conversation.mockResolvedValue(detail(submitted));
    const view = render(<AssistantPage />);

    const card = await view.findByLabelText('差旅申请草稿（已提交）');
    expect(within(card).getByText('已提交')).not.toBeNull();
    expect(within(card).queryByRole('button')).toBeNull();
    expect(view.queryByText(/你可以直接回复补充或修改信息/)).toBeNull();
  });

  it('未知提交结果禁用编辑并沿用服务端请求号查询', async () => {
    const unknown = state({
      lastSubmission: { status: 'UNKNOWN', requestId: 'request-original', message: '结果待确认' },
    });
    api.conversation.mockResolvedValue(detail(unknown));
    api.sendMessage.mockResolvedValue({ turnId: 'turn-query', status: 'running' });
    const view = render(<AssistantPage />);

    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    expect(within(card).getByRole('button', { name: '编辑申请' }).hasAttribute('disabled')).toBe(true);
    expect(view.queryByText(/你可以直接回复补充或修改信息/)).toBeNull();
    fireEvent.click(within(card).getByRole('button', { name: '查询提交结果' }));

    await waitFor(() => expect(api.sendMessage).toHaveBeenCalledWith('A', expect.objectContaining({ text: '确认提交' })));
    expect(api.sendMessage.mock.calls[0][1].clientRequestId).not.toBe('request-original');
  });
});

describe('草稿编辑抽屉', () => {
  it('语义查询结果到达时不会关闭创建草稿或覆盖未保存输入', async () => {
    let resolveQuery!: (value: unknown) => void;
    api.lifecycle.mockImplementationOnce(() => new Promise((resolve) => { resolveQuery = resolve; }));
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    const reason = within(drawer).getByLabelText('出差事由') as HTMLTextAreaElement;
    fireEvent.change(reason, { target: { value: '未保存的创建草稿输入' } });

    resolveQuery({ documents: [], selectedDocument: null, draft: null, lastReceipt: null,
      querySummary: { filters: { dateBasis: 'trip' }, total: 0, limit: 20, offset: 0 } });
    await view.findByText(/没有找到相关单据/);
    expect(view.getByRole('dialog', { name: '编辑差旅申请' })).not.toBeNull();
    expect((within(drawer).getByLabelText('出差事由') as HTMLTextAreaElement).value).toBe('未保存的创建草稿输入');
  });

  it('卡片显示规范城市名，抽屉保留可编辑的原始地点', async () => {
    const mappedDraft = {
      ...draft(),
      trips: [{ ...draft().trips[0], toCity: '苏州市' }],
      editTrips: [{ ...draft().trips[0], toCity: '昆山' }],
    } as DraftView;
    const mappedState = state({ draft: mappedDraft });
    api.conversation.mockResolvedValue(detail(mappedState));
    const view = render(<AssistantPage />);

    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    expect(card.textContent).toContain('苏州市');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    expect((within(drawer).getByLabelText('行程 1 到达城市') as HTMLInputElement).value).toBe('昆山');
  });

  it('展示完整字段和行程操作，且没有保存草稿入口', async () => {
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));

    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    expect(within(drawer).getByText('普通演示员工')).not.toBeNull();
    expect(within(drawer).getByText('产品研发部')).not.toBeNull();
    expect(within(drawer).getByText('示例科技有限公司')).not.toBeNull();
    expect(within(drawer).getByLabelText('差旅类型')).not.toBeNull();
    expect(within(drawer).getByRole('option', { name: '普通差旅' })).not.toBeNull();
    expect(within(drawer).getByRole('option', { name: '短期异地办公' })).not.toBeNull();
    expect(within(drawer).getByLabelText('出差事由')).not.toBeNull();
    expect(within(drawer).getByLabelText('行程 1 出发城市')).not.toBeNull();
    expect(within(drawer).getByLabelText('行程 1 到达城市')).not.toBeNull();
    expect(within(drawer).getByLabelText('行程 1 出发日期')).not.toBeNull();
    expect(within(drawer).getByLabelText('行程 1 到达日期')).not.toBeNull();
    expect(within(drawer).getByLabelText('行程 1 交通方式')).not.toBeNull();
    expect((within(drawer).getByLabelText('行程 1 交通方式') as HTMLSelectElement).selectedOptions[0].textContent).toBe('火车 - 高铁/动车二等座');
    expect(within(drawer).queryByRole('button', { name: /保存草稿/ })).toBeNull();
    expect(within(drawer).getAllByRole('button', { name: '提交单据' })).toHaveLength(1);

    fireEvent.click(within(drawer).getByRole('button', { name: '在此后插入行程' }));
    expect(within(drawer).getByText('行程 2')).not.toBeNull();
    fireEvent.click(within(drawer).getByRole('button', { name: '交换行程 1 的城市' }));
    expect((within(drawer).getByLabelText('行程 1 出发城市') as HTMLInputElement).value).toBe('上海');
    fireEvent.click(within(drawer).getByRole('button', { name: '删除行程 2' }));
    fireEvent.click(within(drawer).getByRole('button', { name: '增加行程' }));
    expect(within(drawer).getByText('行程 2')).not.toBeNull();
  });

  it('在前端限制事由为 1200 字，并拒绝提交超长内容', async () => {
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    const reason = within(drawer).getByLabelText('出差事由');
    expect(reason.getAttribute('maxlength')).toBe('1200');

    fireEvent.change(reason, { target: { value: '测'.repeat(1201) } });
    fireEvent.click(within(drawer).getByRole('button', { name: '提交单据' }));

    expect(await within(drawer).findByText('出差事由最多 1200 个字符。')).not.toBeNull();
    expect(api.submitDraft).not.toHaveBeenCalled();
  });

  it('已有 20 段行程时禁用所有新增入口', async () => {
    const trips = Array.from({ length: 20 }, (_, index) => ({
      ...draft().trips[0], id: `trip-${index + 1}`,
    }));
    const cappedState = state({ draft: { ...draft(), trips, editTrips: trips } });
    api.conversation.mockResolvedValue(detail(cappedState));
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });

    expect(within(drawer).getByRole('button', { name: '增加行程' }).hasAttribute('disabled')).toBe(true);
    within(drawer).getAllByRole('button', { name: '在此后插入行程' }).forEach((button) => {
      expect(button.hasAttribute('disabled')).toBe(true);
    });
  });

  it('校验失败保留编辑内容，选择城市后提交结构化新值', async () => {
    api.submitDraft.mockResolvedValue({ turnId: 'turn-form', status: 'running' });
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });

    const reason = within(drawer).getByLabelText('出差事由');
    fireEvent.change(reason, { target: { value: '' } });
    fireEvent.click(within(drawer).getByRole('button', { name: '提交单据' }));
    expect(await within(drawer).findByText('请填写出差事由。')).not.toBeNull();
    expect(api.submitDraft).not.toHaveBeenCalled();
    expect((reason as HTMLTextAreaElement).value).toBe('');
    await waitFor(() => expect(document.activeElement).toBe(reason));

    fireEvent.change(reason, { target: { value: '参加客户需求评审' } });
    const toCity = within(drawer).getByLabelText('行程 1 到达城市');
    fireEvent.change(toCity, { target: { value: '上' } });
    await waitFor(() => expect(api.cities).toHaveBeenCalledWith('上'));
    fireEvent.click(await within(drawer).findByRole('option', { name: '上海市' }));
    fireEvent.change(within(drawer).getByLabelText('行程 1 交通方式'), { target: { value: 'FLIGHT_ECONOMY' } });
    fireEvent.click(within(drawer).getByRole('button', { name: '提交单据' }));

    await waitFor(() => expect(api.submitDraft).toHaveBeenCalledWith('A', {
      clientRequestId: expect.any(String),
      draftId: 'draft-current',
      revision: 2,
      edits: {
        travelType: 'NORMAL', reason: '参加客户需求评审',
        trips: [{ id: 'trip-1', fromCity: '杭州', toCity: '上海市', departDate: '2026-10-18', arriveDate: '2026-10-20', transport: 'FLIGHT_ECONOMY' }],
      },
    }));
  });

  it('关闭有修改的抽屉前防误丢', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    fireEvent.change(within(drawer).getByLabelText('出差事由'), { target: { value: '新的事由' } });
    fireEvent.click(within(drawer).getByRole('button', { name: '关闭编辑' }));

    expect(confirm).toHaveBeenCalledWith('修改尚未提交，确定要关闭吗？');
    expect(view.getByRole('dialog', { name: '编辑差旅申请' })).not.toBeNull();

    confirm.mockReturnValue(true);
    fireEvent.click(within(drawer).getByRole('button', { name: '关闭编辑' }));
    await waitFor(() => expect(view.queryByRole('dialog', { name: '编辑差旅申请' })).toBeNull());
  });

  it('把服务端 snake_case 行程错误定位到对应字段并保留抽屉', async () => {
    api.submitDraft.mockRejectedValue({
      code: 'DRAFT_INVALID',
      issues: [{ target: 'trip-1', field: 'to_city', question: '请选择有效的到达城市。' }],
    });
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    fireEvent.click(within(drawer).getByRole('button', { name: '提交单据' }));

    expect(await within(drawer).findByText('请选择有效的到达城市。')).not.toBeNull();
    const toCity = within(drawer).getByLabelText('行程 1 到达城市');
    expect(toCity.getAttribute('aria-invalid')).toBe('true');
    await waitFor(() => expect(document.activeElement).toBe(toCity));
  });

  it('无法定位到单字段的服务端问题显示为抽屉全局错误', async () => {
    api.submitDraft.mockRejectedValue({
      code: 'DRAFT_INVALID',
      issues: [{ target: 'trip-1', field: 'cities', question: '城市基础数据暂时不可用。' }],
    });
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    fireEvent.click(within(drawer).getByRole('button', { name: '提交单据' }));

    expect((await within(drawer).findByRole('alert', { name: '表单错误' })).textContent).toContain('城市基础数据暂时不可用。');
  });

  it('解析 ValidationError 的 message 和字段路径，并让未知路径与请求摘要保持可见', async () => {
    api.submitDraft.mockRejectedValue(Object.assign(new Error('请求结构不符合接口约定，请核对参数。'), {
      code: 'INVALID_REQUEST',
      status: 422,
      issues: [
        { field: 'body.edits.reason', message: 'String should have at most 1200 characters' },
        { field: 'body.edits.trips.0.fromCity', message: 'String should have at most 100 characters' },
        { field: 'body.edits.unexpected', message: 'Extra inputs are not permitted' },
      ],
    }));
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    fireEvent.click(within(drawer).getByRole('button', { name: '提交单据' }));

    expect(await within(drawer).findByText('出差事由最多 1200 个字符。')).not.toBeNull();
    expect(within(drawer).getByText('出发城市最多 100 个字符。')).not.toBeNull();
    expect(within(drawer).getByRole('alert', { name: '表单错误' }).textContent).toContain('提交内容格式不正确，请核对后重试。');
    expect(within(drawer).getByRole('alert', { name: '提交错误' }).textContent).toContain('请求结构不符合接口约定');
    expect(drawer.textContent).not.toContain('String should');
    expect(drawer.textContent).not.toContain('Extra inputs');
    expect(within(drawer).getByLabelText('出差事由').getAttribute('aria-invalid')).toBe('true');
    expect(within(drawer).getByLabelText('行程 1 出发城市').getAttribute('aria-invalid')).toBe('true');
  });

  it('无字段 issues 的提交错误在抽屉内显示并保留输入', async () => {
    api.submitDraft.mockRejectedValue(Object.assign(new Error('草稿版本已变化，请重新打开最新草稿。'), { code: 'CONFIRMATION_STALE' }));
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    const reason = within(drawer).getByLabelText('出差事由');
    fireEvent.change(reason, { target: { value: '仍需保留的修改' } });
    fireEvent.click(within(drawer).getByRole('button', { name: '提交单据' }));

    expect((await within(drawer).findByRole('alert', { name: '提交错误' })).textContent).toContain('草稿版本已变化');
    expect((reason as HTMLTextAreaElement).value).toBe('仍需保留的修改');
  });

  it('打开抽屉后禁用聊天输入并把 Tab 焦点约束在对话框内', async () => {
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    const close = within(drawer).getByRole('button', { name: '关闭编辑' });
    const submit = within(drawer).getByRole('button', { name: '提交单据' });
    expect((view.getByLabelText('发送给小智的消息') as HTMLTextAreaElement).disabled).toBe(true);

    submit.focus();
    fireEvent.keyDown(drawer, { key: 'Tab' });
    expect(document.activeElement).toBe(close);
    close.focus();
    fireEvent.keyDown(drawer, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(submit);
  });

  it('表单提交断网后保留同一请求号并锁定内容查询结果', async () => {
    api.submitDraft
      .mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
      .mockResolvedValueOnce({ turnId: 'turn-receipt', status: 'running' });
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    fireEvent.change(within(drawer).getByLabelText('出差事由'), { target: { value: '断网前的新事由' } });
    fireEvent.click(within(drawer).getByRole('button', { name: '提交单据' }));

    const query = await within(drawer).findByRole('button', { name: '查询提交结果' });
    const firstRequestId = api.submitDraft.mock.calls[0][1].clientRequestId;
    expect((within(drawer).getByLabelText('出差事由') as HTMLTextAreaElement).disabled).toBe(true);
    fireEvent.click(query);

    await waitFor(() => expect(api.submitDraft).toHaveBeenCalledTimes(2));
    expect(api.submitDraft.mock.calls[1][1].clientRequestId).toBe(firstRequestId);
    expect(api.submitDraft.mock.calls[1][1].edits.reason).toBe('断网前的新事由');
  });

  it('表单提交在成功响应无法解析时保留同一请求号查询结果', async () => {
    api.submitDraft
      .mockRejectedValueOnce(Object.assign(new Error('服务返回了无法识别的内容。'), { code: 'INVALID_RESPONSE', status: 202 }))
      .mockResolvedValueOnce({ turnId: 'turn-truncated-query', status: 'running' });
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    fireEvent.click(within(drawer).getByRole('button', { name: '提交单据' }));

    const query = await within(drawer).findByRole('button', { name: '查询提交结果' });
    const firstRequestId = api.submitDraft.mock.calls[0][1].clientRequestId;
    fireEvent.click(query);

    await waitFor(() => expect(api.submitDraft).toHaveBeenCalledTimes(2));
    expect(api.submitDraft.mock.calls[1][1].clientRequestId).toBe(firstRequestId);
  });

  it('明确 4xx 响应无法解析时不把提交标为结果未知', async () => {
    api.submitDraft.mockRejectedValue(Object.assign(new Error('服务返回了无法识别的内容。'), {
      code: 'INVALID_RESPONSE', status: 422,
    }));
    const view = render(<AssistantPage />);
    const card = await view.findByLabelText('差旅申请草稿（当前版本）');
    fireEvent.click(within(card).getByRole('button', { name: '编辑申请' }));
    const drawer = await view.findByRole('dialog', { name: '编辑差旅申请' });
    fireEvent.click(within(drawer).getByRole('button', { name: '提交单据' }));

    expect((await within(drawer).findByRole('alert', { name: '提交错误' })).textContent).toContain('无法识别');
    expect(within(drawer).queryByRole('button', { name: '查询提交结果' })).toBeNull();
    expect((within(drawer).getByLabelText('出差事由') as HTMLTextAreaElement).disabled).toBe(false);
  });
});
