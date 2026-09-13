import type { ConversationState } from './types';

export function canConfirmDraft(_state: ConversationState | null | undefined): boolean {
  const state = _state;
  return Boolean(
    state?.phase === 'READY_TO_CONFIRM'
      && state.canSubmit
      && state.draftId
      && Number.isInteger(state.revision)
      && (state.revision ?? 0) > 0
      && state.fingerprint,
  );
}

export function phaseLabel(phase: string): string {
  return ({
    IDLE: '新会话',
    COLLECTING: '补充信息',
    READY_TO_CONFIRM: '等待确认',
    SUBMITTED: '已提交',
  } as Record<string, string>)[phase] ?? '处理中';
}

export function isCreateSuccess(value: { code?: string } | null | undefined): boolean {
  return value?.code === 'SUCCESS';
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(date);
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '请求失败，请稍后重试。';
}
