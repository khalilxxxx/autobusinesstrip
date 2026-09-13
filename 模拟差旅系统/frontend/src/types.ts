export type ConversationPhase = 'IDLE' | 'COLLECTING' | 'READY_TO_CONFIRM' | 'SUBMITTED' | string;

export interface SubmissionState {
  status: string;
  applicationId?: string | null;
  applicationNo?: string | null;
  requestId?: string | null;
  message?: string | null;
}

export interface DraftTrip {
  id: string;
  fromCity: string;
  toCity: string;
  departDate: string;
  arriveDate: string;
  transport: string;
}

export interface DraftView {
  draftId: string;
  revision: number;
  applicantName: string;
  department: string;
  payerCompany: string;
  travelType: 'NORMAL' | 'SHORT_TERM';
  reason: string;
  trips: DraftTrip[];
  editTrips?: DraftTrip[];
}

export interface FormTransport {
  category: string;
  option: string;
  value: string;
}

export interface CityOption {
  id: string;
  name: string;
}

export interface DraftEdits {
  travelType: DraftView['travelType'];
  reason: string;
  trips: DraftTrip[];
}

export interface ApiIssue {
  target?: string;
  field: string;
  question?: string;
  message?: string;
}

export interface ConversationState {
  phase: ConversationPhase;
  canSubmit: boolean;
  draftId: string | null;
  revision: number | null;
  fingerprint: string | null;
  lastSubmission: SubmissionState | null;
  pending: unknown[];
  draft?: DraftView | null;
  synchronized?: boolean;
}

export interface AssistantStatus {
  ready: boolean;
  appName: string;
  employeeName: string;
  bridgeConfigured: boolean;
}

export interface ConversationSummary {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  phase: ConversationPhase;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: string;
  status: string;
  draftState?: ConversationState | null;
}

export interface ConversationDetail {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
  state: ConversationState;
  activeTurnId: string | null;
}

export type TurnStatus = 'running' | 'succeeded' | 'failed' | 'uncertain';

export interface Turn {
  id: string;
  conversationId: string;
  status: TurnStatus;
  answer: string | null;
  error: { code?: string; message?: string } | string | null;
}

export interface MockEnvelope<T> {
  uuid: string | { value: string };
  code: string;
  message: { text?: string; details?: unknown };
  data: T;
}

export interface Scenario {
  submissionResult: 'SUCCESS' | 'FAILURE';
  failureMessage: string;
}

export interface Trip {
  dateFrom: string;
  dateTo: string;
  cityFrom: string;
  cityTo: string;
  tool: string;
}

export interface TravelApplication {
  applicationId: string;
  applicationNo: string;
  createdAt: string;
  demoOnly: boolean;
  request: {
    applicantId: string;
    departmentId: string;
    payerCompanyId: string;
    remark: string;
    dqydbg: 'Y' | null;
    trips: Trip[];
  };
}

export type LifecycleStatus = 'UNKNOWN' | 'S002' | 'S003' | 'S004' | 'S005' | 'S100' | string;
export type LifecycleDocumentType = 'APPLICATION' | 'CHANGE';

export interface LifecycleActionEligibility {
  allowed: boolean;
  reason: string | null;
}

export interface LifecycleHistoryItem {
  action: string;
  at: string;
  fromStatus: string | null;
  toStatus: string;
  role: string;
  submissionRound: number;
}

export interface LifecycleDocument extends TravelApplication {
  submittedAt: string;
  status: LifecycleStatus;
  tflag: 'D' | 'YBG' | string;
  documentType: LifecycleDocumentType;
  version: number;
  submissionRound: number;
  rootId: string;
  rootNo: string;
  predecessorId: string | null;
  currentEffectiveId: string | null;
  pendingChangeId: string | null;
  isEffective: boolean;
  isSuperseded: boolean;
  tripStart: string;
  tripEnd: string;
  history: LifecycleHistoryItem[];
  actions: Record<'withdraw' | 'void' | 'change' | 'resubmit', LifecycleActionEligibility>;
  stay?: { date: string; cityId?: string; cityName?: string; description?: string } | null;
}

export interface LifecycleDifference {
  field: string;
  before: unknown;
  after: unknown;
}

export interface LifecycleDraft {
  id: string;
  revision: number;
  mode: 'change' | 'resubmit';
  targetId: string;
  targetVersion: number;
  targetDocument: LifecycleDocument;
  payload: TravelApplication['request'];
  original: TravelApplication['request'];
  differences: LifecycleDifference[];
  fingerprint: string;
  requestId?: string;
}

export interface LifecycleQueryFilters {
  keyword?: string;
  city?: string;
  dateFrom?: string;
  dateTo?: string;
  temporal?: 'past' | 'current' | 'future';
  dateBasis: 'trip' | 'submitted';
  status?: string;
  effectiveOnly?: boolean;
  limit?: number;
  offset?: number;
}

export interface LifecycleReceipt {
  clientRequestId: string;
  createdAt?: string;
  status: 'UNKNOWN' | 'SUCCEEDED' | 'FAILED' | string;
  result: {
    action?: string;
    message?: string;
    document?: LifecycleDocument;
    documentResolvedToCurrent?: boolean;
    [key: string]: unknown;
  };
  demoOnly?: boolean;
}

export interface LifecycleState {
  documents: LifecycleDocument[];
  selectedDocument: LifecycleDocument | null;
  draft: LifecycleDraft | null;
  lastReceipt: LifecycleReceipt | null;
  querySummary: { filters: LifecycleQueryFilters; total: number; limit: number; offset: number } | null;
}

export interface LifecycleOptions {
  departments: { id: string; name: string }[];
  payerCompanies: { id: string; name: string }[];
  travelTypes: { value: 'Y' | null; label: string }[];
  transports: FormTransport[];
  cities: { cityId: string; cityName: string; upCityId: string; upCityName: string;
    countryId: string; provinceId: string; provinceName: string }[];
  demoOnly: boolean;
}

export interface ApplicationList {
  items: TravelApplication[];
  total: number;
  limit: number;
  offset: number;
}

export interface SubmissionReceipt {
  clientRequestId: string;
  createdAt: string;
  status: string;
  result: MockEnvelope<Record<string, unknown>>;
}

export interface IntegrationEvent {
  id: string;
  createdAt: string;
  source: string;
  method: string;
  path: string;
  httpStatus: number;
  code: string;
  durationMs: number;
  requestId: string | null;
}
