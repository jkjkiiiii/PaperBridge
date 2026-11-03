# DeepSeek token 与人民币费用核算

计量依据是每次 API 响应的 `usage`，不是 Word 的字数，也不是仅对论文正文分词。请求还包含系统提示、句子 ID、中文译文、相邻上下文和映射 JSON；同一内容可能在多个段落请求中出现。

专用机器翻译由火山执行时，DeepSeek 只承担句子映射；中文编辑后的英文回写属于另外的调用。报告必须说明这两个阶段是否都包括在内。参考文献跳过策略应体现在实际请求清单，而不是事后从 token 总数中扣一个估计比例。

## 记录全部响应

测量脚本应在 HTTP 响应到达、JSON 与映射校验之前记录 usage。模型输出未通过校验但已经生成的响应，以及后续修正重试，都可能计费。不能只统计最后成功存进项目的那次结果。

账本格式：

```json
{
  "requests": [
    {
      "requestId": "example-1",
      "task": "repair_alignment",
      "paragraphId": "p00001",
      "model": "deepseek-flash",
      "startedAt": "2026-11-04T02:00:00+00:00",
      "statusCode": 200,
      "usage": {
        "prompt_tokens": 1000,
        "prompt_cache_hit_tokens": 200,
        "prompt_cache_miss_tokens": 800,
        "completion_tokens": 100,
        "total_tokens": 1100
      }
    }
  ]
}
```

示例数量仅用于解释格式，不是论文实测值。账本无需记录密钥、Authorization 请求头或完整论文文字。

## 计算方法

```text
人民币费用 =
  缓存命中输入 token × 命中单价 / 1,000,000
+ 缓存未命中输入 token × 未命中单价 / 1,000,000
+ 输出 token × 输出单价 / 1,000,000
```

`completion_tokens` 已包含相应推理输出时，不能再加一次 reasoning token。`prompt_tokens` 已包含缓存命中部分，不能把完整输入同时按未命中价格重复计算。

2026-11-04 核对的官方人民币价格如下，单位为每百万 token：

| 模型 | 时段 | 输入缓存命中 | 输入缓存未命中 | 输出 |
| --- | --- | ---: | ---: | ---: |
| DeepSeek Flash | 高峰 | 0.04 | 2 | 8 |
| DeepSeek Flash | 空闲 | 0.02 | 1 | 4 |
| DeepSeek V4 Pro | 高峰 | 0.30 | 9 | 27 |
| DeepSeek V4 Pro | 空闲 | 0.15 | 4.5 | 13.5 |

官方高峰时段为北京时间工作日周一至周五的 09:00–12:00、14:00–18:00，排除中国法定节假日。工具按请求开始时间判断时段；跨时段请求的实际账单口径可能不同。节假日需用 `--holiday YYYY-MM-DD` 显式提供，工具不推断调休安排。

```powershell
.\.venv\Scripts\python.exe scripts/report_translation_cost.py `
  .data/experiment/usage-ledger.json `
  --output .data/experiment/cost-report.json
```

同时生成 JSON 和 Markdown。若缺少 usage，报告会标为不完整，不把它记为零费用；若只有输入总量而没有缓存拆分，则给出已计量请求的公开价格范围；未知模型或时区时间也不会猜测单价。

这是按公开价格进行的费用核算，不是账户扣款凭证。赠送余额、账号优惠、价格更新及服务端实际账单仍以控制台为准。价格快照写在 `server/usage_cost.py`，后续价格变化需要更新并重新核对。

来源：[DeepSeek 官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[官方 token 用量说明](https://api-docs.deepseek.com/zh-cn/quick_start/token_usage/)。
