import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertCircle, ArrowRight, Bot, CheckCircle2, Clock3, History, LoaderCircle,
  Menu, MessageSquarePlus, PanelLeftClose, RefreshCw, Send, Server, Sparkles, Trash2, UserRound, X,
} from 'lucide-react';
import { assistantApi } from '../api';
import type {
  ApiIssue, AssistantStatus, ConversationDetail, ConversationState, ConversationSummary,
  DraftEdits, DraftView, Turn,
} from '../types';
import { canConfirmDraft, errorMessage, formatDateTime, phaseLabel } from '../utils';
import { MarkdownMessage } from './MarkdownMessage';
import { DraftCard } from './DraftCard';
import { DraftDrawer } from './DraftDrawer';
import { DeleteConversationDialog } from './DeleteConversationDialog';
import { DocumentPanel } from './DocumentPanel';

const examples = [
  '我下周一从杭州去桐庐拜访客户，当天高铁往返。',
  '10 月 18 日从上海虹桥到广州出差，20 日返回，坐飞机经济舱。',
  '我想申请下周去昆山出差，还缺哪些信息？',
];

const draftReplyGuidance = '你可以直接回复补充或修改信息，也可以点击“编辑申请”填写表单。';

interface OptimisticMessage {
  content: string;
  requestId: string;
}

interface PendingDraftSubmission {
  conversationId: string;
  clientRequestId: string;
  draftId: string;
  revision: number;
  edits: DraftEdits;
}

function sameDraft(left?: ConversationState | null, right?: ConversationState | null) {
  return Boolean(left?.draft && right?.draft
    && left.draft.draftId === right.draft.draftId
    && left.draft.revision === right.draft.revision);
}

function errorDetails(reason: unknown): { code?: string; status?: number; issues?: ApiIssue[] } {
  return typeof reason === 'object' && reason !== null
    ? reason as { code?: string; status?: number; issues?: ApiIssue[] }
    : {};
}

function isUnknownSubmissionResult(reason: unknown): boolean {
  const details = errorDetails(reason);
  if (details.code === 'NETWORK_ERROR') return true;
  return details.code === 'INVALID_RESPONSE'
    && !(typeof details.status === 'number' && details.status >= 400 && details.status < 500);
}

export function AssistantPage() {
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [activeTurn, setActiveTurn] = useState<Turn | null>(null);
  const [optimistic, setOptimistic] = useState<OptimisticMessage | null>(null);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [postingByConversation, setPostingByConversation] = useState<Record<string, string>>({});
  const [pollEpoch, setPollEpoch] = useState(0);
  const [error, setError] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [composing, setComposing] = useState(false);
  const [editingDraft, setEditingDraft] = useState<DraftView | null>(null);
  const [drawerIssues, setDrawerIssues] = useState<ApiIssue[]>([]);
  const [pendingDraftSubmission, setPendingDraftSubmission] = useState<PendingDraftSubmission | null>(null);
  const [unknownConfirmation, setUnknownConfirmation] = useState<{ conversationId: string; clientRequestId: string } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ConversationSummary | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const deleteInFlightRef = useRef(false);
  const deletedIdsRef = useRef(new Set<string>());
  const selectedConversationRef = useRef<string | null>(null);
  const viewGenerationRef = useRef(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const focusBeforeDrawerRef = useRef<HTMLElement | null>(null);

  function currentDraftSubmission() {
    const draft = conversation?.state.draft;
    return draft && pendingDraftSubmission
      && pendingDraftSubmission.conversationId === conversation?.id
      && pendingDraftSubmission.draftId === draft.draftId
      && pendingDraftSubmission.revision === draft.revision
      ? pendingDraftSubmission : null;
  }

  function openDraftEditor() {
    const draft = conversation?.state.draft;
    if (!draft) return;
    const pending = currentDraftSubmission();
    focusBeforeDrawerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setError('');
    setDrawerIssues([]);
    setEditingDraft(pending ? { ...draft, ...pending.edits, editTrips: pending.edits.trips } : draft);
  }

  function submitCurrentCard() {
    if (!conversation) return;
    const pending = currentDraftSubmission();
    if (pending) { void submitDraft(pending.edits); return; }
    const existingRequestId = unknownConfirmation?.conversationId === conversation.id
      ? unknownConfirmation.clientRequestId : undefined;
    void send('确认提交', true, existingRequestId);
  }

  const loadList = useCallback(async (preferredId?: string) => {
    const result = await assistantApi.conversations();
    const items = result.items.filter((item) => !deletedIdsRef.current.has(item.id));
    setConversations(items);
    return items.find((item) => item.id === preferredId)?.id || items[0]?.id || null;
  }, []);

  const loadConversation = useCallback(async (id: string, generation = viewGenerationRef.current) => {
    const detail = await assistantApi.conversation(id);
    if (selectedConversationRef.current !== id || generation !== viewGenerationRef.current || deletedIdsRef.current.has(id)) return detail;
    setConversation(detail);
    if (detail.activeTurnId) {
      setActiveTurn((current) => current?.id === detail.activeTurnId ? current : {
        id: detail.activeTurnId!, conversationId: detail.id, status: 'running', answer: null, error: null,
      });
      setPollEpoch((current) => current + 1);
    } else {
      setActiveTurn(null);
    }
    return detail;
  }, []);

  const initialise = useCallback(async () => {
    setLoading(true);
    setError('');
    const [statusResult, listResult] = await Promise.allSettled([
      assistantApi.status(), assistantApi.conversations(),
    ]);
    if (statusResult.status === 'fulfilled') setStatus(statusResult.value);
    if (listResult.status === 'fulfilled') {
      const items = listResult.value.items.filter((item) => !deletedIdsRef.current.has(item.id));
      setConversations(items);
      const preferredId = selectedConversationRef.current;
      const target = items.find((item) => item.id === preferredId) || items[0];
      if (target) {
        const generation = ++viewGenerationRef.current;
        selectedConversationRef.current = target.id;
        try { await loadConversation(target.id, generation); } catch (reason) { setError(errorMessage(reason)); }
      } else {
        ++viewGenerationRef.current;
        selectedConversationRef.current = null;
        setConversation(null);
        setActiveTurn(null);
      }
    }
    const failure = [statusResult, listResult].find((result) => result.status === 'rejected');
    if (failure?.status === 'rejected') setError(errorMessage(failure.reason));
    setLoading(false);
  }, [loadConversation]);

  useEffect(() => { void initialise(); }, [initialise]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [conversation?.messages.length, activeTurn?.answer, optimistic]);

  useEffect(() => {
    if (!activeTurn || activeTurn.status !== 'running') return;
    let cancelled = false;
    let timer: number | undefined;
    const turnId = activeTurn.id;
    const conversationId = activeTurn.conversationId;
    const generation = viewGenerationRef.current;
    const isCurrentView = () => selectedConversationRef.current === conversationId
      && viewGenerationRef.current === generation;

    const poll = async () => {
      try {
        const turn = await assistantApi.turn(turnId);
        if (cancelled || !isCurrentView()) return;
        if (turn.status === 'running') {
          setActiveTurn(turn);
          timer = window.setTimeout(poll, 900);
          return;
        }
        const [detailResult, listResult] = await Promise.allSettled([
          assistantApi.conversation(conversationId), assistantApi.conversations(),
        ]);
        if (cancelled || !isCurrentView()) return;
        if (listResult.status === 'fulfilled') setConversations(listResult.value.items.filter((item) => !deletedIdsRef.current.has(item.id)));
        if (detailResult.status === 'rejected') {
          setActiveTurn(turn);
          setError(`本轮结果已收到，但会话刷新失败：${errorMessage(detailResult.reason)} 请点击“重新连接”同步。`);
          return;
        }
        setConversation(detailResult.value);
        setOptimistic(null);
        setActiveTurn(null);
        if (turn.status !== 'succeeded') {
          const turnError = typeof turn.error === 'string' ? turn.error : turn.error?.message;
          setError(turnError || (turn.status === 'uncertain'
            ? '提交结果暂时不确定。请保留当前页面并重新检查会话，系统不会自动重复提交。'
            : '本轮处理失败，请核对信息后重试。'));
        } else if (listResult.status === 'rejected') {
          setError(`会话已更新，但历史列表刷新失败：${errorMessage(listResult.reason)}`);
        } else {
          setError('');
        }
      } catch (reason) {
        if (cancelled || !isCurrentView()) return;
        setError(`${errorMessage(reason)} 正在继续检查本轮状态。`);
        timer = window.setTimeout(poll, 2200);
      }
    };
    void poll();
    return () => { cancelled = true; if (timer) window.clearTimeout(timer); };
  }, [activeTurn?.id, activeTurn?.status, pollEpoch]);

  async function createConversation(): Promise<ConversationDetail | null> {
    if (creating || deleteTarget || deleteInFlightRef.current) return null;
    const requestGeneration = viewGenerationRef.current;
    setCreating(true);
    setError('');
    try {
      const detail = await assistantApi.createConversation();
      await loadList(detail.id);
      if (requestGeneration !== viewGenerationRef.current) return null;
      const generation = ++viewGenerationRef.current;
      selectedConversationRef.current = detail.id;
      setConversation(detail);
      setActiveTurn(null);
      setOptimistic(null);
      setInput('');
      setSidebarOpen(false);
      setEditingDraft(null);
      setDrawerIssues([]);
      if (generation !== viewGenerationRef.current) return null;
      return detail;
    } catch (reason) {
      if (requestGeneration === viewGenerationRef.current) setError(errorMessage(reason));
      return null;
    } finally {
      setCreating(false);
    }
  }

  async function selectConversation(id: string) {
    if (deleteTarget || deleteInFlightRef.current || deletedIdsRef.current.has(id)) return;
    if (id === selectedConversationRef.current) { setSidebarOpen(false); return; }
    const generation = ++viewGenerationRef.current;
    selectedConversationRef.current = id;
    setLoading(true);
    setError('');
    setActiveTurn(null);
    setOptimistic(null);
    setEditingDraft(null);
    setDrawerIssues([]);
    try { await loadConversation(id, generation); }
    catch (reason) {
      if (generation === viewGenerationRef.current) setError(errorMessage(reason));
    } finally {
      if (generation === viewGenerationRef.current) setLoading(false);
      setSidebarOpen(false);
    }
  }

  async function deleteConversation() {
    const target = deleteTarget;
    if (!target || deleteInFlightRef.current) return;
    deleteInFlightRef.current = true;
    setDeletingId(target.id);
    setDeleteError('');
    try {
      await assistantApi.deleteConversation(target.id);
      deletedIdsRef.current.add(target.id);
      const remaining = conversations.filter((item) => !deletedIdsRef.current.has(item.id));
      setConversations((current) => current.filter((item) => !deletedIdsRef.current.has(item.id)));
      setUnknownConfirmation((current) => current?.conversationId === target.id ? null : current);
      setPendingDraftSubmission((current) => current?.conversationId === target.id ? null : current);
      if (selectedConversationRef.current === target.id) {
        const generation = ++viewGenerationRef.current;
        const nextId = remaining[0]?.id || null;
        selectedConversationRef.current = nextId;
        setConversation(null);
        setActiveTurn(null);
        setOptimistic(null);
        setInput('');
        setError('');
        setEditingDraft(null);
        setDrawerIssues([]);
        setSidebarOpen(false);
        setLoading(Boolean(nextId));
        try {
          if (nextId) await loadConversation(nextId, generation);
        } catch (reason) {
          if (generation === viewGenerationRef.current) setError(`会话已删除，但其他会话暂时无法载入：${errorMessage(reason)}`);
        } finally {
          if (generation === viewGenerationRef.current) setLoading(false);
        }
      }
      setDeleteTarget(null);
    } catch (reason) {
      setDeleteError(errorMessage(reason));
    } finally {
      deleteInFlightRef.current = false;
      setDeletingId(null);
    }
  }

  async function send(text: string, confirmation = false, existingRequestId?: string) {
    const trimmed = text.trim();
    if (!trimmed || creating || loading || editingDraft || deleteTarget || deleteInFlightRef.current) return;
    let target = conversation;
    if (!target) target = await createConversation();
    if (!target) return;
    if (target.id !== selectedConversationRef.current) return;
    if (postingByConversation[target.id] || (activeTurn?.conversationId === target.id && activeTurn.status === 'running')) return;
    const generation = viewGenerationRef.current;
    const confirmationState = target.state;
    if (confirmation && !canConfirmDraft(confirmationState)) {
      setError('当前草稿尚未达到可确认状态，请先核对或补充信息。');
      return;
    }
    const clientRequestId = existingRequestId || crypto.randomUUID();
    setPostingByConversation((current) => ({ ...current, [target!.id]: clientRequestId }));
    setError('');
    setOptimistic({ content: trimmed, requestId: clientRequestId });
    if (!confirmation) setInput('');
    try {
      const result = await assistantApi.sendMessage(target.id, {
        text: trimmed,
        clientRequestId,
        ...(confirmation ? { confirmation: {
          draftId: confirmationState.draftId!,
          revision: confirmationState.revision!,
          fingerprint: confirmationState.fingerprint!,
        } } : {}),
      });
      if (confirmation) setUnknownConfirmation((current) => current?.conversationId === target!.id && current.clientRequestId === clientRequestId ? null : current);
      if (selectedConversationRef.current === target.id && viewGenerationRef.current === generation) {
        setActiveTurn({
          id: result.turnId, conversationId: target.id, status: 'running', answer: null, error: null,
        });
      }
      void loadList(target.id);
    } catch (reason) {
      if (confirmation && isUnknownSubmissionResult(reason)) {
        setUnknownConfirmation({ conversationId: target.id, clientRequestId });
      } else if (confirmation) {
        setUnknownConfirmation((current) => current?.conversationId === target!.id && current.clientRequestId === clientRequestId ? null : current);
      }
      if (selectedConversationRef.current === target.id && viewGenerationRef.current === generation) {
        setOptimistic(null);
        if (confirmation && isUnknownSubmissionResult(reason)) {
          setError('提交结果暂时不确定。请使用“查询提交结果”继续查询，系统会沿用本次请求号，不会重复创建。');
        } else {
          setError(errorMessage(reason));
        }
      }
    } finally {
      setPostingByConversation((current) => {
        if (current[target!.id] !== clientRequestId) return current;
        const next = { ...current };
        delete next[target!.id];
        return next;
      });
    }
  }

  async function submitDraft(edits: DraftEdits) {
    const sourceDraft = editingDraft || conversation?.state.draft;
    if (!conversation || !sourceDraft || busy) return;
    const targetId = conversation.id;
    const generation = viewGenerationRef.current;
    const retained = pendingDraftSubmission
      && pendingDraftSubmission.conversationId === targetId
      && pendingDraftSubmission.draftId === sourceDraft.draftId
      && pendingDraftSubmission.revision === sourceDraft.revision
      && JSON.stringify(pendingDraftSubmission.edits) === JSON.stringify(edits)
      ? pendingDraftSubmission : null;
    const payload: PendingDraftSubmission = retained || {
      conversationId: targetId,
      clientRequestId: crypto.randomUUID(),
      draftId: sourceDraft.draftId,
      revision: sourceDraft.revision,
      edits,
    };
    setPostingByConversation((current) => ({ ...current, [targetId]: payload.clientRequestId }));
    setDrawerIssues([]);
    setError('');
    try {
      const result = await assistantApi.submitDraft(targetId, {
        clientRequestId: payload.clientRequestId,
        draftId: payload.draftId,
        revision: payload.revision,
        edits: payload.edits,
      });
      setPendingDraftSubmission((current) => current?.conversationId === targetId && current.clientRequestId === payload.clientRequestId ? null : current);
      if (selectedConversationRef.current === targetId && viewGenerationRef.current === generation) {
        setEditingDraft(null);
        setActiveTurn({ id: result.turnId, conversationId: targetId, status: 'running', answer: null, error: null });
        void loadList(targetId);
      }
    } catch (reason) {
      const details = errorDetails(reason);
      const resultUnknown = isUnknownSubmissionResult(reason);
      if (resultUnknown) setPendingDraftSubmission(payload);
      else setPendingDraftSubmission((current) => current?.conversationId === targetId && current.clientRequestId === payload.clientRequestId ? null : current);
      if (selectedConversationRef.current !== targetId || viewGenerationRef.current !== generation) return;
      if (details.issues?.length) { setDrawerIssues(details.issues); setError(''); }
      if (resultUnknown) {
        setError('提交结果暂时不确定。请在抽屉中使用“查询提交结果”继续查询，系统会沿用本次请求号。');
      } else {
        setError(errorMessage(reason));
      }
    } finally {
      setPostingByConversation((current) => {
        if (current[targetId] !== payload.clientRequestId) return current;
        const next = { ...current };
        delete next[targetId];
        return next;
      });
    }
  }

  const busy = Boolean(
    loading
    || (!conversation && creating)
    || (conversation && postingByConversation[conversation.id])
    || (conversation && activeTurn?.conversationId === conversation.id && activeTurn.status === 'running'),
  );
  const pageLocked = busy || Boolean(editingDraft) || Boolean(deleteTarget);
  const submission = conversation?.state.lastSubmission;
  const matchingSnapshotMessages = conversation?.messages.filter((message) => sameDraft(message.draftState, conversation.state)) || [];
  const latestDraftMessageId = matchingSnapshotMessages[matchingSnapshotMessages.length - 1]?.id;
  const hasCurrentSnapshot = Boolean(latestDraftMessageId);
  const showDraftReplyGuidance = Boolean(
    conversation?.state.draft
    && ['COLLECTING', 'READY_TO_CONFIRM'].includes(conversation.state.phase)
    && !['FAILED', 'FAILURE', 'UNKNOWN'].includes((submission?.status || '').toUpperCase())
    && !currentDraftSubmission()
    && unknownConfirmation?.conversationId !== conversation.id,
  );

  return (
    <div className="assistant-shell">
      <button className="mobile-menu" aria-label="打开会话列表" onClick={() => setSidebarOpen(true)}><Menu /></button>
      {sidebarOpen && <button className="sidebar-backdrop" aria-label="关闭会话列表" onClick={() => setSidebarOpen(false)} />}
      <aside className={`assistant-sidebar ${sidebarOpen ? 'is-open' : ''}`}>
        <div className="brand-row">
          <div className="brand-mark"><Sparkles size={19} /></div>
          <div><strong>小智 AI 助理</strong><span>差旅申请助手</span></div>
          <button className="icon-button close-sidebar" onClick={() => setSidebarOpen(false)} aria-label="关闭会话列表"><PanelLeftClose /></button>
        </div>
        <button className="new-chat-button" onClick={() => void createConversation()} disabled={creating || Boolean(deletingId)}>
          <MessageSquarePlus size={19} /> 新建会话
        </button>
        <div className="history-heading"><History size={16} /><span>历史会话</span><span className="history-count">{conversations.length}</span></div>
        <nav className="conversation-list" aria-label="历史会话">
          {conversations.length === 0 && !loading && <p className="sidebar-empty">还没有会话，点击上方开始。</p>}
          {conversations.map((item) => (
            <div className="conversation-row" key={item.id}>
              <button
              className={`conversation-item ${conversation?.id === item.id ? 'active' : ''}`}
              onClick={() => void selectConversation(item.id)}
            >
              <span className="conversation-title">{item.title || '未命名会话'}</span>
              <span className="conversation-meta"><span>{phaseLabel(item.phase)}</span><time>{formatDateTime(item.updatedAt)}</time></span>
              </button>
              <button type="button" className="conversation-delete" title="删除会话" aria-label={`删除会话：${item.title || '未命名会话'}`}
                disabled={loading || creating || Boolean(deletingId) || Boolean(editingDraft) || Boolean(postingByConversation[item.id])
                  || (activeTurn?.conversationId === item.id && activeTurn.status === 'running')
                  || pendingDraftSubmission?.conversationId === item.id || unknownConfirmation?.conversationId === item.id}
                onClick={() => { setDeleteError(''); setDeleteTarget(item); }}><Trash2 size={16} /></button>
            </div>
          ))}
        </nav>
        <a className="simulator-link" href="/simulator"><Server size={18} /><span><strong>模拟差旅系统</strong><small>查看单据与调用记录</small></span><ArrowRight size={17} /></a>
      </aside>

      <main className="assistant-main">
        <header className="chat-header">
          <div>
            <h1>{conversation?.title || '新的差旅申请'}</h1>
            <p>{status?.employeeName || '普通演示员工'} · 由小智协助整理并核对</p>
          </div>
          <div className={`service-pill ${status?.ready ? 'ready' : 'offline'}`}>
            <span />{status?.ready ? '服务已就绪' : '服务未就绪'}
          </div>
          <DocumentPanel conversationId={conversation?.id || null}
            refreshToken={`${conversation?.updatedAt || ''}:${conversation?.messages.length || 0}`} />
        </header>

        <section className="chat-stage" aria-live="polite">
          {loading ? (
            <div className="center-state"><LoaderCircle className="spin" /><p>正在载入会话…</p></div>
          ) : !conversation || (conversation.messages.length === 0 && !optimistic && !activeTurn) ? (
            <div className="welcome-state">
              <div className="welcome-icon"><Bot size={29} /></div>
              <h2>你好，我是小智</h2>
              <p>告诉我出发地、目的地、日期、交通方式和出差事由，我会逐项核对后生成申请。</p>
              <div className="example-grid">
                {examples.map((example) => <button key={example} onClick={() => void send(example)} disabled={busy}>{example}<ArrowRight size={16} /></button>)}
              </div>
            </div>
          ) : (
            <div className="message-stream">
              {conversation.messages.map((message) => (
                <article key={message.id} className={`message-row ${message.role}`}>
                  <div className="avatar">{message.role === 'assistant' ? <Bot size={20} /> : <UserRound size={19} />}</div>
                  <div className={`message-content ${message.draftState?.draft ? 'has-draft' : ''}`}>
                    <div className="message-bubble"><MarkdownMessage content={message.content + (
                      message.id === latestDraftMessageId && showDraftReplyGuidance ? `\n\n${draftReplyGuidance}` : ''
                    )} /></div>
                    {message.draftState?.draft && <DraftCard
                      state={message.id === latestDraftMessageId ? conversation.state : message.draftState}
                      current={message.id === latestDraftMessageId}
                      busy={pageLocked}
                      onEdit={openDraftEditor}
                      onSubmit={submitCurrentCard}
                      editDisabled={Boolean(currentDraftSubmission())}
                      submitLabel={currentDraftSubmission() || unknownConfirmation?.conversationId === conversation.id || (conversation.state.lastSubmission?.status || '').toUpperCase() === 'UNKNOWN' ? '查询提交结果' : '提交单据'}
                    />}
                    <time>{formatDateTime(message.createdAt)}</time>
                    {message.status === 'uncertain' && <div className="message-status-note uncertain"><AlertCircle size={14} />本轮结果尚未确认，请核对会话与模拟单据后继续。</div>}
                    {message.status === 'failed' && <div className="message-status-note failed"><AlertCircle size={14} />本轮处理失败，已有内容仍保留。</div>}
                  </div>
                </article>
              ))}
              {!hasCurrentSnapshot && conversation.state.draft && <article className="message-row assistant legacy-draft-row">
                <div className="avatar"><Bot size={20} /></div><div className="message-content has-draft">
                  {showDraftReplyGuidance && <div className="message-bubble"><MarkdownMessage content={draftReplyGuidance} /></div>}
                  <DraftCard
                  state={conversation.state}
                  current
                  busy={pageLocked}
                  onEdit={openDraftEditor}
                  onSubmit={submitCurrentCard}
                  editDisabled={Boolean(currentDraftSubmission())}
                  submitLabel={currentDraftSubmission() || unknownConfirmation?.conversationId === conversation.id || (conversation.state.lastSubmission?.status || '').toUpperCase() === 'UNKNOWN' ? '查询提交结果' : '提交单据'}
                /></div>
              </article>}
              {optimistic && !conversation.messages.some((message) => message.content === optimistic.content && message.role === 'user') && (
                <article className="message-row user pending-message"><div className="avatar"><UserRound size={19} /></div><div className="message-content"><div className="message-bubble"><p>{optimistic.content}</p></div><time>发送中</time></div></article>
              )}
              {activeTurn && (
                <article className={`message-row assistant ${activeTurn.status === 'running' ? 'running-message' : 'turn-result-message'}`}>
                  <div className="avatar"><Bot size={20} /></div>
                  <div className="message-content"><div className="message-bubble">
                    {activeTurn.answer ? <MarkdownMessage content={activeTurn.answer} /> : activeTurn.status === 'running'
                      ? <div className="thinking"><span /><span /><span /> 小智正在整理</div>
                      : <p>{typeof activeTurn.error === 'string' ? activeTurn.error : activeTurn.error?.message || '本轮处理结果已保留。'}</p>}
                  </div>{activeTurn.status !== 'running' && <div className={`message-status-note ${activeTurn.status}`}><AlertCircle size={14} />本轮结果已收到，但会话尚未同步，请点击“重新连接”重试。</div>}</div>
                </article>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </section>

        <div className="chat-actions">
          {error && <div className="notice error-notice"><AlertCircle size={18} /><span>{error}</span><button onClick={() => void initialise()}><RefreshCw size={15} />重新连接</button></div>}
          {submission && (
            <div className={`submission-card ${submission.status.toLowerCase()}`}>
              {submission.applicationId ? <CheckCircle2 size={20} /> : <AlertCircle size={20} />}
              <div><strong>{submission.applicationNo ? `模拟申请 ${submission.applicationNo}` : (submission.message || '已记录提交结果')}</strong>
                {submission.applicationId && <a href={`/simulator?applicationId=${encodeURIComponent(submission.applicationId)}`}>在模拟系统中查看 <ArrowRight size={14} /></a>}
              </div>
            </div>
          )}
          <div className={`composer ${pageLocked ? 'busy' : ''}`}>
            <textarea
              ref={composerRef}
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onCompositionStart={() => setComposing(true)}
              onCompositionEnd={() => setComposing(false)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey && !composing && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  void send(input);
                }
              }}
              placeholder={editingDraft ? '请先完成或关闭差旅申请编辑…' : busy ? '请稍候，小智正在处理本轮消息…' : '输入差旅行程或修改要求…'}
              disabled={pageLocked}
              rows={1}
              aria-label="发送给小智的消息"
            />
            <button className="send-button" onClick={() => void send(input)} disabled={pageLocked || !input.trim()} aria-label="发送消息">
              {busy ? <LoaderCircle className="spin" /> : <Send />}
            </button>
          </div>
          <p className="composer-hint"><Clock3 size={13} /> Enter 发送，Shift + Enter 换行 · 所有单据均为本地模拟数据</p>
        </div>
      </main>

      {deleteTarget && <DeleteConversationDialog conversation={deleteTarget} deleting={Boolean(deletingId)} error={deleteError}
        onCancel={() => { if (!deleteInFlightRef.current) { setDeleteTarget(null); setDeleteError(''); } }}
        onConfirm={() => void deleteConversation()} />}
      {editingDraft && <DraftDrawer
        draft={editingDraft}
        submitting={Boolean(conversation && postingByConversation[conversation.id])}
        submitLabel={pendingDraftSubmission ? '查询提交结果' : '提交单据'}
        serverIssues={drawerIssues}
        resultUnknown={Boolean(currentDraftSubmission())}
        generalError={error}
        onClose={() => {
          setEditingDraft(null);
          setDrawerIssues([]);
          window.setTimeout(() => focusBeforeDrawerRef.current?.focus(), 0);
        }}
        onSubmit={(edits) => void submitDraft(edits)}
      />}
    </div>
  );
}
