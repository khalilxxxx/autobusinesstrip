import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertCircle, ArrowRight, CalendarDays, ChevronDown, FileSearch, LoaderCircle, RefreshCw, Search, X } from 'lucide-react';
import { assistantApi } from '../api';
import type { ApiIssue, LifecycleDocument, LifecycleOptions, LifecycleQueryFilters, LifecycleState, TravelApplication } from '../types';
import { errorMessage, formatDateTime } from '../utils';
import { LifecycleEditor } from './LifecycleEditor';

const PENDING_KEY = 'travelLifecyclePendingOperation';

type PendingOperation = {
  conversationId: string;
  kind: 'action' | 'submit';
  body: Record<string, unknown> & { clientRequestId: string };
};

const emptyState = (): LifecycleState => ({ documents: [], selectedDocument: null, draft: null, lastReceipt: null, querySummary: null });
const statusNames: Record<string, string> = {
  UNKNOWN: '待核对', S002: '待审批', S003: '审批中', S004: '审批完成', S005: '已撤回／退回', S100: '已作废',
};
const historyNames: Record<string, string> = {
  create: '创建并提交', change: '提交行程变更', resubmit: '编辑后重新提交', withdraw: '员工撤回',
  void: '员工作废', start: '开始审批', complete: '审批完成', return: '审批退回',
};

function isUnknown(reason: unknown) {
  const value = reason as { code?: string; status?: number };
  return value?.code === 'NETWORK_ERROR' || (value?.code === 'INVALID_RESPONSE' && !(value.status && value.status >= 400 && value.status < 500));
}

function readPendingOperations(): Record<string, PendingOperation> {
  try {
    const value = JSON.parse(localStorage.getItem(PENDING_KEY) || '{}') as unknown;
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    const legacy = value as Partial<PendingOperation>;
    if (typeof legacy.conversationId === 'string' && legacy.body && legacy.kind) {
      return { [legacy.conversationId]: legacy as PendingOperation };
    }
    return value as Record<string, PendingOperation>;
  } catch { return {}; }
}

function readPending(conversationId: string): PendingOperation | null {
  return readPendingOperations()[conversationId] || null;
}

function cityLabel(options: LifecycleOptions | null, cityId: string) {
  return options?.cities.find((city) => city.cityId === cityId)?.cityName || cityId;
}

function efficacy(doc: LifecycleDocument) {
  if (doc.status === 'UNKNOWN') return '效力待核对';
  if (doc.isEffective && doc.tflag === 'YBG') return '当前有效 · 有在途变更';
  if (doc.isEffective) return '当前有效';
  if (doc.documentType === 'CHANGE' && ['S002', 'S003', 'S005'].includes(doc.status)) return '在途变更 · 尚未生效';
  return '当前未生效';
}

type DocumentPanelProps = { conversationId: string | null; refreshToken: unknown };

function DocumentPanelSession({ conversationId, refreshToken }: DocumentPanelProps) {
  const [open, setOpen] = useState(false);
  const [queryOpen, setQueryOpen] = useState(false);
  const [state, setState] = useState<LifecycleState>(emptyState);
  const [selected, setSelected] = useState<LifecycleDocument | null>(null);
  const [options, setOptions] = useState<LifecycleOptions | null>(null);
  const [optionsError, setOptionsError] = useState('');
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [issues, setIssues] = useState<ApiIssue[]>([]);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState<PendingOperation | null>(() => conversationId ? readPending(conversationId) : null);
  const [filters, setFilters] = useState<LifecycleQueryFilters>({ dateBasis: 'trip', temporal: 'future', effectiveOnly: false });
  const requestRef = useRef(0);
  const loadingOwnerRef = useRef(0);
  const optionsRequestRef = useRef(0);

  const beginLoading = () => {
    const owner = ++loadingOwnerRef.current;
    setLoading(true);
    return owner;
  };

  const endLoading = (owner: number) => {
    if (owner === loadingOwnerRef.current) setLoading(false);
  };

  const applyState = useCallback((next: LifecycleState) => {
    setState(next);
    setSelected((current) => next.selectedDocument
      || next.documents.find((item) => item.applicationId === current?.applicationId)
      || (current && next.draft?.targetDocument.applicationId === current.applicationId ? next.draft.targetDocument : null));
  }, []);

  const refresh = useCallback(async (id: string) => {
    const request = ++requestRef.current;
    try {
      const next = await assistantApi.lifecycle(id);
      if (request === requestRef.current) applyState(next);
    } catch (reason) {
      if (request === requestRef.current) setError(errorMessage(reason));
    }
  }, [applyState]);

  useEffect(() => {
    if (!conversationId) { setState(emptyState()); setSelected(null); setEditing(false); setPending(null); return; }
    setPending(readPending(conversationId));
    void refresh(conversationId);
  }, [conversationId, refreshToken, refresh]);

  const loadOptions = useCallback(async () => {
    const request = ++optionsRequestRef.current;
    setOptionsLoading(true); setOptionsError('');
    try {
      const result = await assistantApi.lifecycleOptions();
      if (request === optionsRequestRef.current) setOptions(result.data);
    } catch (reason) {
      if (request === optionsRequestRef.current) setOptionsError(errorMessage(reason));
    } finally {
      if (request === optionsRequestRef.current) setOptionsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadOptions();
    return () => { ++optionsRequestRef.current; };
  }, [loadOptions]);

  const run = async (operation: () => Promise<LifecycleState>, preserveEditor = true) => {
    const request = ++requestRef.current;
    const loadingOwner = beginLoading();
    setError(''); setNotice(''); setIssues([]);
    try {
      const result = await operation();
      if (request !== requestRef.current) return result;
      applyState(result);
      if (!preserveEditor) setEditing(false);
      return result;
    } catch (reason) {
      const value = reason as { issues?: ApiIssue[]; code?: string };
      if (request !== requestRef.current) throw reason;
      if (value.issues?.length) setIssues(value.issues);
      setError(errorMessage(reason));
      if (conversationId && ['CONFIRMATION_STALE', 'ACTION_NOT_ALLOWED'].includes(value.code || '')) await refresh(conversationId);
      throw reason;
    } finally {
      endLoading(loadingOwner);
    }
  };

  async function query(event: FormEvent) {
    event.preventDefault(); if (!conversationId) return;
    try { await run(() => assistantApi.lifecycleQuery(conversationId, filters)); }
    catch { /* error state already preserves both editors */ }
  }

  async function prepare(doc: LifecycleDocument, mode: 'change' | 'resubmit') {
    if (!conversationId || pending) return;
    try { await run(() => assistantApi.lifecyclePrepare(conversationId, { reference: doc.applicationId, mode })); setEditing(true); }
    catch { /* shown above */ }
  }

  async function selectDocument(doc: LifecycleDocument) {
    setSelected(doc);
    if (!conversationId) return;
    try { await run(() => assistantApi.lifecycleDetail(conversationId, doc.applicationId)); }
    catch { /* 本地选择保留，错误已显示 */ }
  }

  function remember(operation: PendingOperation) {
    localStorage.setItem(PENDING_KEY, JSON.stringify({ ...readPendingOperations(), [operation.conversationId]: operation }));
    setPending(operation);
  }

  function forget() {
    if (conversationId) {
      const operations = readPendingOperations();
      delete operations[conversationId];
      if (Object.keys(operations).length) localStorage.setItem(PENDING_KEY, JSON.stringify(operations));
      else localStorage.removeItem(PENDING_KEY);
    }
    setPending(null);
  }

  async function performPending(operation: PendingOperation) {
    if (!conversationId) return;
    const result = operation.kind === 'submit'
      ? await assistantApi.lifecycleSubmit(conversationId, operation.body as never)
      : await assistantApi.lifecycleAction(conversationId, operation.body as never);
    applyState(result); forget(); setEditing(Boolean(result.draft)); setNotice('办理结果已同步。');
  }

  async function recover() {
    if (!pending || !conversationId) return;
    const loadingOwner = beginLoading(); setError(''); setNotice('');
    try {
      const receipt = await assistantApi.lifecycleReceipt(pending.body.clientRequestId);
      if (receipt.data.status === 'FAILED') {
        forget(); await refresh(conversationId); setError(String(receipt.data.result.message || '办理失败，请核对单据状态。')); return;
      }
      await performPending(pending);
    } catch (reason) {
      const value = reason as { code?: string };
      if (value.code === 'RECEIPT_NOT_FOUND') {
        try { await performPending(pending); } catch (replayError) { setError(errorMessage(replayError)); }
      } else { setError(errorMessage(reason)); }
    } finally { endLoading(loadingOwner); }
  }

  async function action(doc: LifecycleDocument, actionName: 'withdraw' | 'void') {
    if (!conversationId || pending) return;
    const operation: PendingOperation = { conversationId, kind: 'action', body: {
      reference: doc.applicationId, action: actionName, expectedVersion: doc.version, clientRequestId: crypto.randomUUID(),
    } };
    remember(operation); const loadingOwner = beginLoading(); setError('');
    try { await performPending(operation); }
    catch (reason) {
      if (isUnknown(reason)) setNotice('结果待核对。原请求号已保留，继续办理时会先查询回执。');
      else { forget(); setError(errorMessage(reason)); await refresh(conversationId); }
    } finally { endLoading(loadingOwner); }
  }

  async function saveDraft(payload: TravelApplication['request']) {
    if (!conversationId || !state.draft || pending) return;
    try { await run(() => assistantApi.lifecycleSave(conversationId, { draftId: state.draft!.id, revision: state.draft!.revision, payload })); }
    catch { /* issues and fresh eligibility already loaded */ }
  }

  async function submitDraft() {
    if (!conversationId || !state.draft || pending) return;
    const operation: PendingOperation = { conversationId, kind: 'submit', body: {
      draftId: state.draft.id, revision: state.draft.revision, fingerprint: state.draft.fingerprint, clientRequestId: crypto.randomUUID(),
    } };
    remember(operation); const loadingOwner = beginLoading(); setError('');
    try { await performPending(operation); }
    catch (reason) {
      if (isUnknown(reason)) setNotice('结果待核对。编辑内容和原请求号已保留，请先查询回执。');
      else { forget(); setError(errorMessage(reason)); await refresh(conversationId); }
    } finally { endLoading(loadingOwner); }
  }

  const shownDocuments = useMemo(() => state.documents.filter((item) => !item.isSuperseded), [state.documents]);
  const draftTarget = state.draft?.targetDocument;

  return <>
    <div className="document-panel-entry">
      <button type="button" onClick={() => { setOpen(true); setQueryOpen(true); }} disabled={!conversationId}>
        <FileSearch />查询单据
      </button>
      {state.draft && <button type="button" onClick={() => { setOpen(true); setEditing(true); }}>
        继续编辑{state.draft.mode === 'change' ? '变更' : '重提'}
      </button>}
      {pending && <button type="button" className="pending" onClick={() => { setOpen(true); void recover(); }} disabled={loading}>查询办理结果</button>}
    </div>
    {typeof document !== 'undefined' && createPortal(<>
    {open && <aside className="document-panel" aria-label="单据查询与办理">
      <header><div><strong>我的差旅单据</strong><small>查询、核对并办理当前可见单据</small></div><button type="button" aria-label="关闭单据面板" onClick={() => setOpen(false)}><X /></button></header>
      <div className="document-panel-toolbar"><button type="button" onClick={() => setQueryOpen((value) => !value)}><Search />查询条件<ChevronDown /></button>
        <button type="button" aria-label="刷新单据" onClick={() => conversationId && void refresh(conversationId)} disabled={loading}><RefreshCw className={loading ? 'spin' : ''} /></button></div>
      {queryOpen && <form className="document-query" onSubmit={query}>
        <label>查询范围<select aria-label="历史当前未来" value={filters.temporal || ''} onChange={(event) => setFilters({ ...filters, temporal: event.target.value as LifecycleQueryFilters['temporal'] || undefined })}>
          <option value="">全部日期</option><option value="past">历史差旅</option><option value="current">当前差旅</option><option value="future">未来差旅</option></select></label>
        <label>日期口径<select aria-label="行程或提交日期" value={filters.dateBasis} onChange={(event) => setFilters({ ...filters, dateBasis: event.target.value as 'trip' | 'submitted' })}>
          <option value="trip">行程日期</option><option value="submitted">提交日期</option></select></label>
        <label>开始日期<input type="date" value={filters.dateFrom || ''} onChange={(event) => setFilters({ ...filters, dateFrom: event.target.value || undefined })} /></label>
        <label>结束日期<input type="date" value={filters.dateTo || ''} onChange={(event) => setFilters({ ...filters, dateTo: event.target.value || undefined })} /></label>
        <label>城市<input aria-label="查询城市" value={filters.city || ''} onChange={(event) => setFilters({ ...filters, city: event.target.value || undefined })} placeholder="如上海、杭州" /></label>
        <label>状态<select aria-label="单据状态" value={filters.status || ''} onChange={(event) => setFilters({ ...filters, status: event.target.value || undefined })}>
          <option value="">全部状态</option><option value="S002">待审批</option><option value="S003">审批中</option><option value="S004">审批完成</option><option value="S005">已撤回／退回</option><option value="S100">已作废</option></select></label>
        <label className="query-check"><input type="checkbox" checked={Boolean(filters.effectiveOnly)} onChange={(event) => setFilters({ ...filters, effectiveOnly: event.target.checked })} />仅当前有效</label>
        <button type="submit" disabled={loading || !conversationId}>{loading ? <LoaderCircle className="spin" /> : <Search />}开始查询</button>
      </form>}
      {error && <p className="document-error"><AlertCircle />{error}</p>}
      {notice && <p className="document-notice"><AlertCircle />{notice}</p>}
      {state.lastReceipt?.result.documentResolvedToCurrent && <p className="document-notice">已找到原操作回执；下方展示的是当前可见内容，并非历史提交快照。</p>}
      <div className="document-panel-body">
        <div className="document-results"><div className="document-results-title"><span>{state.querySummary ? `查询到 ${state.querySummary.total} 张` : '查询结果会保留在这里'}</span></div>
          {!shownDocuments.length ? <p className="document-empty">暂无符合条件的当前可见单据。</p> : shownDocuments.map((doc) => <button type="button" key={doc.applicationId}
            className={selected?.applicationId === doc.applicationId ? 'active' : ''} onClick={() => void selectDocument(doc)} aria-label={`打开单据 ${doc.applicationNo}`}>
            <strong>{doc.applicationNo}</strong><span>{doc.documentType === 'CHANGE' ? '行程变更单' : '差旅申请单'} · {statusNames[doc.status] || doc.status}</span>
            <small><CalendarDays />{doc.tripStart} 至 {doc.tripEnd}</small><em>{efficacy(doc)}</em>
          </button>)}</div>
        <div className="document-detail">{!selected ? <div className="document-empty-detail"><FileSearch /><strong>选择一张单据查看详情</strong><p>不会显示已被替代的旧版，也不提供历史还原入口。</p></div> : <>
          <div className="document-detail-heading"><div><small>{selected.documentType === 'CHANGE' ? '行程变更单' : '差旅申请单'}</small><strong>{selected.applicationNo}</strong></div>
            <span>{statusNames[selected.status] || selected.status}</span></div>
          <div className="document-tags"><span>{efficacy(selected)}</span>{selected.pendingChangeId && <span>在途变更处理中</span>}</div>
          <dl className="document-summary"><div><dt>行程日期</dt><dd>{selected.tripStart} 至 {selected.tripEnd}</dd></div><div><dt>提交日期</dt><dd>{formatDateTime(selected.submittedAt)}</dd></div>
            <div><dt>事由</dt><dd>{selected.request.remark}</dd></div><div><dt>差旅类型</dt><dd>{selected.request.dqydbg === 'Y' ? '短期异地办公' : '普通差旅'}</dd></div></dl>
          <h3>路线</h3><div className="document-routes">{selected.request.trips.map((trip, index) => <div key={index}><span>{index + 1}</span><strong>{cityLabel(options, trip.cityFrom)} <ArrowRight /> {cityLabel(options, trip.cityTo)}</strong><small>{trip.dateFrom}{trip.dateTo !== trip.dateFrom ? ` 至 ${trip.dateTo}` : ''} · {trip.tool}</small></div>)}</div>
          {selected.stay?.description && <p className="document-stay">{selected.stay.date}：{selected.stay.description}</p>}
          <h3>办理操作</h3><div className="document-actions">
            <button type="button" disabled={!selected.actions.withdraw.allowed || loading || Boolean(pending)} title={selected.actions.withdraw.reason || ''} onClick={() => void action(selected, 'withdraw')}>撤回本次提交</button>
            <button type="button" disabled={!selected.actions.change.allowed || loading || Boolean(pending)} title={selected.actions.change.reason || ''} onClick={() => void prepare(selected, 'change')}>发起行程变更</button>
            <button type="button" disabled={!selected.actions.resubmit.allowed || loading || Boolean(pending)} title={selected.actions.resubmit.reason || ''} onClick={() => void prepare(selected, 'resubmit')}>编辑后重新提交</button>
            <button type="button" className="danger" disabled={!selected.actions.void.allowed || loading || Boolean(pending)} title={selected.actions.void.reason || ''} onClick={() => void action(selected, 'void')}>
              {selected.documentType === 'CHANGE' && selected.status === 'S005' ? '作废本次未生效变更' : '作废当前有效单据'}
            </button>
          </div><div className="action-reasons">{Object.entries(selected.actions).filter(([, value]) => !value.allowed && value.reason).map(([name, value]) => <p key={name}>{({ withdraw: '撤回', change: '变更', resubmit: '重提', void: '作废' } as Record<string, string>)[name]}：{value.reason}</p>)}</div>
          <h3>办理历史</h3><ol className="document-history">{selected.history.map((item, index) => <li key={`${item.at}-${index}`}><strong>{historyNames[item.action] || item.action}</strong><span>{formatDateTime(item.at)} · {statusNames[item.toStatus] || item.toStatus}</span></li>)}</ol>
        </>}</div>
      </div>
      {draftTarget && !editing && <div className="document-draft-banner"><span>正在编辑 {draftTarget.applicationNo}，草稿尚未提交、尚未生效。</span><button type="button" onClick={() => setEditing(true)}>继续编辑</button></div>}
    </aside>}
    {state.draft && <LifecycleEditor draft={state.draft} options={options} open={editing} busy={loading} locked={Boolean(pending)}
      pendingRequestId={pending?.body.clientRequestId} optionsError={optionsError} optionsLoading={optionsLoading} issues={issues}
      onClose={() => setEditing(false)} onCancel={() => conversationId && !pending && void run(() => assistantApi.lifecycleCancelDraft(conversationId), false)}
      onSave={(payload) => void saveDraft(payload)} onSubmit={() => void submitDraft()} onRetryOptions={() => void loadOptions()} />}
    </>, document.body)}
  </>;
}

export function DocumentPanel(props: DocumentPanelProps) {
  return <DocumentPanelSession key={props.conversationId || 'no-conversation'} {...props} />;
}
