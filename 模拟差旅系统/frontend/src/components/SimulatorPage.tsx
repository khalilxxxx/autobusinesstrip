import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import {
  Activity, AlertCircle, ArrowLeft, Check, ClipboardList, FileSearch, Gauge,
  LoaderCircle, Play, RefreshCw, RotateCcw, Search, Settings2, Sparkles, XCircle,
} from 'lucide-react';
import { simulatorApi } from '../api';
import type { IntegrationEvent, LifecycleDocument, Scenario, SubmissionReceipt } from '../types';
import { errorMessage, formatDateTime, isCreateSuccess } from '../utils';

export function SimulatorPage() {
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [failureMessage, setFailureMessage] = useState('');
  const [applications, setApplications] = useState<LifecycleDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [events, setEvents] = useState<IntegrationEvent[]>([]);
  const [detail, setDetail] = useState<LifecycleDocument | null>(null);
  const [receiptId, setReceiptId] = useState('');
  const [receipt, setReceipt] = useState<SubmissionReceipt | null>(null);
  const [loading, setLoading] = useState(true);
  const [scenarioSaving, setScenarioSaving] = useState(false);
  const [receiptLoading, setReceiptLoading] = useState(false);
  const [error, setError] = useState('');
  const [eventsError, setEventsError] = useState('');
  const [lifecycleSaving, setLifecycleSaving] = useState(false);
  const [seedNotice, setSeedNotice] = useState('');
  const detailRequestRef = useRef(0);

  const loadApplication = useCallback(async (id: string, updateUrl = false) => {
    const request = ++detailRequestRef.current;
    let result;
    try {
      result = await simulatorApi.lifecycleDocument(id);
    } catch (reason) {
      if (request !== detailRequestRef.current) return;
      throw reason;
    }
    if (request !== detailRequestRef.current) return;
    setDetail(result.data);
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set('applicationId', id);
      window.history.replaceState({}, '', url);
    }
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    setEventsError('');
    const [scenarioResult, appsResult, eventsResult] = await Promise.allSettled([
      simulatorApi.scenario(), simulatorApi.lifecycleDocuments(), simulatorApi.events(),
    ]);
    if (scenarioResult.status === 'fulfilled') {
      setScenario(scenarioResult.value.data);
      setFailureMessage(scenarioResult.value.data.failureMessage || '');
    }
    if (appsResult.status === 'fulfilled') {
      setApplications(appsResult.value.data.items);
      setTotal(appsResult.value.data.total);
    }
    if (eventsResult.status === 'fulfilled') setEvents(eventsResult.value.data.items);
    else setEventsError(errorMessage(eventsResult.reason));
    const primaryFailure = [scenarioResult, appsResult].find((result) => result.status === 'rejected');
    if (primaryFailure?.status === 'rejected') setError(errorMessage(primaryFailure.reason));
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh().then(async () => {
      const requested = new URLSearchParams(window.location.search).get('applicationId');
      if (requested) {
        try { await loadApplication(requested); } catch (reason) { setError(errorMessage(reason)); }
      }
    });
  }, [loadApplication, refresh]);

  async function chooseApplication(application: LifecycleDocument) {
    setError('');
    try {
      await loadApplication(application.applicationId, true);
    } catch (reason) { setError(errorMessage(reason)); }
  }

  async function approve(action: 'start' | 'complete' | 'return') {
    if (!detail || lifecycleSaving) return;
    setLifecycleSaving(true); setError('');
    try {
      const response = await simulatorApi.lifecycleApproval(detail.applicationId, {
        action, expectedVersion: detail.version, clientRequestId: crypto.randomUUID(),
      });
      setDetail(response.data.document);
      const list = await simulatorApi.lifecycleDocuments();
      setApplications(list.data.items); setTotal(list.data.total);
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setLifecycleSaving(false); }
  }

  async function addSamples() {
    if (lifecycleSaving) return;
    setLifecycleSaving(true); setError(''); setSeedNotice('');
    try {
      await simulatorApi.seedLifecycle();
      setSeedNotice('演示样例已补齐；操作会保留已有数据，重复点击不会重复生成。');
      await refresh();
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setLifecycleSaving(false); }
  }

  async function saveScenario(result: Scenario['submissionResult']) {
    if (scenarioSaving) return;
    if (result === 'FAILURE' && !failureMessage.trim()) {
      setError('请先填写失败说明。'); return;
    }
    setScenarioSaving(true);
    setError('');
    try {
      const response = await simulatorApi.updateScenario({
        submissionResult: result,
        ...(result === 'FAILURE' ? { failureMessage: failureMessage.trim() } : {}),
      });
      setScenario(response.data);
      setFailureMessage(response.data.failureMessage || '');
    } catch (reason) { setError(errorMessage(reason)); }
    finally { setScenarioSaving(false); }
  }

  async function findReceipt(event: FormEvent) {
    event.preventDefault();
    const id = receiptId.trim();
    if (!id || receiptLoading) return;
    setReceiptLoading(true);
    setReceipt(null);
    setError('');
    try { setReceipt((await simulatorApi.receipt(id)).data); }
    catch (reason) { setError(errorMessage(reason)); }
    finally { setReceiptLoading(false); }
  }

  const successScenario = scenario?.submissionResult === 'SUCCESS';

  return (
    <div className="console-shell">
      <header className="console-header">
        <div><a href="/assistant" className="back-link"><ArrowLeft size={17} />返回小智</a><h1>模拟差旅系统</h1><p>查看场景、单据、回执和接口调用链路</p></div>
        <div className="console-header-actions"><button className="secondary-button" onClick={() => void addSamples()} disabled={lifecycleSaving}><Sparkles size={17} />添加演示样例</button>
          <button className="secondary-button" onClick={() => void refresh()} disabled={loading}><RefreshCw className={loading ? 'spin' : ''} size={17} />刷新数据</button></div>
      </header>

      {error && <div className="console-alert"><AlertCircle size={19} /><span>{error}</span><button onClick={() => setError('')} aria-label="关闭错误"><XCircle size={17} /></button></div>}
      {seedNotice && <div className="console-notice"><Check size={19} /><span>{seedNotice}</span></div>}

      <main className="console-main">
        <section className="overview-grid">
          <div className="metric-card"><span className="metric-icon purple"><ClipboardList /></span><div><small>当前可见单据</small><strong>{loading ? '—' : total}</strong><p>独立生命周期 SQLite；不含被替代旧版</p></div></div>
          <div className="metric-card"><span className={`metric-icon ${successScenario ? 'green' : 'red'}`}>{successScenario ? <Check /> : <AlertCircle />}</span><div><small>下次提交场景</small><strong>{scenario ? (successScenario ? '成功' : '失败') : '—'}</strong><p>只影响新的请求标识</p></div></div>
          <div className="metric-card"><span className="metric-icon blue"><Activity /></span><div><small>最近调用</small><strong>{loading ? '—' : events.length}</strong><p>最多显示 50 条接口记录</p></div></div>
        </section>

        <section className="console-card scenario-card">
          <div className="section-title"><span><Settings2 /><span><h2>提交场景</h2><p>切换后仅影响下一次主动提交，旧请求仍返回原回执。</p></span></span>{scenarioSaving && <LoaderCircle className="spin" />}</div>
          <div className="scenario-options">
            <button className={successScenario ? 'selected success' : ''} onClick={() => void saveScenario('SUCCESS')} disabled={scenarioSaving}>
              <Check /><span><strong>模拟成功</strong><small>创建申请并返回真实模拟单号</small></span>{successScenario && <span className="selected-dot" />}
            </button>
            <button className={scenario && !successScenario ? 'selected failure' : ''} onClick={() => void saveScenario('FAILURE')} disabled={scenarioSaving}>
              <XCircle /><span><strong>模拟失败</strong><small>记录失败回执，不创建申请</small></span>{scenario && !successScenario && <span className="selected-dot" />}
            </button>
          </div>
          <label className="field-label">失败说明<textarea value={failureMessage} onChange={(event) => setFailureMessage(event.target.value)} rows={2} maxLength={1000} placeholder="输入模拟失败时返回给助手的说明" /></label>
          {!successScenario && <button className="primary-button compact" onClick={() => void saveScenario('FAILURE')} disabled={scenarioSaving || !failureMessage.trim()}>保存失败说明</button>}
        </section>

        <div className="console-split">
          <section className="console-card applications-card">
            <div className="section-title"><span><ClipboardList /><span><h2>生命周期单据</h2><p>显示单据类型、状态和当前效力</p></span></span><span className="count-badge">{total} 张</span></div>
            {loading ? <div className="panel-state"><LoaderCircle className="spin" />正在加载</div> : applications.length === 0 ? <div className="panel-state"><ClipboardList /><strong>暂无模拟申请</strong><p>在助手中完成一次成功提交后会显示在这里。</p></div> : (
              <div className="application-list">{applications.map((application) => (
                <button key={application.applicationId} className={detail?.applicationId === application.applicationId ? 'active' : ''} onClick={() => void chooseApplication(application)}>
                  <span className="doc-icon"><ClipboardList /></span><span><strong>{application.applicationNo}</strong><small>{application.documentType === 'CHANGE' ? '行程变更单' : '差旅申请单'} · {{ S002: '待审批', S003: '审批中', S004: '审批完成', S005: '已撤回／退回', S100: '已作废', UNKNOWN: '待核对' }[application.status] || application.status}</small><time>{application.tripStart} 至 {application.tripEnd} · {application.isEffective ? (application.tflag === 'YBG' ? '当前有效，有在途变更' : '当前有效') : '当前未生效'}</time></span>
                </button>
              ))}</div>
            )}
          </section>

          <section className="console-card detail-card">
            <div className="section-title"><span><FileSearch /><span><h2>单据详情与模拟审批</h2><p>S004 是审批完成；S005 保留连续流程，可沿原单号编辑重提。</p></span></span></div>
            {!detail ? <div className="panel-state"><FileSearch /><strong>请选择一张申请</strong><p>可从左侧列表查看完整路线与申请信息。</p></div> : (
              <div className="application-detail">
                <div className="detail-heading"><div><span>{detail.documentType === 'CHANGE' ? '行程变更单' : '差旅申请单'}</span><strong>{detail.applicationNo}</strong></div><span className="success-badge">{{ S002: '待审批', S003: '审批中', S004: '审批完成', S005: '已撤回／退回', S100: '已作废', UNKNOWN: '待核对' }[detail.status] || detail.status}</span></div>
                <dl className="detail-grid"><div><dt>申请人</dt><dd>{detail.request.applicantId}</dd></div><div><dt>创建时间</dt><dd>{formatDateTime(detail.createdAt)}</dd></div><div><dt>差旅类型</dt><dd>{detail.request.dqydbg === 'Y' ? '短期异地办公' : '普通差旅'}</dd></div><div><dt>部门／付款公司</dt><dd>{detail.request.departmentId} / {detail.request.payerCompanyId}</dd></div><div className="wide"><dt>出差事由</dt><dd>{detail.request.remark}</dd></div></dl>
                <div className="approval-actions" aria-label="模拟审批操作">
                  {detail.status === 'S002' && <button className="primary-button" onClick={() => void approve('start')} disabled={lifecycleSaving}><Play />模拟开始审批</button>}
                  {detail.status === 'S003' && <><button className="primary-button" onClick={() => void approve('complete')} disabled={lifecycleSaving}><Check />模拟审批完成</button>
                    <button className="secondary-console-button" onClick={() => void approve('return')} disabled={lifecycleSaving}><RotateCcw />模拟退回</button></>}
                  {!['S002', 'S003'].includes(detail.status) && <p>当前状态无需模拟审批操作。S005 仍可由员工沿原单号编辑后重新提交。</p>}
                </div>
                <h3>行程明细</h3>
                <div className="table-scroll"><table><thead><tr><th>日期</th><th>出发城市</th><th>到达城市</th><th>交通</th></tr></thead><tbody>{detail.request.trips.map((trip, index) => <tr key={`${trip.dateFrom}-${index}`}><td>{trip.dateFrom}{trip.dateTo !== trip.dateFrom && ` → ${trip.dateTo}`}</td><td>{trip.cityFrom}</td><td>{trip.cityTo}</td><td>{trip.tool}</td></tr>)}</tbody></table></div>
                <p className="technical-id">applicationId: {detail.applicationId}</p>
              </div>
            )}
          </section>
        </div>

        <section className="console-card receipt-card">
          <div className="section-title"><span><Search /><span><h2>回执查询</h2><p>输入原始 clientRequestId 找回成功、失败或不确定结果。</p></span></span></div>
          <form className="receipt-form" onSubmit={findReceipt}><input value={receiptId} onChange={(event) => setReceiptId(event.target.value)} placeholder="例如 demo-submit-001" aria-label="请求标识" /><button className="primary-button" disabled={receiptLoading || !receiptId.trim()}>{receiptLoading ? <LoaderCircle className="spin" /> : <Search />}查询回执</button></form>
          {receipt && <div className={`receipt-result ${isCreateSuccess(receipt.result) ? 'success' : 'failure'}`}><div>{isCreateSuccess(receipt.result) ? <Check /> : <XCircle />}<span><strong>{isCreateSuccess(receipt.result) ? '创建成功' : '业务失败'}</strong><small>{receipt.result.code} · {formatDateTime(receipt.createdAt)}</small></span></div><p>{receipt.result.message?.text || (isCreateSuccess(receipt.result) ? `模拟单号：${String(receipt.result.data.applicationNo || '—')}` : '该请求未创建申请。')}</p><code>{receipt.clientRequestId}</code></div>}
        </section>

        <section className="console-card events-card">
          <div className="section-title"><span><Gauge /><span><h2>最近接口调用</h2><p>用于核对助手、工作流与模拟 API 的调用链路。</p></span></span><span className="count-badge">{events.length} 条</span></div>
          {eventsError ? <div className="inline-warning"><AlertCircle />{eventsError}</div> : loading ? <div className="panel-state"><LoaderCircle className="spin" />正在加载</div> : events.length === 0 ? <div className="panel-state"><Activity /><strong>暂无调用记录</strong><p>开始一次助手会话后，这里会显示实际接口请求。</p></div> : (
            <div className="table-scroll"><table className="events-table"><thead><tr><th>时间</th><th>来源</th><th>请求</th><th>HTTP</th><th>业务码</th><th>耗时</th><th>请求标识</th></tr></thead><tbody>{events.map((event) => <tr key={event.id}><td>{formatDateTime(event.createdAt)}</td><td>{event.source}</td><td><code>{event.method}</code> {event.path}</td><td><span className={event.httpStatus < 400 ? 'http-ok' : 'http-error'}>{event.httpStatus}</span></td><td><code>{event.code || '—'}</code></td><td>{event.durationMs} ms</td><td className="request-id">{event.requestId || '—'}</td></tr>)}</tbody></table></div>
          )}
        </section>
      </main>
    </div>
  );
}
