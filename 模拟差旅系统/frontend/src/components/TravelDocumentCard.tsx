import { CalendarDays, ExternalLink, FileText } from 'lucide-react';
import type { LifecycleDocument, LifecycleOptions } from '../types';
import { formatDateRange } from '../utils';
import { TravelRequestContent } from './TravelRequestContent';

const statuses: Record<string, string> = { UNKNOWN: '待核对', S001: '草稿', S002: '已提交', S003: '审批中', S004: '已完成', S005: '已撤回／退回', S100: '已作废' };

export function TravelDocumentCard({ doc, options, busy, current = true, onAction, onPrepare }: {
  doc: LifecycleDocument; options: LifecycleOptions | null; busy: boolean; current?: boolean;
  onAction: (doc: LifecycleDocument, action: 'withdraw' | 'void') => void;
  onPrepare: (doc: LifecycleDocument, mode: 'change' | 'resubmit') => void;
}) {
  const disabled = busy || !current;
  const documentName = doc.documentType === 'CHANGE' ? '行程变更单' : '差旅申请单';
  return <article className={`travel-document-card draft-card ${current ? 'current' : 'historical'}`} aria-label={`差旅单据 ${doc.applicationNo}`}>
    <div className="draft-card-heading"><div><FileText size={18} /><span>
      <strong>{documentName}</strong><small>{doc.applicationNo}</small>
    </span></div><span className={`travel-document-status status-${doc.status}`}>{statuses[doc.status] || doc.status}</span></div>
    <div className="travel-document-date"><CalendarDays size={15} />{formatDateRange(doc.tripStart, doc.tripEnd)}</div>
    <TravelRequestContent payload={doc.request} options={options} />
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
