import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, ArrowRight, Plus, Trash2, X } from 'lucide-react';
import type { ApiIssue, LifecycleDifference, LifecycleDraft, LifecycleOptions, TravelApplication } from '../types';

type Payload = TravelApplication['request'];

interface Props {
  draft: LifecycleDraft;
  options: LifecycleOptions | null;
  open: boolean;
  busy: boolean;
  locked: boolean;
  pendingRequestId?: string;
  optionsError: string;
  optionsLoading: boolean;
  issues: ApiIssue[];
  onClose: () => void;
  onCancel: () => void;
  onSave: (payload: Payload) => void;
  onSubmit: () => void;
  onRetryOptions: () => void;
}

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

function optionName(items: { id: string; name: string }[], value: unknown) {
  return items.find((item) => item.id === value)?.name || String(value ?? '—');
}

function cityName(options: LifecycleOptions | null, value: unknown) {
  return options?.cities.find((item) => item.cityId === value)?.cityName || String(value ?? '—');
}

function tripText(options: LifecycleOptions | null, value: unknown) {
  if (!Array.isArray(value)) return '—';
  return value.map((item, index) => {
    const trip = item as Payload['trips'][number];
    return `${index + 1}. ${trip.dateFrom}${trip.dateTo !== trip.dateFrom ? ` 至 ${trip.dateTo}` : ''} · ${cityName(options, trip.cityFrom)} → ${cityName(options, trip.cityTo)} · ${trip.tool}`;
  }).join('；');
}

function differenceText(item: LifecycleDifference, options: LifecycleOptions | null) {
  const names: Record<string, string> = { departmentId: '部门', payerCompanyId: '付款公司', dqydbg: '差旅类型', remark: '出差事由', trips: '行程安排' };
  const format = (value: unknown) => {
    if (item.field === 'departmentId') return optionName(options?.departments || [], value);
    if (item.field === 'payerCompanyId') return optionName(options?.payerCompanies || [], value);
    if (item.field === 'dqydbg') return value === 'Y' ? '短期异地办公' : '普通差旅';
    if (item.field === 'trips') return tripText(options, value);
    return String(value ?? '—');
  };
  return { label: names[item.field] || item.field, text: `${format(item.before)} → ${format(item.after)}` };
}

function validate(payload: Payload) {
  const errors: Record<string, string> = {};
  if (!payload.departmentId) errors.departmentId = '请选择部门。';
  if (!payload.payerCompanyId) errors.payerCompanyId = '请选择付款公司。';
  if (!payload.remark.trim()) errors.remark = '请填写出差事由。';
  if (!payload.trips.length) errors.trips = '请至少保留一段行程。';
  payload.trips.forEach((trip, index) => {
    if (!trip.cityFrom) errors[`trips.${index}.cityFrom`] = `请选择第 ${index + 1} 段出发城市。`;
    if (!trip.cityTo) errors[`trips.${index}.cityTo`] = `请选择第 ${index + 1} 段到达城市。`;
    if (!trip.dateFrom) errors[`trips.${index}.dateFrom`] = `请选择第 ${index + 1} 段出发日期。`;
    if (!trip.dateTo) errors[`trips.${index}.dateTo`] = `请选择第 ${index + 1} 段到达日期。`;
    if (trip.dateFrom && trip.dateTo && trip.dateTo < trip.dateFrom) errors[`trips.${index}.dateTo`] = `第 ${index + 1} 段到达日期不能早于出发日期。`;
    if (!trip.tool) errors[`trips.${index}.tool`] = `请选择第 ${index + 1} 段交通方式。`;
  });
  return errors;
}

export function LifecycleEditor({ draft, options, open, busy, locked, pendingRequestId, optionsError, optionsLoading,
  issues, onClose, onCancel, onSave, onSubmit, onRetryOptions }: Props) {
  const [payload, setPayload] = useState<Payload>(() => clone(draft.payload));
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    setPayload(clone(draft.payload));
    setClientErrors({});
  }, [draft.id]);

  const targetChanged = draft.targetDocument.applicationId !== draft.targetId
    || draft.targetDocument.version !== draft.targetVersion;
  const unsaved = JSON.stringify(payload) !== JSON.stringify(draft.payload);
  const serverErrors = useMemo(() => Object.fromEntries(issues.map((issue) => [
    issue.field.replace(/^(body\.)?(payload\.)?/, ''), issue.message || issue.question || '请核对这个字段。',
  ])), [issues]);
  const errorFor = (field: string) => clientErrors[field] || serverErrors[field];

  const update = <K extends keyof Payload>(key: K, value: Payload[K]) => {
    setPayload((current) => ({ ...current, [key]: value }));
    setClientErrors((current) => { const next = { ...current }; delete next[key]; return next; });
  };
  const updateTrip = (index: number, key: keyof Payload['trips'][number], value: string) => {
    setPayload((current) => ({ ...current, trips: current.trips.map((trip, itemIndex) => itemIndex === index ? { ...trip, [key]: value } : trip) }));
    setClientErrors((current) => { const next = { ...current }; delete next[`trips.${index}.${key}`]; return next; });
  };
  const save = () => {
    const errors = validate(payload); setClientErrors(errors);
    if (!Object.keys(errors).length && !targetChanged) onSave(payload);
  };

  return <div className="lifecycle-editor-layer" hidden={!open} style={open ? undefined : { display: 'none' }}>
    <button type="button" className="draft-drawer-backdrop" aria-label="关闭生命周期编辑遮罩" onClick={onClose} />
    <aside className="lifecycle-editor" role="dialog" aria-modal="true" aria-labelledby="lifecycle-editor-title">
      <header className="draft-drawer-header">
        <div><h2 id="lifecycle-editor-title">{draft.mode === 'change' ? '编辑行程变更' : '编辑后重新提交'}</h2>
          <p>目标单据 {draft.targetDocument.applicationNo} · 当前编辑草稿尚未提交、尚未生效</p></div>
        <button type="button" aria-label="关闭生命周期编辑" onClick={onClose}><X /></button>
      </header>
      <div className="draft-drawer-body">
        {targetChanged && <div className="lifecycle-warning"><AlertCircle />
          <span><strong>原目标已变化，不能直接提交。</strong>当前页面保留了未保存输入。请先关闭编辑并刷新核对；如需继续，请放弃这份草稿后基于当前单据重新准备。</span></div>}
        {draft.requestId && <div className="lifecycle-warning"><AlertCircle />
          <span>办理结果待核对，已保留原请求号 {draft.requestId}。请先查询回执。</span></div>}
        {locked && !draft.requestId && <div className="lifecycle-warning"><AlertCircle />
          <span>办理结果待核对，已保留原请求号 {pendingRequestId}。请先查询办理结果，完成前不能保存、提交或放弃草稿。</span></div>}
        {optionsError && <div className="lifecycle-warning"><AlertCircle />
          <span>基础选项加载失败：{optionsError}</span>
          <button type="button" onClick={onRetryOptions} disabled={optionsLoading}>{optionsLoading ? '正在重新加载' : '重试加载基础选项'}</button>
        </div>}
        <section className="drawer-section">
          <h3>基本信息</h3>
          <div className="drawer-grid lifecycle-fields">
            <label className="drawer-field"><span>部门</span><select aria-label="部门" value={payload.departmentId}
              onChange={(event) => update('departmentId', event.target.value)} aria-invalid={Boolean(errorFor('departmentId'))}>
              <option value="">请选择部门</option>{options?.departments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>{errorFor('departmentId') && <small className="field-error">{errorFor('departmentId')}</small>}</label>
            <label className="drawer-field"><span>付款公司</span><select aria-label="付款公司" value={payload.payerCompanyId}
              onChange={(event) => update('payerCompanyId', event.target.value)} aria-invalid={Boolean(errorFor('payerCompanyId'))}>
              <option value="">请选择付款公司</option>{options?.payerCompanies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>{errorFor('payerCompanyId') && <small className="field-error">{errorFor('payerCompanyId')}</small>}</label>
            <label className="drawer-field"><span>差旅类型</span><select aria-label="差旅类型" value={payload.dqydbg || ''}
              onChange={(event) => update('dqydbg', event.target.value === 'Y' ? 'Y' : null)}>
              <option value="">普通差旅</option><option value="Y">短期异地办公</option>
            </select></label>
            <label className="drawer-field wide"><span>出差事由</span><textarea aria-label="出差事由" rows={3} maxLength={1200}
              value={payload.remark} onChange={(event) => update('remark', event.target.value)} aria-invalid={Boolean(errorFor('remark'))} />
              {errorFor('remark') && <small className="field-error">{errorFor('remark')}</small>}</label>
          </div>
        </section>
        <section className="drawer-section">
          <div className="drawer-section-heading"><div><h3>完整新安排</h3><p>可调整日期、城市与交通，并增删行程段。</p></div>
            <button type="button" className="drawer-text-button" onClick={() => setPayload((current) => ({ ...current, trips: [...current.trips, {
              cityFrom: current.trips.at(-1)?.cityTo || '', cityTo: '', dateFrom: '', dateTo: '', tool: options?.transports[0]?.value || '',
            }] }))}><Plus />添加行程段</button></div>
          {errorFor('trips') && <p className="drawer-alert">{errorFor('trips')}</p>}
          {payload.trips.map((trip, index) => <fieldset className="drawer-trip" key={index}>
            <legend>第 {index + 1} 段</legend>
            <div className="drawer-trip-tools"><button type="button" aria-label={`删除第 ${index + 1} 段行程`}
              disabled={payload.trips.length === 1} onClick={() => setPayload((current) => ({ ...current, trips: current.trips.filter((_, itemIndex) => itemIndex !== index) }))}><Trash2 />删除</button></div>
            <div className="drawer-grid">
              {(['cityFrom', 'cityTo'] as const).map((key) => <label className="drawer-field" key={key}><span>{key === 'cityFrom' ? '出发城市' : '到达城市'}</span>
                <select aria-label={`第 ${index + 1} 段${key === 'cityFrom' ? '出发' : '到达'}城市`} value={trip[key]}
                  onChange={(event) => updateTrip(index, key, event.target.value)} aria-invalid={Boolean(errorFor(`trips.${index}.${key}`))}>
                  <option value="">请选择城市</option>{options?.cities.map((item) => <option key={item.cityId} value={item.cityId}>{item.cityName}</option>)}
                </select>{errorFor(`trips.${index}.${key}`) && <small className="field-error">{errorFor(`trips.${index}.${key}`)}</small>}</label>)}
              {(['dateFrom', 'dateTo'] as const).map((key) => <label className="drawer-field" key={key}><span>{key === 'dateFrom' ? '出发日期' : '到达日期'}</span>
                <input type="date" aria-label={`第 ${index + 1} 段${key === 'dateFrom' ? '出发' : '到达'}日期`} value={trip[key]}
                  onChange={(event) => updateTrip(index, key, event.target.value)} aria-invalid={Boolean(errorFor(`trips.${index}.${key}`))} />
                {errorFor(`trips.${index}.${key}`) && <small className="field-error">{errorFor(`trips.${index}.${key}`)}</small>}</label>)}
              <label className="drawer-field wide"><span>交通方式</span><select aria-label={`第 ${index + 1} 段交通方式`} value={trip.tool}
                onChange={(event) => updateTrip(index, 'tool', event.target.value)} aria-invalid={Boolean(errorFor(`trips.${index}.tool`))}>
                <option value="">请选择交通方式</option>{options?.transports.map((item) => <option key={item.value} value={item.value}>{item.category} · {item.option}</option>)}
              </select>{errorFor(`trips.${index}.tool`) && <small className="field-error">{errorFor(`trips.${index}.tool`)}</small>}</label>
            </div>
          </fieldset>)}
        </section>
        <section className="drawer-section lifecycle-differences">
          <h3>前后差异</h3>
          {!draft.differences.length ? <p>保存后会在这里显示相对原安排的差异。</p> : draft.differences.map((item) => {
            const value = differenceText(item, options); return <div key={item.field}><strong>{value.label}</strong><span>{value.text}</span></div>;
          })}
        </section>
        <section className="drawer-section lifecycle-arrangement">
          <h3>当前完整新安排</h3><p>{payload.remark}</p>
          {payload.trips.map((trip, index) => <div key={index}><span>{index + 1}</span><strong>{cityName(options, trip.cityFrom)} <ArrowRight /> {cityName(options, trip.cityTo)}</strong><small>{trip.dateFrom || '未填写'}{trip.dateTo && trip.dateTo !== trip.dateFrom ? ` 至 ${trip.dateTo}` : ''} · {trip.tool || '未选择交通'}</small></div>)}
        </section>
      </div>
      <footer className="lifecycle-editor-footer">
        <button type="button" className="text-danger" onClick={onCancel} disabled={busy || locked || Boolean(draft.requestId)}>放弃本次编辑</button>
        <span>{unsaved ? '有未保存修改' : `草稿 revision ${draft.revision}`}</span>
        <button type="button" onClick={save} disabled={busy || locked || targetChanged || Boolean(draft.requestId)}>保存并查看差异</button>
        <button type="button" className="primary" onClick={onSubmit} disabled={busy || locked || targetChanged || unsaved || Boolean(draft.requestId)}>
          {draft.mode === 'change' ? '确认提交变更' : '确认重新提交'}
        </button>
      </footer>
    </aside>
  </div>;
}
