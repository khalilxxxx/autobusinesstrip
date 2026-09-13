// @vitest-environment jsdom
import { cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  scenario: vi.fn(), updateScenario: vi.fn(), applications: vi.fn(),
  application: vi.fn(), receipt: vi.fn(), events: vi.fn(),
}));

vi.mock('../api', () => ({ simulatorApi: api }));

import type { TravelApplication } from '../types';
import { SimulatorPage } from './SimulatorPage';

const application = (id: string): TravelApplication => ({
  applicationId: id, applicationNo: `NO-${id}`, createdAt: '2026-09-12T09:00:00+08:00', demoOnly: true,
  request: { applicantId: 'EMP', departmentId: 'DEPT', payerCompanyId: 'COMP', remark: `事由 ${id}`, dqydbg: null, trips: [] },
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
});

afterEach(cleanup);

describe('模拟申请详情', () => {
  it('较早的详情请求晚返回时不会覆盖最新选择', async () => {
    const requestA = deferred<{ data: TravelApplication }>();
    const requestB = deferred<{ data: TravelApplication }>();
    api.application.mockImplementation((id: string) => id === 'A' ? requestA.promise : requestB.promise);

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
});
