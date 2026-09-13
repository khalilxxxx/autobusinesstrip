import type {
  ApplicationList, AssistantStatus, ConversationDetail, ConversationSummary,
  ApiIssue, CityOption, DraftEdits, FormTransport, IntegrationEvent, MockEnvelope, Scenario,
  SubmissionReceipt, TravelApplication, Turn, LifecycleDocument, LifecycleOptions,
  LifecycleQueryFilters, LifecycleReceipt, LifecycleState,
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
      error?: { code?: string; message?: string; issues?: ApiIssue[]; details?: ApiIssue[] };
      code?: string;
      message?: { text?: string; details?: ApiIssue[] };
    };
    throw new ApiError(
      value.error?.message || value.message?.text || `请求失败（HTTP ${response.status}）`,
      response.status,
      value.error?.code || value.code,
      value.error?.issues || value.error?.details || value.message?.details || [],
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
  lifecycle: (id: string) => requestJson<LifecycleState>(
    `/assistant/api/conversations/${encodeURIComponent(id)}/lifecycle`,
  ),
  lifecycleQuery: (id: string, filters: LifecycleQueryFilters) => requestJson<LifecycleState>(
    `/assistant/api/conversations/${encodeURIComponent(id)}/lifecycle/query`,
    { method: 'POST', body: JSON.stringify(filters) },
  ),
  lifecycleDetail: (id: string, reference: string) => requestJson<LifecycleState>(
    `/assistant/api/conversations/${encodeURIComponent(id)}/lifecycle/detail`,
    { method: 'POST', body: JSON.stringify({ reference }) },
  ),
  lifecyclePrepare: (id: string, payload: { reference: string; mode: 'change' | 'resubmit' }) =>
    requestJson<LifecycleState>(`/assistant/api/conversations/${encodeURIComponent(id)}/lifecycle/prepare`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  lifecycleSave: (id: string, payload: { draftId: string; revision: number; payload: TravelApplication['request'] }) =>
    requestJson<LifecycleState>(`/assistant/api/conversations/${encodeURIComponent(id)}/lifecycle/draft`, {
      method: 'PUT', body: JSON.stringify(payload),
    }),
  lifecycleSubmit: (id: string, payload: { draftId: string; revision: number; fingerprint: string; clientRequestId: string }) =>
    requestJson<LifecycleState>(`/assistant/api/conversations/${encodeURIComponent(id)}/lifecycle/submit`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
  lifecycleAction: (id: string, payload: { reference: string; action: 'withdraw' | 'void'; expectedVersion: number;
    clientRequestId: string; reason?: string }) => requestJson<LifecycleState>(
      `/assistant/api/conversations/${encodeURIComponent(id)}/lifecycle/action`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  lifecycleCancelDraft: (id: string) => requestJson<LifecycleState>(
    `/assistant/api/conversations/${encodeURIComponent(id)}/lifecycle/draft`, { method: 'DELETE' },
  ),
  lifecycleOptions: () => requestJson<MockEnvelope<LifecycleOptions>>('/mock/v1/lifecycle/options'),
  lifecycleReceipt: (requestId: string) => requestJson<MockEnvelope<LifecycleReceipt>>(
    `/mock/v1/lifecycle/receipts/${encodeURIComponent(requestId)}`,
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
  lifecycleDocuments: () => requestJson<MockEnvelope<{ items: LifecycleDocument[]; total: number; limit: number; offset: number }>>(
    '/mock/v1/lifecycle/documents?limit=100',
  ),
  lifecycleDocument: (id: string) => requestJson<MockEnvelope<LifecycleDocument>>(
    `/mock/v1/lifecycle/documents/${encodeURIComponent(id)}`,
  ),
  lifecycleApproval: (id: string, payload: { action: 'start' | 'complete' | 'return'; clientRequestId: string;
    expectedVersion: number; reason?: string }) => requestJson<MockEnvelope<{ document: LifecycleDocument }>>(
      `/mock/v1/lifecycle/documents/${encodeURIComponent(id)}/approval`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  seedLifecycle: () => requestJson<MockEnvelope<{ created?: number; preserved?: number; demoOnly: boolean }>>(
    '/mock/v1/lifecycle/seed', { method: 'POST', body: '{}' },
  ),
  lifecycleReceipt: (requestId: string) => requestJson<MockEnvelope<LifecycleReceipt>>(
    `/mock/v1/lifecycle/receipts/${encodeURIComponent(requestId)}`,
  ),
};
