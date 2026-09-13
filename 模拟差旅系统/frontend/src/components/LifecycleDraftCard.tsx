import { FilePenLine, Send } from 'lucide-react';
import type { LifecycleDraft, LifecycleOptions } from '../types';
import { TravelRequestContent } from './TravelRequestContent';

export function LifecycleDraftCard({ draft, options, current, busy, onEdit, onSubmit }: {
  draft: LifecycleDraft; options: LifecycleOptions | null; current: boolean; busy: boolean;
  onEdit: () => void; onSubmit: () => void;
}) {
  const change = draft.mode === 'change';
  const allowed = draft.targetDocument.actions[draft.mode].allowed;
  const disabled = !current || busy || !allowed || Boolean(draft.requestId);
  return <article className={`draft-card lifecycle-draft-card ${current ? 'current' : 'historical'}`}
    aria-label={`${change ? '行程变更' : '重新提交'}草稿 ${draft.targetDocument.applicationNo} 版本 ${draft.revision}`}>
    <div className="draft-card-heading"><div><FilePenLine size={18} /><span>
      <strong>{change ? '行程变更草稿' : '重新提交草稿'}</strong><small>{draft.targetDocument.applicationNo} · 版本 {draft.revision}</small>
    </span></div><span className={`draft-badge ${draft.requestId ? 'warning' : ''}`}>{current ? draft.requestId ? '结果待核对' : '待提交' : '历史版本'}</span></div>
    <TravelRequestContent payload={draft.payload} options={options} />
    <div className="draft-actions">
      <button type="button" onClick={onEdit} disabled={disabled}><FilePenLine size={15} />{change ? '编辑变更' : '编辑草稿'}</button>
      <button type="button" className="primary" onClick={onSubmit} disabled={disabled}><Send size={15} />{change ? '提交变更' : '重新提交'}</button>
    </div>
  </article>;
}
