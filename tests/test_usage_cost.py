from server.usage_cost import reconcile_usage, tariff_at


def row(**change):
    result={'model':'deepseek-flash','startedAt':'2026-11-04T02:00:00Z','statusCode':200,
        'usage':{'prompt_tokens':1000000,'prompt_cache_hit_tokens':200000,'prompt_cache_miss_tokens':800000,'completion_tokens':100000,'total_tokens':1100000}}
    result.update(change);return result


def test_peak_rmb_uses_cache_split_and_counts_retry_usage():
    report=reconcile_usage({'requests':[row(),row(error='JSON failed validation; retried')]})
    assert report['rmbAtPublishedRates']=='4.81600000'
    assert report['totals']['totalTokens']==2200000
    assert report['costCoverageComplete']


def test_offpeak_boundary_and_holiday_override():
    assert tariff_at('2026-11-04T00:59:59Z')=='off_peak'
    assert tariff_at('2026-11-04T01:00:00Z')=='peak'
    assert tariff_at('2026-11-04T04:00:00Z')=='off_peak'
    assert tariff_at('2026-11-04T06:00:00Z')=='peak'
    assert tariff_at('2026-11-04T10:00:00Z')=='off_peak'
    assert tariff_at('2026-11-07T02:00:00Z')=='off_peak'
    assert tariff_at('2026-11-04T02:00:00Z',['2026-11-04'])=='off_peak'
    assert reconcile_usage([row(startedAt='2026-11-04T04:30:00Z')])['rmbAtPublishedRates']=='1.20400000'


def test_missing_usage_is_incomplete_not_zero_billed_total():
    report=reconcile_usage([row(),{'model':'deepseek-flash','statusCode':200}])
    assert report['usageMissingOrInvalidRequests']==1
    assert report['rmbAtPublishedRates'] is None
    assert not report['costCoverageComplete']


def test_no_cache_details_produces_bounds_not_guessed_actual():
    report=reconcile_usage([row(usage={'prompt_tokens':1000000,'completion_tokens':100000})])
    assert report['usageComplete'] and report['costCoverageComplete']
    assert not report['costIsExactAtPublishedRates']
    assert report['rmbAtPublishedRates'] is None
    assert report['knownRequestsRmbRange']=={'lower':'0.84000000','upper':'2.80000000'}


def test_invalid_usage_and_unknown_model_are_not_priced():
    assert not reconcile_usage([row(usage={'prompt_tokens':2,'prompt_cache_hit_tokens':3,'completion_tokens':1})])['usageComplete']
    report=reconcile_usage([row(model='unknown')])
    assert report['unknownPriceRequests']==1 and report['rmbAtPublishedRates'] is None
