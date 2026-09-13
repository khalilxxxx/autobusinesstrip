import { ArrowRight } from 'lucide-react';
import type { LifecycleOptions, TravelApplication } from '../types';

export function TravelRequestContent({ payload, options }: {
  payload: TravelApplication['request']; options: LifecycleOptions | null;
}) {
  const city = (id: string) => options?.cities.find((item) => item.cityId === id)?.cityName || id;
  const transport = (value: string) => {
    const option = options?.transports.find((item) => item.value === value);
    return option ? `${option.category} · ${option.option}` : value;
  };
  return <>
    <dl className="draft-overview">
      <div><dt>部门</dt><dd>{options?.departments.find((item) => item.id === payload.departmentId)?.name || payload.departmentId}</dd></div>
      <div><dt>费用承担公司</dt><dd>{options?.payerCompanies.find((item) => item.id === payload.payerCompanyId)?.name || payload.payerCompanyId}</dd></div>
      <div><dt>差旅类型</dt><dd>{payload.dqydbg === 'Y' ? '短期异地办公' : '普通差旅'}</dd></div>
      <div className="wide"><dt>出差事由</dt><dd>{payload.remark}</dd></div>
    </dl>
    <div className="draft-trips">
      {payload.trips.map((trip, index) => <div className="draft-trip" key={index}>
        <span className="draft-trip-number">{index + 1}</span>
        <span><strong><span>{city(trip.cityFrom)}</span><ArrowRight size={13} /><span>{city(trip.cityTo)}</span></strong>
          <small>{trip.dateFrom} 至 {trip.dateTo}</small></span>
        <small>{transport(trip.tool)}</small>
      </div>)}
    </div>
  </>;
}
