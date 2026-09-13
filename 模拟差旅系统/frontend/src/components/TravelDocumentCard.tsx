import { CalendarDays, ExternalLink, FileText } from 'lucide-react';
import type { LifecycleDocument, LifecycleOptions } from '../types';
import { formatDateTime } from '../utils';
import { TravelRequestContent } from './TravelRequestContent';

const statuses: Record<string, string> = { UNKNOWN: '待核对', S002: '待审批', S003: '审批中', S004: '审批完成', S005: '已撤回／退回', S100: '已作废' };
const historyNames: Record<string, string> = { create: '创建并提交', change: '提交行程变更', resubmit: '编辑后重新提交', withdraw: '员工撤回', void: '员工作废', start: '开始审批', complete: '审批完成', return: '审批退回' };

export function TravelDocumentCard({ doc, options, busy, current = true, compact = false, onAction, onPrepare }: {
  doc: LifecycleDocument; options: LifecycleOptions | null; busy: boolean; current?: boolean; compact?: boolean;
  onAction: (doc: LifecycleDocument, action: 'withdraw' | 'void') => void;
  onPrepare: (doc: LifecycleDocument, mode: 'change' | 'resubmit') => void;
}) {
  const city = (id: string) => options?.cities.find((item) => item.cityId === id)?.cityName || id;
  const routes: string[][] = [];
  for (const trip of doc.request.trips) {
    const previous = routes.at(-1);
    if (previous?.at(-1) === trip.cityFrom) previous.push(trip.cityTo);
    else routes.push([trip.cityFrom, trip.cityTo]);
  }
  const route = routes.map((cities) => cities.map(city).join('-')).join(' / ');
  const effect = doc.status === 'S100' ? '已作废' : doc.isEffective ? '当前有效'
    : doc.documentType === 'CHANGE' ? '变更尚未生效' : '尚未生效';
  const disabled = busy || !current;
  const documentName = doc.documentType === 'CHANGE' ? '行程变更单' : '差旅申请单';
  return <article className={`travel-document-card draft-card ${compact ? 'compact' : 'full'} ${current ? 'current' : 'historical'}`} aria-label={`差旅单据 ${doc.applicationNo}`}>
    <div className="draft-card-heading"><div><FileText size={18} /><span>
      <strong>{compact ? doc.applicationNo : documentName}</strong><small>{compact ? documentName : doc.applicationNo}</small>
    </span></div><span className={`travel-document-status status-${doc.status}`}>{statuses[doc.status] || doc.status}</span></div>
    <div className="travel-document-date"><CalendarDays size={15} />{doc.tripStart} 至 {doc.tripEnd}</div>
    {compact ? <p className="travel-document-route">{route}</p> : <TravelRequestContent payload={doc.request} options={options} />}
    <details className="travel-document-details"><summary>查看详情</summary>
      {compact && <TravelRequestContent payload={doc.request} options={options} />}
      <div className="document-tags"><span>{effect}</span>{doc.pendingChangeId && <span>有在途变更</span>}</div>
      {doc.resolvedFrom && <p className="document-stay">原编号已关联到当前单据。</p>}
      <p className="document-stay">提交时间：{formatDateTime(doc.submittedAt)}</p>
      <ol className="document-history">{doc.history.map((item, i) => <li key={i}><strong>{historyNames[item.action] || item.action}</strong>
        <span>{formatDateTime(item.at)} · {statuses[item.toStatus] || item.toStatus}</span></li>)}</ol>
    </details>
    <footer className="draft-actions">
      <button type="button" className="system-document-button" title="演示入口">查看系统单据<ExternalLink size={13} /></button>
      {doc.actions.withdraw.allowed && <button type="button" disabled={disabled} onClick={() => onAction(doc, 'withdraw')}>撤回本次提交</button>}
      {doc.actions.change.allowed && <button type="button" disabled={disabled} onClick={() => onPrepare(doc, 'change')}>发起行程变更</button>}
      {doc.actions.resubmit.allowed && <button type="button" disabled={disabled} onClick={() => onPrepare(doc, 'resubmit')}>编辑后重新提交</button>}
      {doc.actions.void.allowed && <button type="button" className="danger" disabled={disabled} onClick={() => onAction(doc, 'void')}>
        {doc.documentType === 'CHANGE' && doc.status === 'S005' ? '作废本次未生效变更' : '作废当前有效单据'}</button>}
    </footer>
  </article>;
}
