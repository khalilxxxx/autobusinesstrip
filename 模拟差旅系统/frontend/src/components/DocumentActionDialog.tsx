import { useEffect, useRef, useState } from 'react';
import { AlertCircle, LoaderCircle } from 'lucide-react';
import type { LifecyclePendingAction } from '../types';

export function DocumentActionDialog({ proposal, busy, error, onCancel, onConfirm }: {
  proposal: LifecyclePendingAction; busy: boolean; error: string;
  onCancel: () => void; onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState(proposal.reason || '');
  const ref = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const withdraw = proposal.action === 'withdraw';
  const doc = proposal.targetDocument;
  useEffect(() => {
    const previous = document.activeElement;
    cancelRef.current?.focus();
    return () => { if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, []);
  return <div className="delete-dialog-layer" onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onCancel(); }}>
    <div className="delete-dialog document-action-dialog" ref={ref} role="alertdialog" aria-modal="true" aria-labelledby="document-action-title" aria-describedby="document-action-impact"
      onKeyDown={(e) => {
        if (e.key === 'Escape' && !busy) { e.preventDefault(); onCancel(); }
        if (e.key !== 'Tab') return;
        const fields = Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not([disabled]), textarea:not([disabled])') || []);
        const index = fields.indexOf(document.activeElement as HTMLElement);
        if (!fields.length) { e.preventDefault(); return; }
        if (e.shiftKey && index <= 0) { e.preventDefault(); fields[fields.length - 1].focus(); }
        else if (!e.shiftKey && (index < 0 || index === fields.length - 1)) { e.preventDefault(); fields[0].focus(); }
      }}>
      <h2 id="document-action-title">{withdraw ? '确认撤回' : '作废差旅单据'}</h2>
      <p className="delete-dialog-name">{doc.applicationNo}</p>
      <p>{doc.request.remark} · {doc.tripStart} 至 {doc.tripEnd}</p>
      <p id="document-action-impact">{withdraw ? '撤回后单据进入已撤回状态，可沿原单号编辑后重新提交。确认撤回本次提交吗？'
        : doc.documentType === 'CHANGE' && doc.status === 'S005' ? '本次未生效变更将作废，前序批准安排仍有效，之后可以重新发起变更。'
        : '作废后，这份差旅安排立即失效，不恢复旧版本。'}</p>
      {!withdraw && <label className="void-reason-field">作废原因（选填）<textarea aria-label="作废原因（选填）" rows={3} maxLength={4000} value={reason} disabled={busy} onChange={(e) => setReason(e.target.value)} placeholder="例如：客户取消会议，行程不再需要" /></label>}
      {error && <p className="delete-dialog-error" role="alert"><AlertCircle size={16} />{error}</p>}
      <div className="delete-dialog-actions">
        <button ref={cancelRef} type="button" onClick={onCancel} disabled={busy}>取消</button>
        <button type="button" className="danger" disabled={busy} onClick={() => onConfirm(reason.trim())}>{busy && <LoaderCircle size={15} className="spin" />}{withdraw ? '确认撤回' : '确认作废'}</button>
      </div>
    </div>
  </div>;
}
