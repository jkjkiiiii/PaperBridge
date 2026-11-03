"""Reconcile returned DeepSeek usage with a dated public RMB price snapshot.

This is a price calculation, not an account invoice. No paper text or credentials
are needed. Missing usage is never silently replaced with a word-count estimate.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

PRICE_URL = 'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/'
TOKEN_URL = 'https://api-docs.deepseek.com/zh-cn/quick_start/token_usage/'
PRICE_CHECKED_DATE = '2026-11-04'
BEIJING = timezone(timedelta(hours=8), 'Asia/Shanghai')
RATES = {
    'deepseek-flash': {'peak': ('0.04', '2', '8'), 'off_peak': ('0.02', '1', '4')},
    'deepseek-v4-pro': {'peak': ('0.30', '9', '27'), 'off_peak': ('0.15', '4.5', '13.5')},
}


def model_family(model):
    value = (model or '').lower()
    if value in ('deepseek-flash', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp') or value.startswith('deepseek-v4.1-flash'):
        return 'deepseek-flash'
    if value == 'deepseek-v4-pro' or value.startswith('deepseek-v4-pro-'):
        return 'deepseek-v4-pro'
    return None


def tariff_at(iso, holidays=()):
    moment = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    if moment.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    local = moment.astimezone(BEIJING)
    minute = local.hour * 60 + local.minute
    is_peak = local.weekday() < 5 and local.date().isoformat() not in holidays and (540 <= minute < 720 or 840 <= minute < 1080)
    return 'peak' if is_peak else 'off_peak'


def _integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f'{label} must be a non-negative integer')
    return value


def _money(value):
    return format(value.quantize(Decimal('0.00000001')), 'f')


def reconcile_usage(ledger, holidays=()):
    requests = ledger.get('requests', []) if isinstance(ledger, dict) else ledger
    if not isinstance(requests, list): raise ValueError('Ledger requests must be an array')
    rows = []
    totals = dict(promptTokens=0, completionTokens=0, totalTokens=0, cacheHitTokens=0, cacheMissTokens=0)
    lower = upper = Decimal(0)
    incomplete, cache_unknown, unknown_prices = 0, 0, 0
    for index, request in enumerate(requests):
        row = {k: request[k] for k in ('requestId', 'task', 'paragraphId', 'model', 'startedAt', 'statusCode') if k in request}
        row['index'] = index
        usage = request.get('usage')
        if not isinstance(usage, dict) or 'prompt_tokens' not in usage or 'completion_tokens' not in usage:
            row.update(metering='unavailable', warning='No complete returned token usage; not treated as zero cost.')
            incomplete += 1; rows.append(row); continue
        try:
            prompt = _integer(usage['prompt_tokens'], 'prompt_tokens')
            output = _integer(usage['completion_tokens'], 'completion_tokens')
            hit, miss = usage.get('prompt_cache_hit_tokens'), usage.get('prompt_cache_miss_tokens')
            if hit is not None: hit = _integer(hit, 'prompt_cache_hit_tokens')
            if miss is not None: miss = _integer(miss, 'prompt_cache_miss_tokens')
            if hit is not None and miss is None: miss = prompt - hit
            if miss is not None and hit is None: hit = prompt - miss
            if hit is not None and (hit < 0 or miss < 0 or hit + miss != prompt):
                raise ValueError('Cache hit/miss tokens do not reconcile with prompt_tokens')
            if 'total_tokens' in usage and _integer(usage['total_tokens'], 'total_tokens') != prompt + output:
                raise ValueError('total_tokens does not equal input plus output')
        except ValueError as exc:
            row.update(metering='invalid', warning=str(exc)); incomplete += 1; rows.append(row); continue
        totals['promptTokens'] += prompt; totals['completionTokens'] += output; totals['totalTokens'] += prompt + output
        row.update(metering='returned-usage', promptTokens=prompt, completionTokens=output, totalTokens=prompt + output,
                   cacheHitTokens=hit, cacheMissTokens=miss)
        if hit is not None:
            totals['cacheHitTokens'] += hit; totals['cacheMissTokens'] += miss
        else: cache_unknown += 1
        family = model_family(request.get('model') or request.get('requestedModel'))
        try: tariff = request.get('tariff') or tariff_at(request['startedAt'], holidays)
        except (KeyError, ValueError, TypeError): tariff = None
        if family is None or tariff not in ('peak', 'off_peak'):
            row['warning'] = 'Unknown model price or timezone-aware request time; no RMB amount guessed.'
            unknown_prices += 1; rows.append(row); continue
        hit_rate, miss_rate, output_rate = map(Decimal, RATES[family][tariff])
        if hit is None:
            lo = (prompt * hit_rate + output * output_rate) / Decimal(1000000)
            hi = (prompt * miss_rate + output * output_rate) / Decimal(1000000)
        else:
            lo = hi = (hit * hit_rate + miss * miss_rate + output * output_rate) / Decimal(1000000)
        lower += lo; upper += hi
        row.update(priceModel=family, tariff=tariff, rmbLower=_money(lo), rmbUpper=_money(hi),
                   ratesPerMillionRmb={'inputCacheHit':str(hit_rate),'inputCacheMiss':str(miss_rate),'output':str(output_rate)})
        rows.append(row)
    complete = incomplete == 0 and unknown_prices == 0
    exact_split = complete and cache_unknown == 0
    return {'priceSource':PRICE_URL,'tokenSource':TOKEN_URL,'priceCheckedDate':PRICE_CHECKED_DATE,
        'requestCount':len(requests),'usageMissingOrInvalidRequests':incomplete,'unknownPriceRequests':unknown_prices,
        'cacheSplitUnknownRequests':cache_unknown,'usageComplete':incomplete == 0,'costCoverageComplete':complete,
        'costIsExactAtPublishedRates':exact_split,'totals':totals,
        'rmbAtPublishedRates':_money(lower) if exact_split else None,
        'knownRequestsRmbRange':{'lower':_money(lower),'upper':_money(upper)},
        'assumptions':['Request start time determines peak/off-peak tier; the provider invoice may use a different billing instant.',
            'Weekday schedule excludes only dates explicitly supplied in holidays; no national holiday calendar is inferred.',
            'Returned completion_tokens already includes reasoning tokens where applicable; reasoning is not counted again.',
            'All returned HTTP usage belongs in the ledger, including invalid outputs and retried calls.',
            'This is a calculation at the captured public rates, not a balance deduction or invoice.',
            'Missing usage or unknown prices make the monetary total incomplete; known-request bounds are not bounds for unmetered requests.'],
        'holidayOverrides':list(holidays),'requests':rows}


def markdown_report(report, title='DeepSeek token 与人民币费用核算'):
    totals=report['totals']; amount=report['rmbAtPublishedRates']
    lines=[f'# {title}', '', f"价格核对日期：{report['priceCheckedDate']}。本报告按 API 返回的 usage 计算，不是账户账单。", '',
        '| 项目 | 数量 |','| --- | ---: |',f"| HTTP 请求记录 | {report['requestCount']} |",
        f"| 已计量输入 token | {totals['promptTokens']} |",f"| 已计量输出 token | {totals['completionTokens']} |",
        f"| 合计 token | {totals['totalTokens']} |",f"| 已知缓存命中 token | {totals['cacheHitTokens']} |",
        f"| 已知缓存未命中 token | {totals['cacheMissTokens']} |",
        f"| 缺失或无效用量的请求 | {report['usageMissingOrInvalidRequests']} |",'']
    if amount is not None: lines.append(f'按公开价格核算：**人民币 {amount} 元**。')
    else:
        bounds=report['knownRequestsRmbRange']
        lines.append(f"暂不能给出完整确定金额。可计价请求部分：人民币 {bounds['lower']}–{bounds['upper']} 元；未计量请求不包含在该范围中。")
    lines+=['', '## 计算范围与假设', '']+[f'- {s}' for s in report['assumptions']]
    lines+=['', f"价格：[DeepSeek 官方价格]({PRICE_URL})。用量口径：[官方 token 说明]({TOKEN_URL})。", '']
    return '\n'.join(lines)
