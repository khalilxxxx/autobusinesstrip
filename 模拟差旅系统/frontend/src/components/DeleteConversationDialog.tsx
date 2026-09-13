import { useEffect, useRef } from 'react';
import { AlertCircle, LoaderCircle, Trash2 } from 'lucide-react';
import type { ConversationSummary } from '../types';

interface Props {
  conversation: ConversationSummary;
  deleting: boolean;
  error: string;
  onCancel: () => void;
  onConfirm: () => void;
}

export function DeleteConversationDialog({ conversation, deleting, error, onCancel, onConfirm }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previous = document.activeElement;
    cancelRef.current?.focus();
    return () => {
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
      else document.querySelector<HTMLButtonElement>('.new-chat-button')?.focus();
    };
  }, []);

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'Escape' && !deleting) { event.preventDefault(); onCancel(); }
    if (event.key !== 'Tab') return;
    const buttons = Array.from(dialogRef.current?.querySelectorAll<HTMLButtonElement>('button:not([disabled])') || []);
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (!buttons.length) { event.preventDefault(); return; }
    if (event.shiftKey && index <= 0) { event.preventDefault(); buttons[buttons.length - 1].focus(); }
    else if (!event.shiftKey && (index < 0 || index === buttons.length - 1)) { event.preventDefault(); buttons[0].focus(); }
  }

  return <div className="delete-dialog-layer" onMouseDown={(event) => {
    if (event.target === event.currentTarget && !deleting) onCancel();
  }}>
    <div ref={dialogRef} className="delete-dialog" role="alertdialog" aria-modal="true"
      aria-labelledby="delete-conversation-title" aria-describedby="delete-conversation-description" onKeyDown={handleKeyDown}>
      <div className="delete-dialog-icon"><Trash2 size={22} /></div>
      <h2 id="delete-conversation-title">删除会话</h2>
      <p className="delete-dialog-name">{conversation.title || '未命名会话'}</p>
      <p id="delete-conversation-description">删除后，该会话及其草稿将从历史列表移除。已提交的单据仍可在模拟差旅系统中查看。</p>
      {error && <p className="delete-dialog-error" role="alert"><AlertCircle size={16} />{error}</p>}
      <div className="delete-dialog-actions">
        <button ref={cancelRef} type="button" onClick={onCancel} disabled={deleting}>取消</button>
        <button type="button" className="danger" onClick={onConfirm} disabled={deleting}>
          {deleting && <LoaderCircle size={15} className="spin" />}{deleting ? '正在删除…' : '确定删除'}
        </button>
      </div>
    </div>
  </div>;
}
