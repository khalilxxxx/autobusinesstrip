import { ArrowRight, CircleAlert, FilePenLine, Send } from 'lucide-react';
import type { ConversationState } from '../types';

interface DraftCardProps {
  state: ConversationState;
  current: boolean;
  busy: boolean;
  onEdit: () => void;
  onSubmit: () => void;
  submitLabel?: string;
  editDisabled?: boolean;
}

function isFailure(status?: string | null) {
  return ['FAILED', 'FAILURE'].includes((status || '').toUpperCase());
}

export function DraftCard({
  state, current, busy, onEdit, onSubmit, submitLabel = '提交单据', editDisabled = false,
}: DraftCardProps) {
  const draft = state.draft;
  if (!draft) return null;
  const failed = current && isFailure(state.lastSubmission?.status);
  const submitted = current && state.phase === 'SUBMITTED';
  const unknown = current && (state.lastSubmission?.status || '').toUpperCase() === 'UNKNOWN';
  const interactionLocked = editDisabled || unknown;
  const label = failed ? '差旅申请草稿（提交失败）' : submitted ? '差旅申请草稿（已提交）' : `差旅申请草稿（${current ? '当前版本' : '历史版本'}）`;
  const incomplete = !submitted && (state.phase !== 'READY_TO_CONFIRM' || !state.canSubmit);

  return (
    <section className={`draft-card ${current ? 'current' : 'historical'} ${failed ? 'failed' : ''} ${submitted ? 'submitted' : ''}`} aria-label={label}>
      <div className="draft-card-heading">
        <div><FilePenLine size={18} /><span><strong>差旅申请草稿</strong><small>版本 {draft.revision}</small></span></div>
        <span className={`draft-badge ${failed || unknown || incomplete ? 'warning' : ''}`}>
          {failed ? '提交失败' : submitted ? '已提交' : unknown ? '结果待确认' : current ? (incomplete ? '待补充' : '待提交') : '历史版本'}
        </span>
      </div>

      <dl className="draft-overview">
        <div><dt>申请人</dt><dd>{draft.applicantName || '待补充'}</dd></div>
        <div><dt>部门</dt><dd>{draft.department || '待补充'}</dd></div>
        <div><dt>费用承担公司</dt><dd>{draft.payerCompany || '待补充'}</dd></div>
        <div><dt>差旅类型</dt><dd>{draft.travelType === 'SHORT_TERM' ? '短期异地办公' : '普通差旅'}</dd></div>
        <div className="wide"><dt>出差事由</dt><dd>{draft.reason || '待补充'}</dd></div>
      </dl>

      <div className="draft-trips">
        {draft.trips.length === 0 ? <p className="draft-empty"><CircleAlert size={15} />还没有完整行程，请继续补充。</p> : draft.trips.map((trip, index) => (
          <div className="draft-trip" key={trip.id || `${index}`}>
            <span className="draft-trip-number">{index + 1}</span>
            <span><strong>{trip.fromCity || '待补充'} <ArrowRight size={13} /> {trip.toCity || '待补充'}</strong><small>{trip.departDate || '待补充'} 至 {trip.arriveDate || '待补充'}</small></span>
            <small>{trip.transport || '交通待补充'}</small>
          </div>
        ))}
      </div>

      {failed && <p className="draft-failure-note"><CircleAlert size={16} /><span><strong>完整信息已保留为草稿。</strong>可前往差旅系统进一步编辑；当前演示仅说明后续流程，暂不提供跳转编辑。</span></p>}

      {current && !failed && !submitted && <div className="draft-actions">
        <button type="button" onClick={onEdit} disabled={busy || interactionLocked}><FilePenLine size={15} />编辑申请</button>
        <button type="button" className="primary" onClick={onSubmit} disabled={busy || !state.canSubmit || state.synchronized === false}>
          <Send size={15} />{submitLabel}
        </button>
      </div>}
    </section>
  );
}
