import type {
  ApplicationList, AssistantStatus, ConversationDetail, ConversationSummary,
  ApiIssue, CityOption, DraftEdits, FormTransport, IntegrationEvent, MockEnvelope, Scenario,
  SubmissionReceipt, TravelApplication, Turn,
} from './types';

export class ApiError extends Error {
  code?: string;
  status: number;
  issues: ApiIssue[];

  constructor(message: string, status: number, code?: string, issues: ApiIssue[] = []) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.issues = issues;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: init?.body ? { 'Content-Type': 'application/json', ...init.headers } : init?.headers,
    });
  } catch {
    throw new ApiError('无法连接本地服务，请确认服务已启动后重试。', 0, 'NETWORK_ERROR');
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError('服务返回了无法识别的内容。', response.status, 'INVALID_RESPONSE');
  }

  if (!response.ok) {
    const value = body as {
      error?: { code?: string; message?: string; issues?: ApiIssue[] };
      code?: string;
      message?: { text?: string };
    };
    throw new ApiError(
      value.error?.message || value.message?.text || `请求失败（HTTP ${response.status}）`,
      response.status,
      value.error?.code || value.code,
      value.error?.issues || [],
    );
  }
  return body as T;
}

export const assistantApi = {
  status: () => requestJson<AssistantStatus>('/assistant/api/status'),
  conversations: () => requestJson<{ items: ConversationSummary[] }>('/assistant/api/conversations'),
  createConversation: () => requestJson<ConversationDetail>('/assistant/api/conversations', {
    method: 'POST', body: '{}',
  }),
  deleteConversation: (id: string) => requestJson<{ id: string; deleted: boolean }>(
    `/assistant/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' },
  ),
  conversation: (id: string) => requestJson<ConversationDetail>(
    `/assistant/api/conversations/${encodeURIComponent(id)}`,
  ),
  sendMessage: (
    id: string,
    payload: {
      text: string;
      clientRequestId: string;
      confirmation?: { draftId: string; revision: number; fingerprint: string };
    },
  ) => requestJson<{ turnId: string; status: string }>(
    `/assistant/api/conversations/${encodeURIComponent(id)}/messages`,
    { method: 'POST', body: JSON.stringify(payload) },
  ),
  turn: (id: string) => requestJson<Turn>(`/assistant/api/turns/${encodeURIComponent(id)}`),
  formOptions: () => requestJson<{ transports: FormTransport[] }>('/assistant/api/form-options'),
  cities: (filter: string) => requestJson<{ items: CityOption[] }>(
    `/assistant/api/cities?filter=${encodeURIComponent(filter)}`,
  ),
  submitDraft: (
    id: string,
    payload: { clientRequestId: string; draftId: string; revision: number; edits: DraftEdits },
  ) => requestJson<{ turnId: string; status: string }>(
    `/assistant/api/conversations/${encodeURIComponent(id)}/submit`,
    { method: 'POST', body: JSON.stringify(payload) },
  ),
};

export const simulatorApi = {
  scenario: () => requestJson<MockEnvelope<Scenario>>('/mock/v1/scenario'),
  updateScenario: (payload: Partial<Scenario> & Pick<Scenario, 'submissionResult'>) =>
    requestJson<MockEnvelope<Scenario>>('/mock/v1/scenario', {
      method: 'PUT', body: JSON.stringify(payload),
    }),
  applications: () => requestJson<MockEnvelope<ApplicationList>>('/mock/v1/travel/applications?limit=100'),
  application: (id: string) => requestJson<MockEnvelope<TravelApplication>>(
    `/mock/v1/travel/applications/${encodeURIComponent(id)}`,
  ),
  receipt: (requestId: string) => requestJson<MockEnvelope<SubmissionReceipt>>(
    `/mock/v1/submissions/${encodeURIComponent(requestId)}`,
  ),
  events: () => requestJson<MockEnvelope<{ items: IntegrationEvent[] }>>(
    '/mock/v1/integration/events?limit=50',
  ),
};
