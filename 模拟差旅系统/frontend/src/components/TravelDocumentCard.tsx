import { ArrowRight, CalendarDays, ExternalLink, FileText } from 'lucide-react';
import type { LifecycleDocument, LifecycleOptions } from '../types';
import { formatDateTime } from '../utils';

const statuses: Record<string, string> = { UNKNOWN: '待核对', S002: '待审批', S003: '审批中', S004: '审批完成', S005: '已撤回／退回', S100: '已作废' };
const historyNames: Record<string, string> = { create: '创建并提交', change: '提交行程变更', resubmit: '编辑后重新提交', withdraw: '员工撤回', void: '员工作废', start: '开始审批', complete: '审批完成', return: '审批退回' };

export function TravelDocumentCard({ doc, options, busy, onAction, onPrepare }: {
  doc: LifecycleDocument; options: LifecycleOptions | null; busy: boolean;
  onAction: (doc: LifecycleDocument, action: 'withdraw' | 'void') => void;
  onPrepare: (doc: LifecycleDocument, mode: 'change' | 'resubmit') => void;
}) {
  const city = (id: string) => options?.cities.find((c) => c.cityId === id)?.cityName || id;
  const effect = doc.status === 'S100' ? '已作废' : doc.isEffective ? '当前有效'
    : doc.documentType === 'CHANGE' ? '变更尚未生效' : '尚未生效';
  return <article className="travel-document-card" aria-label={`差旅单据 ${doc.applicationNo}`}>
    <header><span className="travel-document-icon"><FileText size={19} /></span><div>
      <small>{doc.documentType === 'CHANGE' ? '行程变更单' : '差旅申请单'}</small><strong>{doc.applicationNo}</strong>
    </div><span className={`travel-document-status status-${doc.status}`}>{statuses[doc.status] || doc.status}</span></header>
    <div className="travel-document-body">
      <div className="travel-document-date"><CalendarDays size={15} />{doc.tripStart} 至 {doc.tripEnd}</div>
      <p className="travel-document-reason">{doc.request.remark}</p>
      <div className="travel-document-route">{doc.request.trips.map((trip, i) => <span key={i}>{city(trip.cityFrom)} <ArrowRight size={12} /> {city(trip.cityTo)}</span>)}</div>
      <div className="document-tags"><span>{effect}</span>{doc.pendingChangeId && <span>有在途变更</span>}</div>
      {doc.resolvedFrom && <p className="document-stay">原编号已关联到当前单据。</p>}
      {doc.locations?.map((location, i) => <p className="document-stay" key={i}>{location.dateFrom}{location.dateTo !== location.dateFrom ? ` 至 ${location.dateTo}` : ''}：
        {location.cityIds.map(city).join('、')} · {location.kind === 'stay' ? '申报停留' : '申报移动'}。{location.explanation}</p>)}
      <details><summary>单据详情</summary>
        <dl className="document-summary"><div><dt>部门</dt><dd>{options?.departments.find((d) => d.id === doc.request.departmentId)?.name || doc.request.departmentId}</dd></div>
          <div><dt>付款公司</dt><dd>{options?.payerCompanies.find((c) => c.id === doc.request.payerCompanyId)?.name || doc.request.payerCompanyId}</dd></div>
          <div><dt>差旅类型</dt><dd>{doc.request.dqydbg === 'Y' ? '短期异地办公' : '普通差旅'}</dd></div><div><dt>提交日期</dt><dd>{formatDateTime(doc.submittedAt)}</dd></div></dl>
        <div className="document-routes">{doc.request.trips.map((trip, i) => <div key={i}><span>{i + 1}</span><strong>{city(trip.cityFrom)} <ArrowRight /> {city(trip.cityTo)}</strong><small>{trip.dateFrom}{trip.dateTo !== trip.dateFrom ? ` 至 ${trip.dateTo}` : ''} · {trip.tool}</small></div>)}</div>
        <ol className="document-history">{doc.history.map((item, i) => <li key={i}><strong>{historyNames[item.action] || item.action}</strong><span>{formatDateTime(item.at)} · {statuses[item.toStatus] || item.toStatus}</span></li>)}</ol>
      </details>
    </div>
    <footer>
      <button type="button" className="system-document-button" title="演示入口">查看系统单据<ExternalLink size={13} /></button>
      {doc.actions.withdraw.allowed && <button type="button" disabled={busy} onClick={() => onAction(doc, 'withdraw')}>撤回本次提交</button>}
      {doc.actions.change.allowed && <button type="button" disabled={busy} onClick={() => onPrepare(doc, 'change')}>发起行程变更</button>}
      {doc.actions.resubmit.allowed && <button type="button" disabled={busy} onClick={() => onPrepare(doc, 'resubmit')}>编辑后重新提交</button>}
      {doc.actions.void.allowed && <button type="button" className="danger" disabled={busy} onClick={() => onAction(doc, 'void')}>
        {doc.documentType === 'CHANGE' && doc.status === 'S005' ? '作废本次未生效变更' : '作废当前有效单据'}</button>}
    </footer>
  </article>;
}
