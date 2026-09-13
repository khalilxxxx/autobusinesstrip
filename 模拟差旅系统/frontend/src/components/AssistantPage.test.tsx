// @vitest-environment jsdom
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  status: vi.fn(),
  conversations: vi.fn(),
  createConversation: vi.fn(),
  conversation: vi.fn(),
  sendMessage: vi.fn(),
  turn: vi.fn(),
  lifecycle: vi.fn(),
  lifecycleOptions: vi.fn(),
}));

vi.mock('../api', () => ({ assistantApi: api }));

import type { ConversationDetail, ConversationState } from '../types';
import { AssistantPage } from './AssistantPage';

const state = (pending: unknown[] = []): ConversationState => ({
  phase: 'COLLECTING', canSubmit: false, draftId: '', revision: 0,
  fingerprint: '', lastSubmission: null, pending,
});

const detail = (
  id: string,
  options: Partial<ConversationDetail> = {},
): ConversationDetail => ({
  id, title: `会话 ${id}`, createdAt: '2026-09-12T09:00:00+08:00',
  updatedAt: '2026-09-12T09:00:00+08:00', messages: [], state: state(), activeTurnId: null,
  ...options,
});

const summary = (id: string) => ({
  id, title: `会话 ${id}`, createdAt: '2026-09-12T09:00:00+08:00',
  updatedAt: '2026-09-12T09:00:00+08:00', phase: 'COLLECTING',
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, '', '/assistant');
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
  api.status.mockResolvedValue({ ready: true, appName: '差旅申请助手', employeeName: '普通演示员工', bridgeConfigured: true });
  api.createConversation.mockResolvedValue(detail('new'));
  api.lifecycle.mockResolvedValue({ documents: [], selectedDocument: null, draft: null, lastReceipt: null, querySummary: null });
  api.lifecycleOptions.mockResolvedValue({ data: { departments: [], payerCompanies: [], travelTypes: [], transports: [], cities: [], demoOnly: true } });
});

afterEach(cleanup);

describe('助手页面会话状态', () => {
  it('业务待澄清列表非空时仍允许继续输入', async () => {
    api.conversations.mockResolvedValue({ items: [summary('A')] });
    api.conversation.mockResolvedValue(detail('A', {
      messages: [{ id: 'm1', role: 'assistant', content: '还需要出发日期。', createdAt: '2026-09-12T09:00:00+08:00', status: 'succeeded' }],
      state: state([{ field: 'dateFrom', label: '出发日期' }]),
    }));

    const view = render(<AssistantPage />);
    const input = await view.findByLabelText('发送给小智的消息');
    expect(input.hasAttribute('disabled')).toBe(false);
  });

  it('空会话首轮发送后显示乐观消息和运行中回复', async () => {
    api.conversations.mockResolvedValue({ items: [summary('A')] });
    api.conversation.mockResolvedValue(detail('A'));
    api.sendMessage.mockResolvedValue({ turnId: 'turn-A', status: 'running' });
    api.turn.mockImplementation(() => new Promise(() => {}));

    const view = render(<AssistantPage />);
    const example = await view.findByRole('button', { name: /我下周一从杭州去桐庐/ });
    fireEvent.click(example);

    await waitFor(() => expect(api.sendMessage).toHaveBeenCalled());
    expect(view.container.querySelector('.pending-message')?.textContent).toContain('我下周一从杭州去桐庐');
    expect(view.container.querySelector('.running-message')).not.toBeNull();
  });

  it('A 请求未返回时切到 B，不锁住 B 且不接管 B 的轮询', async () => {
    const postA = deferred<{ turnId: string; status: string }>();
    api.conversations.mockResolvedValue({ items: [summary('A'), summary('B')] });
    api.conversation.mockImplementation((id: string) => Promise.resolve(detail(id, {
      messages: [{ id: `m-${id}`, role: 'assistant', content: `这是 ${id}`, createdAt: '2026-09-12T09:00:00+08:00', status: 'succeeded' }],
    })));
    api.sendMessage.mockReturnValue(postA.promise);
    api.turn.mockImplementation(() => new Promise(() => {}));

    const view = render(<AssistantPage />);
    const input = await view.findByLabelText('发送给小智的消息');
    fireEvent.change(input, { target: { value: '发送到 A' } });
    fireEvent.click(view.getByLabelText('发送消息'));
    await waitFor(() => expect(api.sendMessage).toHaveBeenCalled());

    fireEvent.click(view.getByRole('button', { name: /^会话 B/ }));
    await view.findByText('这是 B');
    expect((await view.findByLabelText('发送给小智的消息')).hasAttribute('disabled')).toBe(false);

    postA.resolve({ turnId: 'turn-A', status: 'running' });
    await new Promise((resolve) => window.setTimeout(resolve, 20));
    expect(api.turn).not.toHaveBeenCalledWith('turn-A');
    expect(view.getByText('这是 B')).not.toBeNull();
  });

  it('切换到 B 的详情加载完成前不会把输入发送到旧会话 A', async () => {
    const detailB = deferred<ConversationDetail>();
    api.conversations.mockResolvedValue({ items: [summary('A'), summary('B')] });
    api.conversation.mockImplementation((id: string) => id === 'A'
      ? Promise.resolve(detail('A', { messages: [{ id: 'm-A', role: 'assistant', content: '这是 A', createdAt: '2026-09-12T09:00:00+08:00', status: 'succeeded' }] }))
      : detailB.promise);

    const view = render(<AssistantPage />);
    await view.findByText('这是 A');
    fireEvent.click(view.getByRole('button', { name: /^会话 B/ }));

    const input = await view.findByLabelText('发送给小智的消息');
    expect(input.hasAttribute('disabled')).toBe(true);
    fireEvent.change(input, { target: { value: '发给 B 的内容' } });
    fireEvent.click(view.getByLabelText('发送消息'));
    expect(api.sendMessage).not.toHaveBeenCalled();

    detailB.resolve(detail('B'));
  });

  it('重连读到同一运行任务时立即恢复轮询', async () => {
    api.conversations.mockResolvedValue({ items: [summary('A')] });
    api.conversation.mockResolvedValue(detail('A', {
      messages: [{ id: 'm-A', role: 'assistant', content: '处理中会话', createdAt: '2026-09-12T09:00:00+08:00', status: 'succeeded' }],
      activeTurnId: 'turn-A',
    }));
    api.turn.mockRejectedValueOnce(new Error('暂时断网')).mockImplementation(() => new Promise(() => {}));

    const view = render(<AssistantPage />);
    await view.findByText(/正在继续检查本轮状态/);
    expect(api.turn).toHaveBeenCalledTimes(1);
    fireEvent.click(view.getByRole('button', { name: /重新连接/ }));

    await waitFor(() => expect(api.turn).toHaveBeenCalledTimes(2));
  });

  it('刷新载入不确定消息时显示明确状态', async () => {
    api.conversations.mockResolvedValue({ items: [summary('A')] });
    api.conversation.mockResolvedValue(detail('A', {
      messages: [{ id: 'uncertain', role: 'assistant', content: '已收到部分回复。', createdAt: '2026-09-12T09:00:00+08:00', status: 'uncertain' }],
    }));

    const view = render(<AssistantPage />);
    expect(await view.findByText(/本轮结果尚未确认/)).not.toBeNull();
  });

  it('任务完成但会话刷新失败时保留已收到的答案并提示重试', async () => {
    api.conversations.mockResolvedValue({ items: [summary('A')] });
    api.conversation
      .mockResolvedValueOnce(detail('A', {
        messages: [{ id: 'old', role: 'assistant', content: '上一轮', createdAt: '2026-09-12T09:00:00+08:00', status: 'succeeded' }],
      }))
      .mockRejectedValueOnce(new Error('暂时无法读取会话'));
    api.sendMessage.mockResolvedValue({ turnId: 'turn-A', status: 'running' });
    api.turn.mockResolvedValue({ id: 'turn-A', conversationId: 'A', status: 'succeeded', answer: '本轮最终答案', error: null });

    const view = render(<AssistantPage />);
    const input = await view.findByLabelText('发送给小智的消息');
    fireEvent.change(input, { target: { value: '继续处理' } });
    fireEvent.click(view.getByLabelText('发送消息'));

    expect(await view.findByText('本轮最终答案')).not.toBeNull();
    expect(await view.findByText(/会话刷新失败/)).not.toBeNull();
    expect(view.container.querySelector('.turn-result-message')).not.toBeNull();
  });
});
