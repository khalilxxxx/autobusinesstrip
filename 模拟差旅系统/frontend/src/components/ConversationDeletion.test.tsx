// @vitest-environment jsdom
import { cleanup, fireEvent, render, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConversationDetail, Turn } from '../types';

const api = vi.hoisted(() => ({
  status: vi.fn(), conversations: vi.fn(), conversation: vi.fn(),
  createConversation: vi.fn(), deleteConversation: vi.fn(), sendMessage: vi.fn(), turn: vi.fn(),
}));
vi.mock('../api', () => ({ assistantApi: api }));
import { AssistantPage } from './AssistantPage';

const summary = (id: string) => ({ id, title: `会话 ${id}`, phase: 'COLLECTING', createdAt: '', updatedAt: '' });
const detail = (id: string): ConversationDetail => ({
  ...summary(id), activeTurnId: null,
  state: { phase: 'COLLECTING', canSubmit: false, draftId: '', revision: 0, fingerprint: '', pending: [], lastSubmission: null },
  messages: [{ id: `m-${id}`, role: 'assistant', content: `这是 ${id}`, status: 'succeeded', createdAt: '' }],
});

beforeEach(() => {
  vi.resetAllMocks();
  Object.defineProperty(Element.prototype, 'scrollIntoView', { configurable: true, value: vi.fn() });
  api.status.mockResolvedValue({ ready: true, appName: '差旅助手', employeeName: '演示员工' });
  api.conversations.mockResolvedValue({ items: [summary('A'), summary('B')] });
  api.conversation.mockImplementation((id: string) => Promise.resolve(detail(id)));
  api.deleteConversation.mockResolvedValue({ deleted: true });
});
afterEach(cleanup);

describe('删除历史会话', () => {
  it('先确认要删除的会话，取消时保留内容并恢复焦点', async () => {
    const view = render(<AssistantPage />);
    await view.findByText('这是 A');
    const trigger = view.getByRole('button', { name: '删除会话：会话 B' });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await view.findByRole('alertdialog', { name: '删除会话' });
    expect(within(dialog).getByText('会话 B')).not.toBeNull();
    expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: '取消' }));
    expect(api.deleteConversation).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole('button', { name: '取消' }));
    expect(view.queryByRole('alertdialog')).toBeNull();
    expect(view.getByText('这是 A')).not.toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('删除当前会话后切到另一会话、清空原输入并恢复键盘焦点', async () => {
    let finishLoading!: (value: ConversationDetail) => void;
    api.conversation.mockImplementation((id: string) => id === 'B'
      ? new Promise<ConversationDetail>((resolve) => { finishLoading = resolve; })
      : Promise.resolve(detail(id)));
    const view = render(<AssistantPage />);
    await view.findByText('这是 A');
    fireEvent.change(view.getByLabelText('发送给小智的消息'), { target: { value: '属于 A 的输入' } });
    const trigger = view.getByRole('button', { name: '删除会话：会话 A' });
    trigger.focus();
    fireEvent.click(trigger);
    fireEvent.click(within(await view.findByRole('alertdialog')).getByRole('button', { name: '确定删除' }));
    await waitFor(() => expect(api.conversation).toHaveBeenCalledWith('B'));
    finishLoading(detail('B'));
    await view.findByText('这是 B');
    expect(api.deleteConversation).toHaveBeenCalledWith('A');
    expect(view.queryByRole('button', { name: '删除会话：会话 A' })).toBeNull();
    expect((view.getByLabelText('发送给小智的消息') as HTMLTextAreaElement).value).toBe('');
    expect(document.activeElement).toBe(view.getByRole('button', { name: '新建会话' }));
  });

  it('删除最后一个会话后显示欢迎页，不自动创建空会话', async () => {
    api.conversations.mockResolvedValue({ items: [summary('A')] });
    const view = render(<AssistantPage />);
    await view.findByText('这是 A');
    fireEvent.click(view.getByRole('button', { name: '删除会话：会话 A' }));
    fireEvent.click(within(await view.findByRole('alertdialog')).getByRole('button', { name: '确定删除' }));
    await view.findByText('你好，我是小智');
    expect(view.queryByRole('button', { name: /删除会话：/ })).toBeNull();
    expect(api.createConversation).not.toHaveBeenCalled();
    expect(view.getByLabelText('发送给小智的消息').hasAttribute('disabled')).toBe(false);
  });

  it('删除非当前会话时保留当前内容和已输入文字', async () => {
    const view = render(<AssistantPage />);
    await view.findByText('这是 A');
    fireEvent.change(view.getByLabelText('发送给小智的消息'), { target: { value: '继续修改 A' } });
    fireEvent.click(view.getByRole('button', { name: '删除会话：会话 B' }));
    fireEvent.click(within(await view.findByRole('alertdialog')).getByRole('button', { name: '确定删除' }));
    await waitFor(() => expect(view.queryByRole('button', { name: '删除会话：会话 B' })).toBeNull());
    expect(view.getByText('这是 A')).not.toBeNull();
    expect((view.getByLabelText('发送给小智的消息') as HTMLTextAreaElement).value).toBe('继续修改 A');
  });

  it('删除失败在确认框中说明原因，保留会话并允许重试', async () => {
    api.deleteConversation.mockRejectedValueOnce(new Error('该会话仍在处理中，请完成后再删除。'));
    const view = render(<AssistantPage />);
    await view.findByText('这是 A');
    fireEvent.click(view.getByRole('button', { name: '删除会话：会话 B' }));
    const dialog = await view.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: '确定删除' }));
    expect(await within(dialog).findByRole('alert')).not.toBeNull();
    expect(within(dialog).getByText(/仍在处理中/)).not.toBeNull();
    expect(view.getByRole('button', { name: '删除会话：会话 B' })).not.toBeNull();
    fireEvent.click(within(dialog).getByRole('button', { name: '确定删除' }));
    await waitFor(() => expect(view.queryByRole('alertdialog')).toBeNull());
    expect(view.queryByRole('button', { name: '删除会话：会话 B' })).toBeNull();
  });

  it('后台轮询返回旧列表时不会恢复已删除的其他会话', async () => {
    let finish!: (turn: Turn) => void;
    api.turn.mockReturnValue(new Promise<Turn>((resolve) => { finish = resolve; }));
    api.conversation.mockResolvedValueOnce({ ...detail('A'), activeTurnId: 'turn-A' }).mockResolvedValue(detail('A'));
    const view = render(<AssistantPage />);
    await view.findByText('这是 A');
    expect(view.getByRole('button', { name: '删除会话：会话 A' }).hasAttribute('disabled')).toBe(true);
    fireEvent.click(view.getByRole('button', { name: '删除会话：会话 B' }));
    fireEvent.click(within(await view.findByRole('alertdialog')).getByRole('button', { name: '确定删除' }));
    await waitFor(() => expect(view.queryByRole('alertdialog')).toBeNull());
    finish({ id: 'turn-A', conversationId: 'A', status: 'succeeded', answer: '完成', error: null });
    await waitFor(() => expect(api.conversations).toHaveBeenCalledTimes(2));
    expect(view.queryByRole('button', { name: '删除会话：会话 B' })).toBeNull();
    expect(view.getByText('这是 A')).not.toBeNull();
  });
});
