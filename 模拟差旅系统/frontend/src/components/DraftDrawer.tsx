import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDownUp, CircleAlert, LoaderCircle, Plus, RefreshCw, Send, Trash2, X,
} from 'lucide-react';
import { assistantApi } from '../api';
import type { ApiIssue, CityOption, DraftEdits, DraftTrip, DraftView, FormTransport } from '../types';
import { errorMessage } from '../utils';

interface DraftDrawerProps {
  draft: DraftView;
  submitting: boolean;
  submitLabel?: string;
  serverIssues?: ApiIssue[];
  resultUnknown?: boolean;
  generalError?: string;
  onClose: () => void;
  onSubmit: (edits: DraftEdits) => void;
}

type ErrorMap = Record<string, string>;

function blankTrip(): DraftTrip {
  return { id: crypto.randomUUID(), fromCity: '', toCity: '', departDate: '', arriveDate: '', transport: '' };
}

function editableFrom(draft: DraftView): DraftEdits {
  return {
    travelType: draft.travelType,
    reason: draft.reason,
    trips: (draft.editTrips || draft.trips).map((trip) => ({ ...trip })),
  };
}

function validate(edits: DraftEdits): ErrorMap {
  const errors: ErrorMap = {};
  if (!edits.reason.trim()) errors.reason = '请填写出差事由。';
  else if (edits.reason.length > 1200) errors.reason = '出差事由最多 1200 个字符。';
  if (!edits.trips.length) errors.trips = '请至少添加一段行程。';
  else if (edits.trips.length > 20) errors.trips = '最多添加 20 段行程。';
  edits.trips.forEach((trip, index) => {
    const prefix = `trips.${index}`;
    if (!trip.fromCity.trim()) errors[`${prefix}.fromCity`] = '请选择出发城市。';
    if (!trip.toCity.trim()) errors[`${prefix}.toCity`] = '请选择到达城市。';
    if (trip.fromCity.trim() && trip.fromCity.trim() === trip.toCity.trim()) errors[`${prefix}.toCity`] = '出发城市和到达城市不能相同。';
    if (!trip.departDate) errors[`${prefix}.departDate`] = '请选择出发日期。';
    if (!trip.arriveDate) errors[`${prefix}.arriveDate`] = '请选择到达日期。';
    if (trip.departDate && trip.arriveDate && trip.arriveDate < trip.departDate) errors[`${prefix}.arriveDate`] = '到达日期不能早于出发日期。';
    if (!trip.transport) errors[`${prefix}.transport`] = '请选择交通方式。';
  });
  return errors;
}

function groupedTransports(transports: FormTransport[]) {
  return transports.reduce<Record<string, FormTransport[]>>((groups, option) => {
    (groups[option.category] ||= []).push(option);
    return groups;
  }, {});
}

function issueMessage(issue: ApiIssue, path: string[]): string {
  if (issue.question?.trim()) return issue.question.trim();
  if (path.length === 1 && path[0] === 'reason') return '出差事由最多 1200 个字符。';
  if (path.length === 1 && path[0] === 'trips') return '最多添加 20 段行程。';
  if (path.length === 1 && path[0] === 'travelType') return '差旅类型无效，请重新选择。';
  if (path[0] === 'trips' && path.length === 3) {
    return ({
      fromCity: '出发城市最多 100 个字符。',
      from_city: '出发城市最多 100 个字符。',
      toCity: '到达城市最多 100 个字符。',
      to_city: '到达城市最多 100 个字符。',
      departDate: '出发日期格式不正确，请重新选择。',
      depart_date: '出发日期格式不正确，请重新选择。',
      arriveDate: '到达日期格式不正确，请重新选择。',
      arrive_date: '到达日期格式不正确，请重新选择。',
      transport: '交通方式无效，请重新选择。',
    } as Record<string, string>)[path[2]] || '行程信息格式不正确，请核对后重试。';
  }
  return '提交内容格式不正确，请核对后重试。';
}

function CityField({
  label, value, disabled, error, onChange,
}: { label: string; value: string; disabled: boolean; error?: string; onChange: (value: string) => void }) {
  const [query, setQuery] = useState(value);
  const [items, setItems] = useState<CityOption[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => { setQuery(value); }, [value]);
  useEffect(() => {
    const trimmed = query.trim();
    if (!open || !trimmed) { setItems([]); return; }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const result = await assistantApi.cities(trimmed);
        if (!cancelled) setItems(result.items);
      } catch {
        if (!cancelled) setItems([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 120);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [query, open]);

  return <label className="drawer-field city-field"><span>{label}</span>
    <input
      value={query}
      disabled={disabled}
      aria-label={label}
      aria-invalid={Boolean(error)}
      autoComplete="off"
      onFocus={() => setOpen(true)}
      onBlur={() => window.setTimeout(() => setOpen(false), 100)}
      onChange={(event) => { setQuery(event.target.value); onChange(event.target.value); setOpen(true); }}
    />
    {open && (loading || items.length > 0) && <div className="city-results" role="listbox" aria-label={`${label}搜索结果`}>
      {loading ? <span className="city-loading"><LoaderCircle className="spin" />正在搜索…</span> : items.map((item) => (
        <button key={item.id} type="button" role="option" aria-selected={item.name === value} onMouseDown={(event) => event.preventDefault()} onClick={() => { onChange(item.name); setQuery(item.name); setOpen(false); }}>{item.name}</button>
      ))}
    </div>}
    {error && <small className="field-error">{error}</small>}
  </label>;
}

export function DraftDrawer({ draft, submitting, submitLabel = '提交单据', serverIssues = [], resultUnknown = false, generalError = '', onClose, onSubmit }: DraftDrawerProps) {
  const initial = useMemo(() => editableFrom(draft), [draft]);
  const [edits, setEdits] = useState<DraftEdits>(initial);
  const [errors, setErrors] = useState<ErrorMap>({});
  const [transports, setTransports] = useState<FormTransport[]>([]);
  const [optionsError, setOptionsError] = useState('');
  const headingRef = useRef<HTMLHeadingElement>(null);
  const drawerRef = useRef<HTMLElement>(null);
  const formErrorRef = useRef<HTMLParagraphElement>(null);
  const generalErrorRef = useRef<HTMLParagraphElement>(null);
  const dirty = JSON.stringify(edits) !== JSON.stringify(initial);

  function focusFirstError(preferGeneral = false) {
    window.setTimeout(() => {
      const invalid = drawerRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
      const target = preferGeneral ? generalErrorRef.current : invalid || formErrorRef.current;
      target?.focus();
      target?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 0);
  }

  useEffect(() => {
    let cancelled = false;
    setOptionsError('');
    void assistantApi.formOptions().then((result) => {
      if (!cancelled) setTransports(result.transports);
    }).catch((reason) => {
      if (!cancelled) setOptionsError(errorMessage(reason));
    });
    headingRef.current?.focus();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!serverIssues.length) return;
    const next: ErrorMap = {};
    const fields: Record<string, string> = {
      from_city: 'fromCity', to_city: 'toCity', depart_date: 'departDate',
      arrive_date: 'arriveDate', fromCity: 'fromCity', toCity: 'toCity',
      departDate: 'departDate', arriveDate: 'arriveDate', transport: 'transport',
    };
    const addError = (key: string, message: string) => {
      next[key] = next[key] && next[key] !== message ? `${next[key]} ${message}` : message;
    };
    serverIssues.forEach((issue) => {
      const path = issue.field.split('.').filter(Boolean);
      while (path[0] === 'body' || path[0] === 'edits') path.shift();
      const message = issueMessage(issue, path);
      if (path.length === 1 && path[0] === 'reason') {
        addError('reason', message);
        return;
      }
      if (path.length === 1 && (path[0] === 'trips' || path[0] === 'route')) {
        addError('form', message);
        return;
      }
      if (path[0] === 'trips' && path.length === 3) {
        const index = Number(path[1]);
        const field = fields[path[2]];
        if (Number.isInteger(index) && index >= 0 && index < edits.trips.length && field) {
          addError(`trips.${index}.${field}`, message);
          return;
        }
      }
      const targetIndex = issue.target ? edits.trips.findIndex((trip) => trip.id === issue.target) : -1;
      const targetField = fields[path[path.length - 1]];
      if (targetIndex >= 0 && targetField) {
        addError(`trips.${targetIndex}.${targetField}`, message);
      } else {
        addError('form', message);
      }
    });
    setErrors(next);
    focusFirstError();
  }, [serverIssues]);

  useEffect(() => {
    if (generalError && !serverIssues.length) focusFirstError(true);
  }, [generalError, serverIssues.length]);

  function requestClose() {
    if (submitting) return;
    if (dirty && !window.confirm('修改尚未提交，确定要关闭吗？')) return;
    onClose();
  }

  function updateTrip(index: number, field: keyof DraftTrip, value: string) {
    setEdits((current) => ({ ...current, trips: current.trips.map((trip, tripIndex) => tripIndex === index ? { ...trip, [field]: value } : trip) }));
    setErrors((current) => { const next = { ...current }; delete next[`trips.${index}.${field}`]; return next; });
  }

  function insertTrip(afterIndex?: number) {
    setEdits((current) => {
      if (current.trips.length >= 20) return current;
      const trips = [...current.trips];
      trips.splice(afterIndex === undefined ? trips.length : afterIndex + 1, 0, blankTrip());
      return { ...current, trips };
    });
  }

  function submit() {
    const next = validate(edits);
    setErrors(next);
    if (Object.keys(next).length) { focusFirstError(); return; }
    onSubmit({ ...edits, reason: edits.reason.trim(), trips: edits.trips.map((trip) => ({ ...trip, fromCity: trip.fromCity.trim(), toCity: trip.toCity.trim() })) });
  }

  function handleDialogKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'Escape') { requestClose(); return; }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(drawerRef.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) || []);
    if (!focusable.length) { event.preventDefault(); return; }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    const activeIndex = focusable.indexOf(active as HTMLElement);
    if (event.shiftKey && activeIndex <= 0) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (activeIndex < 0 || active === last)) {
      event.preventDefault();
      first.focus();
    }
  }

  return <div className="draft-drawer-layer">
    <button type="button" className="draft-drawer-backdrop" aria-label="关闭编辑遮罩" onClick={requestClose} />
    <aside ref={drawerRef} className="draft-drawer" role="dialog" aria-modal="true" aria-labelledby="draft-drawer-title" onKeyDown={handleDialogKeyDown}>
      <header className="draft-drawer-header">
        <div><h2 id="draft-drawer-title" ref={headingRef} tabIndex={-1}>编辑差旅申请</h2><p>提交前请核对所有字段，修改会随本次提交一起处理。</p></div>
        <button type="button" aria-label="关闭编辑" onClick={requestClose} disabled={submitting}><X /></button>
      </header>

      <div className="draft-drawer-body">
        {generalError && <p ref={generalErrorRef} className="drawer-alert" role="alert" aria-label="提交错误" tabIndex={-1}><CircleAlert />{generalError}</p>}
        {errors.form && <p ref={formErrorRef} className="drawer-alert" role="alert" aria-label="表单错误" tabIndex={-1}><CircleAlert />{errors.form}</p>}
        <section className="drawer-section"><h3>申请信息</h3>
          <dl className="drawer-identity">
            <div><dt>申请人</dt><dd>{draft.applicantName}</dd></div>
            <div><dt>部门</dt><dd>{draft.department}</dd></div>
            <div><dt>费用承担公司</dt><dd>{draft.payerCompany}</dd></div>
          </dl>
          <div className="drawer-grid">
            <label className="drawer-field"><span>差旅类型</span><select aria-label="差旅类型" value={edits.travelType} disabled={submitting || resultUnknown} onChange={(event) => setEdits((current) => ({ ...current, travelType: event.target.value as DraftEdits['travelType'] }))}><option value="NORMAL">普通差旅</option><option value="SHORT_TERM">短期异地办公</option></select></label>
            <label className="drawer-field wide"><span>出差事由</span><textarea aria-label="出差事由" rows={3} maxLength={1200} value={edits.reason} disabled={submitting || resultUnknown} aria-invalid={Boolean(errors.reason)} onChange={(event) => { setEdits((current) => ({ ...current, reason: event.target.value })); setErrors((current) => { const next = { ...current }; delete next.reason; return next; }); }} />{errors.reason && <small className="field-error">{errors.reason}</small>}</label>
          </div>
        </section>

        <section className="drawer-section"><div className="drawer-section-heading"><div><h3>行程信息</h3><p>可按实际顺序补充多段行程，最多 20 段。</p></div><button type="button" className="drawer-text-button" onClick={() => insertTrip()} disabled={submitting || resultUnknown || edits.trips.length >= 20}><Plus />增加行程</button></div>
          {resultUnknown && <p className="drawer-alert unknown"><CircleAlert />提交结果尚未确认，填写内容已保留。请沿用本次请求查询结果，避免重复创建。</p>}
          {errors.trips && <p className="drawer-alert"><CircleAlert />{errors.trips}</p>}
          <div className="drawer-trip-list">{edits.trips.map((trip, index) => {
            const key = `trips.${index}`;
            return <fieldset key={trip.id} className="drawer-trip"><legend>行程 {index + 1}</legend>
              <div className="drawer-trip-tools">
                <button type="button" aria-label={`交换行程 ${index + 1} 的城市`} onClick={() => { updateTrip(index, 'fromCity', trip.toCity); updateTrip(index, 'toCity', trip.fromCity); }} disabled={submitting || resultUnknown}><ArrowDownUp />交换城市</button>
                <button type="button" aria-label="在此后插入行程" onClick={() => insertTrip(index)} disabled={submitting || resultUnknown || edits.trips.length >= 20}><Plus />插入</button>
                <button type="button" aria-label={`删除行程 ${index + 1}`} onClick={() => setEdits((current) => ({ ...current, trips: current.trips.filter((_, tripIndex) => tripIndex !== index) }))} disabled={submitting || resultUnknown || edits.trips.length === 1}><Trash2 />删除</button>
              </div>
              <div className="drawer-grid">
                <CityField label={`行程 ${index + 1} 出发城市`} value={trip.fromCity} disabled={submitting || resultUnknown} error={errors[`${key}.fromCity`]} onChange={(value) => updateTrip(index, 'fromCity', value)} />
                <CityField label={`行程 ${index + 1} 到达城市`} value={trip.toCity} disabled={submitting || resultUnknown} error={errors[`${key}.toCity`]} onChange={(value) => updateTrip(index, 'toCity', value)} />
                <label className="drawer-field"><span>出发日期</span><input type="date" aria-label={`行程 ${index + 1} 出发日期`} value={trip.departDate} disabled={submitting || resultUnknown} aria-invalid={Boolean(errors[`${key}.departDate`])} onChange={(event) => updateTrip(index, 'departDate', event.target.value)} />{errors[`${key}.departDate`] && <small className="field-error">{errors[`${key}.departDate`]}</small>}</label>
                <label className="drawer-field"><span>到达日期</span><input type="date" aria-label={`行程 ${index + 1} 到达日期`} value={trip.arriveDate} disabled={submitting || resultUnknown} aria-invalid={Boolean(errors[`${key}.arriveDate`])} onChange={(event) => updateTrip(index, 'arriveDate', event.target.value)} />{errors[`${key}.arriveDate`] && <small className="field-error">{errors[`${key}.arriveDate`]}</small>}</label>
                <label className="drawer-field wide"><span>交通方式</span><select aria-label={`行程 ${index + 1} 交通方式`} value={trip.transport} disabled={submitting || resultUnknown} aria-invalid={Boolean(errors[`${key}.transport`])} onChange={(event) => updateTrip(index, 'transport', event.target.value)}><option value="">请选择交通方式</option>{Object.entries(groupedTransports(transports)).map(([category, options]) => <optgroup key={category} label={category}>{options.map((option) => <option key={option.value} value={option.value}>{category} - {option.option}</option>)}</optgroup>)}</select>{errors[`${key}.transport`] && <small className="field-error">{errors[`${key}.transport`]}</small>}</label>
              </div>
            </fieldset>;
          })}</div>
          {optionsError && <p className="drawer-alert"><RefreshCw />交通选项加载失败：{optionsError}</p>}
        </section>
      </div>

      <footer className="draft-drawer-footer"><p>提交后将创建模拟差旅申请。</p><button type="button" onClick={submit} disabled={submitting}>{submitting ? <LoaderCircle className="spin" /> : <Send />}{submitLabel}</button></footer>
    </aside>
  </div>;
}
