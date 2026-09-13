from datetime import date, timedelta
import pytest
from mock_travel.store import ServiceError
from test_lifecycle import service, payload, create, operation, complete


def test_version_is_selected_before_city_and_date_filters(service):
    a=complete(service,create(service))
    a1=complete(service,operation(service,a,'change',payload('DEMO_BEIJING','2027-03-01','2027-03-05')))
    assert service.list_documents({'city':'上海'})['total']==0
    assert service.list_documents({'dateFrom':'2025-12-31','dateTo':'2026-01-01'})['total']==0
    found=service.list_documents({'keyword':a['applicationNo']})['items']
    assert len(found)==1 and found[0]['applicationId']==a1['applicationId']
    assert 'DEMO_SHANGHAI' not in str(found)


def test_cross_year_stay_and_moving_day_city_intersection(service):
    a=complete(service,create(service))
    stay=service.list_documents({'dateFrom':'2026-01-01','dateTo':'2026-01-01','city':'上海','effectiveOnly':True})
    assert stay['total']==1
    assert stay['items'][0]['locations'][0]['kind']=='stay'
    assert stay['items'][0]['locations'][0]['cityIds']==['DEMO_SHANGHAI']
    move=service.list_documents({'dateFrom':'2025-12-29','dateTo':'2025-12-29','city':'杭州'})
    assert move['total']==1
    location=move['items'][0]['locations'][0]
    assert location['kind']=='movement' and location['cityIds']==['330100','DEMO_SHANGHAI']
    assert location['explanation']
    assert service.list_documents({'dateFrom':'2026-01-01','dateTo':'2026-01-01','city':'杭州'})['total']==0
    assert service.list_documents({'dateFrom':'2025-12-31','dateTo':'2026-01-02'})['total']==1


def test_effective_pending_status_temporal_and_pagination(service):
    today=date.today()
    a=complete(service,create(service,payload(start=(today-timedelta(days=1)).isoformat(),end=(today+timedelta(days=1)).isoformat())))
    operation(service,a,'change',payload('DEMO_BEIJING','2027-03-01','2027-03-05'))
    assert service.list_documents({'effectiveOnly':True})['total']==1
    assert service.list_documents({'status':'S002'})['total']==1
    assert service.list_documents({'temporal':'current','effectiveOnly':True})['total']==1
    assert service.list_documents({'limit':1,'offset':1})['total']==2
    assert len(service.list_documents({'limit':1,'offset':1})['items'])==1
    assert service.list_documents({'dateBasis':'submitted','dateFrom':today.isoformat()})['total']==2


@pytest.mark.parametrize('filters',[{'dateFrom':'2026-02-30'},{'dateFrom':'2027-01-01','dateTo':'2026-01-01'},
                                   {'dateBasis':'bad'},{'temporal':'bad'},{'limit':0},{'effectiveOnly':'maybe'}])
def test_invalid_filters_are_structured(service,filters):
    with pytest.raises(ServiceError) as exc: service.list_documents(filters)
    assert exc.value.status==422


@pytest.mark.parametrize('boundary', ['0001-01-01', '9999-12-31'])
def test_same_day_date_boundary_keeps_default_list_and_movements_queryable(service, boundary):
    a = complete(service, create(service))
    current = complete(service, operation(service, a, 'change', payload(start=boundary, end=boundary)))
    documents = service.list_documents({})
    assert documents['total'] == 1
    assert documents['items'][0]['applicationId'] == current['applicationId']
    day = service.list_documents({'dateFrom': boundary, 'dateTo': boundary})
    locations = day['items'][0]['locations']
    assert [item['kind'] for item in locations] == ['movement', 'movement']
    assert [item['cityIds'] for item in locations] == [
        ['330100', 'DEMO_SHANGHAI'], ['DEMO_SHANGHAI', '330100']]


@pytest.mark.parametrize('start,end,stay_day', [
    ('0001-01-01', '0001-01-03', '0001-01-02'),
    ('9999-12-29', '9999-12-31', '9999-12-30'),
])
def test_date_boundary_retains_real_intermediate_stay(service, start, end, stay_day):
    a = complete(service, create(service))
    complete(service, operation(service, a, 'change', payload(start=start, end=end)))
    day = service.list_documents({'dateFrom': stay_day, 'dateTo': stay_day, 'city': '上海'})
    locations = day['items'][0]['locations']
    assert len(locations) == 1
    assert locations[0]['kind'] == 'stay'
    assert locations[0]['dateFrom'] == locations[0]['dateTo'] == stay_day
    assert locations[0]['cityIds'] == ['DEMO_SHANGHAI']
