import { createContext, useContext, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { assistantApi } from '../api';
import type { ApiIssue, LifecycleDocument, LifecycleOptions, LifecyclePendingAction, LifecycleState, TravelApplication } from '../types';
import { errorMessage } from '../utils';
import { LifecycleEditor } from './LifecycleEditor';
import { TravelDocumentCard } from './TravelDocumentCard';
import { LifecycleDraftCard } from './LifecycleDraftCard';
import { DocumentActionDialog } from './DocumentActionDialog';

const PENDING_KEY = 'travelLifecyclePendingOperation';

type PendingOperation = {
  conversationId: string;
  kind: 'action' | 'submit' | 'recover';
  body: Record<string, unknown> & { clientRequestId: string };
};

const emptyState = (): LifecycleState => ({ documents: [], selectedDocument: null, draft: null, lastReceipt: null, querySummary: null });
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

function writePending(operation: PendingOperation) {
  localStorage.setItem(PENDING_KEY, JSON.stringify({ ...readPendingOperations(), [operation.conversationId]: operation }));
}

function unresolvedRequestId(value: LifecycleState) {
  if (value.lastReceipt?.status === 'UNKNOWN') return value.lastReceipt.clientRequestId;
  return value.draft?.requestId || null;
}

function terminalReceiptFor(value: LifecycleState, clientRequestId: string) {
  return value.lastReceipt?.clientRequestId === clientRequestId
    && ['SUCCEEDED', 'FAILED'].includes(value.lastReceipt.status)
    && !value.draft?.requestId;
}

type LifecycleContextValue = { conversationId: string | null; renderCards: (turnId?: string) => ReactNode; feedback: ReactNode };
const LifecycleContext = createContext<LifecycleContextValue | null>(null);
export function LifecycleCards({ turnId }: { turnId?: string }) { return useContext(LifecycleContext)?.renderCards(turnId) || null; }
export function LifecycleFeedback() { return useContext(LifecycleContext)?.feedback || null; }

type DocumentPanelProps = { conversationId: string | null; refreshToken: unknown; children?: ReactNode; busy?: boolean; latestTurnId?: string | null };

function DocumentPanelSession({ conversationId, refreshToken, busy = false, latestTurnId, publish }: DocumentPanelProps & { publish: (value: LifecycleContextValue) => void }) {
  const [proposal, setProposal] = useState<LifecyclePendingAction | null>(null);
  const [state, setState] = useState<LifecycleState>(emptyState);
  const [options, setOptions] = useState<LifecycleOptions | null>(null);
  const [optionsError, setOptionsError] = useState('');
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(false);
  const [issues, setIssues] = useState<ApiIssue[]>([]);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState<PendingOperation | null>(() => conversationId ? readPending(conversationId) : null);
  const requestRef = useRef(0);
  const loadingOwnerRef = useRef(0);
  const optionsRequestRef = useRef(0);
  const latestTurnRef = useRef(latestTurnId);
  latestTurnRef.current = latestTurnId;
  const localCardTurnsRef = useRef(new Map<string, string | null>());
  const submittingDraftRef = useRef(false);

  const beginLoading = () => {
    const owner = ++loadingOwnerRef.current;
    setLoading(true);
    return owner;
  };

  const endLoading = (owner: number) => {
    if (owner === loadingOwnerRef.current) setLoading(false);
  };

  const applyState = useCallback((next: LifecycleState, turnId = latestTurnRef.current) => {
    const owner = turnId === undefined ? next.cardGroups?.at(-1)?.turnId || null : turnId;
    const groups = next.cardGroups?.length ? next.cardGroups : [{ id: 'current', turnId: null }, { id: 'current-draft', turnId: null }];
    for (const group of groups) {
      if (group.turnId === null && !localCardTurnsRef.current.has(group.id)) localCardTurnsRef.current.set(group.id, owner);
    }
    setState(next);
  }, []);

  const restoreServerPending = useCallback((id: string, next: LifecycleState) => {
    const clientRequestId = unresolvedRequestId(next);
    if (!clientRequestId) return;
    setPending((current) => {
      if (current?.conversationId === id && current.body.clientRequestId === clientRequestId) return current;
      if (current?.conversationId === id) return current;
      const operation: PendingOperation = { conversationId: id, kind: 'recover', body: { clientRequestId } };
      writePending(operation);
      return operation;
    });
  }, []);

  const refresh = useCallback(async (id: string) => {
    const request = ++requestRef.current;
    const turnId = latestTurnRef.current;
    try {
      const next = await assistantApi.lifecycle(id);
      if (request === requestRef.current) {
        applyState(next, turnId);
        restoreServerPending(id, next);
        return next;
      }
    } catch (reason) {
      if (request === requestRef.current) setError(errorMessage(reason));
    }
    return null;
  }, [applyState, restoreServerPending]);

  useEffect(() => {
    if (!conversationId) { setState(emptyState()); setEditing(false); setPending(null); return; }
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
    const turnId = latestTurnRef.current;
    const loadingOwner = beginLoading();
    setError(''); setNotice(''); setIssues([]);
    try {
      const result = await operation();
      if (request !== requestRef.current) return result;
      applyState(result, turnId);
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

  async function prepare(doc: LifecycleDocument, mode: 'change' | 'resubmit') {
    if (!conversationId || pending || loading || busy) return;
    try { await run(() => assistantApi.lifecyclePrepare(conversationId, { reference: doc.applicationId, mode })); setEditing(true); }
    catch { /* shown above */ }
  }

  async function proposeAction(doc: LifecycleDocument, actionName: 'withdraw' | 'void') {
    if (!conversationId || pending || loading || busy) return;
    try {
      const previous = state.pendingAction;
      const next = await run(() => assistantApi.lifecycleProposeAction(conversationId, {
        reference: doc.applicationId, action: actionName,
        ...(previous?.targetDocument.applicationId === doc.applicationId && previous.action === actionName && previous.reason ? { reason: previous.reason } : {}),
      }));
      if (next?.pendingAction) setProposal(next.pendingAction);
    } catch { /* 展示资格或连接错误 */ }
  }

  async function cancelAction() {
    if (!conversationId || loading) return;
    try { await run(() => assistantApi.lifecycleCancelAction(conversationId)); setProposal(null); }
    catch { /* 保留弹窗便于重试 */ }
  }

  function remember(operation: PendingOperation) {
    writePending(operation);
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
    if (operation.kind === 'recover') return;
    const result = operation.kind === 'submit'
      ? await assistantApi.lifecycleSubmit(conversationId, operation.body as never)
      : await assistantApi.lifecycleAction(conversationId, operation.body as never);
    applyState(result);
    setEditing(Boolean(result.draft));
    if (!terminalReceiptFor(result, operation.body.clientRequestId)) {
      restoreServerPending(conversationId, result);
      setNotice(result.draft?.requestId ? '' : `办理结果待核对，已保留原请求号 ${operation.body.clientRequestId}。`);
      return;
    }
    forget(); setNotice('办理结果已同步。');
  }

  async function refreshAfterRecoveryError(reason: unknown, clientRequestId: string) {
    if (!conversationId) return;
    const latest = await refresh(conversationId);
    if (!latest) return;
    setEditing(Boolean(latest.draft));
    if (!terminalReceiptFor(latest, clientRequestId)) {
      restoreServerPending(conversationId, latest);
    } else {
      forget();
    }
    setError(errorMessage(reason));
  }

  async function syncAssistantReceipt(clientRequestId: string) {
    if (!conversationId) return;
    try {
      const result = await assistantApi.lifecycleRecover(conversationId);
      applyState(result);
      setEditing(Boolean(result.draft));
      if (!terminalReceiptFor(result, clientRequestId)) {
        restoreServerPending(conversationId, result);
        setNotice(`尚未取得原请求 ${clientRequestId} 的终态，已继续保留该请求号。`);
      } else {
        forget();
        setNotice('办理结果已同步。');
      }
    } catch (reason) {
      await refreshAfterRecoveryError(reason, clientRequestId);
    }
  }

  async function recover() {
    if (!pending || !conversationId) return;
    const loadingOwner = beginLoading(); setError(''); setNotice('');
    try {
      if (pending.kind === 'recover') {
        await syncAssistantReceipt(pending.body.clientRequestId);
        return;
      }
      const receipt = await assistantApi.lifecycleReceipt(pending.body.clientRequestId);
      if (receipt.data.status === 'FAILED' || receipt.data.status === 'SUCCEEDED') await syncAssistantReceipt(pending.body.clientRequestId);
      else await performPending(pending);
    } catch (reason) {
      const value = reason as { code?: string };
      if (value.code === 'RECEIPT_NOT_FOUND') {
        try { await performPending(pending); }
        catch (replayError) {
          if (isUnknown(replayError)) setNotice(`办理结果待核对，已保留原请求号 ${pending.body.clientRequestId}。`);
          else await refreshAfterRecoveryError(replayError, pending.body.clientRequestId);
        }
      } else { setError(errorMessage(reason)); }
    } finally { endLoading(loadingOwner); }
  }

  async function action(confirmation: LifecyclePendingAction, reason: string) {
    if (!conversationId || pending) return;
    const operation: PendingOperation = { conversationId, kind: 'action', body: {
      reference: confirmation.reference, action: confirmation.action, expectedVersion: confirmation.targetVersion, clientRequestId: crypto.randomUUID(), reason: reason || null,
    } };
    remember(operation); const loadingOwner = beginLoading(); setError('');
    try { await performPending(operation); setProposal(null); }
    catch (reason) {
      if (isUnknown(reason)) { setProposal(null); setNotice('结果待核对。原请求号已保留，继续办理时会先查询回执。'); }
      else { forget(); setError(errorMessage(reason)); await refresh(conversationId); }
    } finally { endLoading(loadingOwner); }
  }

  async function saveDraft(payload: TravelApplication['request']) {
    if (!conversationId || !state.draft || pending || loading || busy) return;
    try { await run(() => assistantApi.lifecycleSave(conversationId, { draftId: state.draft!.id, revision: state.draft!.revision, payload })); }
    catch { /* issues and fresh eligibility already loaded */ }
  }

  async function submitDraft(payload: TravelApplication['request']) {
    if (!conversationId || !state.draft || pending || loading || busy || submittingDraftRef.current) return;
    submittingDraftRef.current = true;
    const source = state.draft;
    const request = ++requestRef.current;
    const turnId = latestTurnRef.current;
    const loadingOwner = beginLoading();
    let operation: PendingOperation | null = null;
    setError(''); setNotice(''); setIssues([]);
    try {
      let current = source;
      if (JSON.stringify(payload) !== JSON.stringify(source.payload)) {
        const saved = await assistantApi.lifecycleSave(conversationId, { draftId: source.id, revision: source.revision, payload });
        if (request !== requestRef.current || turnId !== latestTurnRef.current) return;
        if (!saved.draft || saved.draft.id !== source.id || saved.draft.revision <= source.revision
          || saved.draft.targetId !== source.targetId || saved.draft.targetVersion !== source.targetVersion) {
          throw new Error('尚未取得本次编辑的新草稿，请核对内容后重新保存。');
        }
        applyState(saved, turnId);
        current = saved.draft;
      }
      if (current.requestId || current.targetId !== current.targetDocument.applicationId
        || current.targetVersion !== current.targetDocument.version || !current.targetDocument.actions[current.mode].allowed) {
        throw new Error('当前单据已变化，请核对最新内容后提交。');
      }
      operation = { conversationId, kind: 'submit', body: {
        draftId: current.id, revision: current.revision, fingerprint: current.fingerprint, clientRequestId: crypto.randomUUID(),
      } };
      remember(operation);
      await performPending(operation);
    }
    catch (reason) {
      if (operation && isUnknown(reason)) setNotice('结果待核对。编辑内容和原请求号已保留，请先查询回执。');
      else {
        if (operation) forget();
        const value = reason as { issues?: ApiIssue[]; code?: string };
        if (value.issues?.length) setIssues(value.issues);
        setError(errorMessage(reason));
        if (operation || ['CONFIRMATION_STALE', 'ACTION_NOT_ALLOWED'].includes(value.code || '')) await refresh(conversationId);
      }
    } finally { submittingDraftRef.current = false; endLoading(loadingOwner); }
  }

  const feedback = !editing && !proposal && (pending || error) ? <div className="lifecycle-feedback message-bubble" role="status">
    {error && <p>{error}</p>}
    {pending && <><p>{notice || '办理结果待核对，请查询原请求结果。'}</p>
      <button type="button" onClick={() => void recover()} disabled={loading || busy}>查询办理结果</button></>}
  </div> : null;

  function renderCards(turnId?: string) {
    let groups = (state.cardGroups || []).filter((group) => turnId ? group.turnId === turnId : group.turnId === null);
    if (!turnId && !state.cardGroups?.length) {
      const docs = [...state.documents];
      if (state.selectedDocument && !docs.some((d) => d.applicationId === state.selectedDocument!.applicationId)) docs.push(state.selectedDocument);
      if (docs.length || state.querySummary) groups = [{ id: 'current', turnId: null, title: '相关差旅单据', documents: docs, total: state.querySummary?.total ?? null }];
      if (state.draft) groups.push({ id: 'current-draft', turnId: null, kind: 'draft', title: '当前编辑草稿', documents: [], total: null, draft: state.draft });
    }
    const currentTurn = latestTurnId === undefined ? state.cardGroups?.at(-1)?.turnId || null : latestTurnId;
    return groups.map((group) => {
      // turnId controls placement; interactionTurnId preserves UI operations' origin across reloads.
      const current = group.interactionTurnId !== undefined ? group.interactionTurnId === currentTurn
        : group.turnId !== null ? group.turnId === currentTurn
        : !state.cardGroups?.length && localCardTurnsRef.current.get(group.id) === currentTurn;
      const snapshot = group.kind === 'draft' ? group.draft : null;
      const currentDraft = Boolean(current && snapshot && state.draft?.id === snapshot.id && state.draft.revision === snapshot.revision);
      const documents = group.documents.filter((doc) => !doc.isSuperseded).slice(0, 3);
      return <section className="travel-document-group" aria-label={group.title} key={group.id}>
        <div className="travel-document-group-heading">{group.title}{group.total != null && <span>{group.total} 张</span>}</div>
        {snapshot ? <LifecycleDraftCard draft={currentDraft ? state.draft! : snapshot} options={options} current={currentDraft}
          busy={loading || busy || Boolean(pending)} onEdit={() => setEditing(true)} onSubmit={() => setEditing(true)} /> : <>
          {!documents.length && <p className="document-empty">没有找到相关单据，可以换个时间或城市继续问我。</p>}
          {documents.map((doc) => <TravelDocumentCard key={doc.applicationId} doc={doc} options={options}
            current={current && group.kind !== 'draft'}
            busy={loading || busy || Boolean(pending)} onAction={(target, name) => void proposeAction(target, name)} onPrepare={(target, mode) => void prepare(target, mode)} />)}
          {(group.total || 0) > 3 && <button type="button" className="query-all-button" title="演示入口">查看全部查询结果</button>}
        </>}
      </section>;
    });
  }

  useLayoutEffect(() => {
    publish({ conversationId, renderCards, feedback });
  }, [conversationId, state, options, loading, busy, latestTurnId, pending, error, notice, editing, proposal, publish]);

  return <>
    {typeof document !== 'undefined' && createPortal(<>
      {proposal && <DocumentActionDialog key={proposal.id} proposal={proposal} busy={loading || busy || Boolean(pending)} error={error}
        onCancel={() => void cancelAction()} onConfirm={(reason) => void action(proposal, reason)} />}
      {state.draft && <LifecycleEditor draft={state.draft} options={options} open={editing} busy={loading || busy} locked={Boolean(pending)}
        pendingRequestId={pending?.body.clientRequestId} pendingMessage={notice} optionsError={optionsError} optionsLoading={optionsLoading} issues={issues} generalError={error}
        onRecover={() => void recover()}
        onClose={() => setEditing(false)} onCancel={() => conversationId && !pending && void run(() => assistantApi.lifecycleCancelDraft(conversationId), false)}
        onSave={(payload) => void saveDraft(payload)} onSubmit={(payload) => void submitDraft(payload)} onRetryOptions={() => void loadOptions()} />}
    </>, document.body)}
  </>;
}

export function DocumentPanel(props: DocumentPanelProps) {
  const [context, setContext] = useState<LifecycleContextValue | null>(null);
  return <LifecycleContext.Provider value={context?.conversationId === props.conversationId ? context : null}>
    <DocumentPanelSession key={props.conversationId || 'no-conversation'} {...props} publish={setContext} />
    {props.children || <><LifecycleCards /><LifecycleFeedback /></>}
  </LifecycleContext.Provider>;
}
