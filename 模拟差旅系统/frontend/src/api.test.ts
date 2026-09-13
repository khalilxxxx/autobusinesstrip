import { afterEach, describe, expect, it, vi } from 'vitest';
import { assistantApi, simulatorApi } from './api';

afterEach(() => vi.unstubAllGlobals());

describe('API 响应解析失败', () => {
  it('保留已收到的成功状态，供提交方判断结果未知', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"turnId":', { status: 202 })));

    await expect(assistantApi.submitDraft('A', {
      clientRequestId: 'request-1', draftId: 'draft-1', revision: 1,
      edits: { travelType: 'NORMAL', reason: '测试', trips: [] },
    })).rejects.toMatchObject({ code: 'INVALID_RESPONSE', status: 202 });
  });

  it('普通读取解析失败仍报告无效响应及原 HTTP 状态', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"items":', { status: 200 })));

    await expect(assistantApi.conversations()).rejects.toMatchObject({
      code: 'INVALID_RESPONSE', status: 200,
    });
  });
});

describe('单据生命周期 API 契约', () => {
  it('员工查询、详情与办理接口使用会话内生命周期路径并原样发送并发字段', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await assistantApi.lifecycleQuery('会话/A', { dateBasis: 'trip', temporal: 'future', city: '上海', effectiveOnly: true });
    await assistantApi.lifecycleDetail('会话/A', 'APP/1');
    await assistantApi.lifecyclePrepare('会话/A', { reference: 'APP/1', mode: 'change' });
    await assistantApi.lifecycleSave('会话/A', {
      draftId: 'draft-1', revision: 2,
      payload: { applicantId: 'EMP', departmentId: 'D1', payerCompanyId: 'C1', remark: '拜访', dqydbg: null, trips: [] },
    });
    await assistantApi.lifecycleSubmit('会话/A', {
      draftId: 'draft-1', revision: 3, fingerprint: 'fp-3', clientRequestId: 'request-submit',
    });
    await assistantApi.lifecycleAction('会话/A', {
      reference: 'APP/1', action: 'withdraw', expectedVersion: 4, clientRequestId: 'request-action',
    });
    await assistantApi.lifecycleRecover('会话/A');
    await assistantApi.lifecycleCancelDraft('会话/A');

    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      '/assistant/api/conversations/%E4%BC%9A%E8%AF%9D%2FA/lifecycle/query',
      '/assistant/api/conversations/%E4%BC%9A%E8%AF%9D%2FA/lifecycle/detail',
      '/assistant/api/conversations/%E4%BC%9A%E8%AF%9D%2FA/lifecycle/prepare',
      '/assistant/api/conversations/%E4%BC%9A%E8%AF%9D%2FA/lifecycle/draft',
      '/assistant/api/conversations/%E4%BC%9A%E8%AF%9D%2FA/lifecycle/submit',
      '/assistant/api/conversations/%E4%BC%9A%E8%AF%9D%2FA/lifecycle/action',
      '/assistant/api/conversations/%E4%BC%9A%E8%AF%9D%2FA/lifecycle/recover',
      '/assistant/api/conversations/%E4%BC%9A%E8%AF%9D%2FA/lifecycle/draft',
    ]);
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ reference: 'APP/1' });
    expect(fetchMock.mock.calls[3][1].method).toBe('PUT');
    expect(JSON.parse(fetchMock.mock.calls[4][1].body)).toEqual({
      draftId: 'draft-1', revision: 3, fingerprint: 'fp-3', clientRequestId: 'request-submit',
    });
    expect(JSON.parse(fetchMock.mock.calls[5][1].body)).toEqual({
      reference: 'APP/1', action: 'withdraw', expectedVersion: 4, clientRequestId: 'request-action',
    });
    expect(fetchMock.mock.calls[6][1]).toMatchObject({ method: 'POST', body: '{}' });
    expect(fetchMock.mock.calls[7][1].method).toBe('DELETE');
  });

  it('回执、模拟审批与 seed 使用 mock 生命周期接口', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response('{}', {
      status: 200, headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await assistantApi.lifecycleReceipt('请求/1');
    await simulatorApi.lifecycleApproval('APP/1', {
      action: 'complete', expectedVersion: 7, clientRequestId: 'approval-1',
    });
    await simulatorApi.seedLifecycle();

    expect(fetchMock.mock.calls[0][0]).toBe('/mock/v1/lifecycle/receipts/%E8%AF%B7%E6%B1%82%2F1');
    expect(fetchMock.mock.calls[1][0]).toBe('/mock/v1/lifecycle/documents/APP%2F1/approval');
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      action: 'complete', expectedVersion: 7, clientRequestId: 'approval-1',
    });
    expect(fetchMock.mock.calls[2][0]).toBe('/mock/v1/lifecycle/seed');
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'POST', body: '{}' });
  });

  it('兼容生命周期契约的 error.details 字段错误格式', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'DRAFT_INVALID', message: '草稿校验失败', details: [{ field: 'payload.trips.0.cityTo', message: '请选择到达城市' }] },
    }), { status: 422, headers: { 'Content-Type': 'application/json' } })));

    await expect(assistantApi.lifecycleDetail('A', 'APP-1')).rejects.toMatchObject({
      code: 'DRAFT_INVALID', status: 422,
      issues: [{ field: 'payload.trips.0.cityTo', message: '请选择到达城市' }],
    });
  });
});
