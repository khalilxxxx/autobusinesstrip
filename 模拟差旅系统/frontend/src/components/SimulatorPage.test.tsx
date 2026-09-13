// @vitest-environment jsdom
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  scenario: vi.fn(), updateScenario: vi.fn(), applications: vi.fn(),
  application: vi.fn(), receipt: vi.fn(), events: vi.fn(), lifecycleDocuments: vi.fn(),
  lifecycleDocument: vi.fn(), lifecycleApproval: vi.fn(), seedLifecycle: vi.fn(),
}));

vi.mock('../api', () => ({ simulatorApi: api }));

import type { LifecycleDocument } from '../types';
import { SimulatorPage } from './SimulatorPage';

const application = (id: string): LifecycleDocument => ({
  applicationId: id, applicationNo: `NO-${id}`, createdAt: '2026-09-12T09:00:00+08:00', demoOnly: true,
  request: { applicantId: 'EMP', departmentId: 'DEPT', payerCompanyId: 'COMP', remark: `事由 ${id}`, dqydbg: null, trips: [] },
  submittedAt: '2026-09-12T09:00:00+08:00', status: 'S004', tflag: 'D', documentType: 'APPLICATION', version: 3,
  submissionRound: 1, rootId: id, rootNo: `NO-${id}`, predecessorId: null, currentEffectiveId: id,
  pendingChangeId: null, isEffective: true, isSuperseded: false, tripStart: '2026-10-01', tripEnd: '2026-10-02', history: [],
  actions: { withdraw: { allowed: false, reason: '不可撤回' }, void: { allowed: true, reason: null },
    change: { allowed: true, reason: null }, resubmit: { allowed: false, reason: '不可重提' } },
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, '', '/simulator');
  api.scenario.mockResolvedValue({ data: { submissionResult: 'SUCCESS', failureMessage: '模拟失败' } });
  api.applications.mockResolvedValue({ data: { items: [application('A'), application('B')], total: 2, limit: 100, offset: 0 } });
  api.events.mockResolvedValue({ data: { items: [] } });
  api.lifecycleDocuments.mockResolvedValue({ data: { items: [application('A'), application('B')], total: 2, limit: 100, offset: 0 } });
});

afterEach(cleanup);

describe('模拟申请详情', () => {
  it('较早的详情请求晚返回时不会覆盖最新选择', async () => {
    const requestA = deferred<{ data: LifecycleDocument }>();
    const requestB = deferred<{ data: LifecycleDocument }>();
    api.lifecycleDocument.mockImplementation((id: string) => id === 'A' ? requestA.promise : requestB.promise);

    const view = render(<SimulatorPage />);
    fireEvent.click(await view.findByRole('button', { name: /NO-A/ }));
    fireEvent.click(view.getByRole('button', { name: /NO-B/ }));

    requestB.resolve({ data: application('B') });
    await view.findByText('NO-B');
    requestA.resolve({ data: application('A') });
    await new Promise((resolve) => window.setTimeout(resolve, 20));

    expect(view.getByText('NO-B', { selector: '.detail-heading strong' })).not.toBeNull();
    expect(view.queryByText('NO-A', { selector: '.detail-heading strong' })).toBeNull();
    expect(new URL(window.location.href).searchParams.get('applicationId')).toBe('B');
  });

  it('审批动作只在模拟控制台按状态显示，使用当前 expectedVersion 并可非破坏性添加样例', async () => {
    const pending = { ...application('A'), status: 'S002', tflag: 'D', version: 7, documentType: 'APPLICATION',
      submissionRound: 1, rootId: 'A', rootNo: 'NO-A', predecessorId: null, currentEffectiveId: null,
      pendingChangeId: null, isEffective: false, isSuperseded: false, history: [],
      actions: { withdraw: { allowed: true, reason: null }, void: { allowed: false, reason: '不可作废' },
        change: { allowed: false, reason: '不可变更' }, resubmit: { allowed: false, reason: '不可重提' } },
      submittedAt: '2026-09-12T09:00:00+08:00', tripStart: '2026-10-01', tripEnd: '2026-10-02' };
    api.lifecycleDocuments.mockResolvedValue({ data: { items: [pending], total: 1, limit: 100, offset: 0 } });
    api.lifecycleDocument.mockResolvedValue({ data: pending });
    api.lifecycleApproval.mockResolvedValue({ data: { document: { ...pending, status: 'S003', version: 8 } } });
    api.seedLifecycle.mockResolvedValue({ data: { created: 4, preserved: 1, demoOnly: true } });

    const view = render(<SimulatorPage />);
    fireEvent.click(await view.findByRole('button', { name: /NO-A/ }));
    fireEvent.click(await view.findByRole('button', { name: '模拟开始审批' }));
    await waitFor(() => expect(api.lifecycleApproval).toHaveBeenCalledWith('A', expect.objectContaining({
      action: 'start', expectedVersion: 7, clientRequestId: expect.any(String),
    })));
    expect(await view.findByRole('button', { name: '模拟审批完成' })).not.toBeNull();
    expect(view.getByText(/S004 是审批完成/)).not.toBeNull();

    fireEvent.click(view.getByRole('button', { name: '添加演示样例' }));
    await waitFor(() => expect(api.seedLifecycle).toHaveBeenCalled());
    expect(view.getByText(/保留已有数据/)).not.toBeNull();
  });
});
