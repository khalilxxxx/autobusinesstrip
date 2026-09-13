import { describe, expect, it } from 'vitest';
import { canConfirmDraft, formatDateTime, isCreateSuccess, phaseLabel } from './utils';

describe('助手状态显示', () => {
  it('仅允许完整且服务端可提交的当前草稿确认', () => {
    expect(canConfirmDraft({
      phase: 'READY_TO_CONFIRM', canSubmit: true, draftId: 'd-1', revision: 2,
      fingerprint: 'fp-1', lastSubmission: null, pending: [],
    })).toBe(true);
    expect(canConfirmDraft({
      phase: 'READY_TO_CONFIRM', canSubmit: false, draftId: 'd-1', revision: 2,
      fingerprint: 'fp-1', lastSubmission: null, pending: ['目的地'],
    })).toBe(false);
    expect(canConfirmDraft({
      phase: 'READY_TO_CONFIRM', canSubmit: true, draftId: 'd-1', revision: 2,
      fingerprint: 'fp-1', lastSubmission: null, pending: [{ field: 'purpose' }],
    })).toBe(true);
  });

  it('为阶段提供中文标签', () => {
    expect(phaseLabel('READY_TO_CONFIRM')).toBe('等待确认');
    expect(phaseLabel('unknown')).toBe('处理中');
  });
});

describe('模拟结果显示', () => {
  it('只把 code=SUCCESS 判断为创建成功', () => {
    expect(isCreateSuccess({ code: 'SUCCESS' })).toBe(true);
    expect(isCreateSuccess({ code: 'MOCK_SUBMIT_FAILED' })).toBe(false);
  });

  it('对无效时间返回原始文本', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date');
  });
});
