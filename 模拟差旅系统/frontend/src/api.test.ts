import { afterEach, describe, expect, it, vi } from 'vitest';
import { assistantApi } from './api';

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
