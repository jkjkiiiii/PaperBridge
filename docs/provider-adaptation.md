# 厂商适配依据与实现边界

日期：2026-11-03。本文记录实际查看的开源实现及官方协议，供当前模型配置改造使用。没有读取用户云端密钥，没有实际调用云服务。OneClaw 代码仅作架构参考，不直接复制实现。

## OneClaw 的实际做法

已通过 GitHub Contents API读取以下源码，研究副本位于被忽略的 `.data/reference/oneclaw/`：

- [provider-config.ts](https://github.com/oneclaw/oneclaw/blob/main/src/provider-config.ts)：厂商预设与 Moonshot 子平台映射、不同认证头、不同验证端点。
- [tab-provider.ts](https://github.com/oneclaw/oneclaw/blob/main/chat-ui/ui/src/ui/views/settings/tab-provider.ts)：按厂商和子平台渲染表单。
- [setup-constants.ts](https://github.com/oneclaw/oneclaw/blob/main/chat-ui/ui/src/ui/views/setup/setup-constants.ts)：厂商专属候选模型、API Key 获取链接与 Kimi Code 独立模型项。此静态列表是候选快照，不能代替账号可用模型发现。
- [model-catalog.ts](https://github.com/oneclaw/oneclaw/blob/main/src/model-catalog.ts)：从 Gateway 目录加载模型能力，优先厂商＋模型精确标识，避免同名模型串用。
- [kimi-oauth.ts](https://github.com/oneclaw/oneclaw/blob/main/src/kimi-oauth.ts)：设备授权、轮询、刷新与本地凭据存储是独立模块，不能由一个“已登录”标签替代。
- [provider-module-redesign.md](https://github.com/oneclaw/oneclaw/blob/main/docs/provider-module-redesign.md)：区分添加／修改意图，保留同服务其他模型元数据，避免覆盖式保存造成数据丢失。

参考的核心是厂商注册表、认证和协议能力分层。开源项目存在某项功能，不等于其 OAuth 客户端身份可以被本工具直接使用。

## 本工具注册表建议

每个接入项至少声明：`vendorId`、`platformId`、`label`、`baseUrl`、`protocol`、`authMode`、`keyUrl`、`modelListMode`、`outputModes`、`supportsBatch`、`notes`。厂商标签应改变默认协议、认证提示和模型列表来源；只更换名称不算适配。

| 接入项 | 地址与协议 | 认证与模型选择 | 结构化结果 |
| --- | --- | --- | --- |
| Kimi 开放平台中国区 | `https://api.moonshot.cn/v1`，Chat Completions | 平台 API Key／Bearer，读取本平台模型列表 | 按模型能力选择 JSON 或 schema，再本地校验 |
| Kimi 开放平台国际区 | `https://api.moonshot.ai/v1`，Chat Completions | 独立平台凭据，不与中国区或会员密钥混用 | 同上 |
| Anthropic | `https://api.anthropic.com/v1`，Messages | Console API Key，版本头，原生 Models API | 本工具强制单一结构化工具结果，无外部工具执行 |
| OpenAI | `https://api.openai.com/v1`，Responses／Chat Completions | 平台 API Key／Bearer，Models API | 按模型能力选择 JSON Schema；不能统一给所有模型注入 temperature |
| Google | `https://generativelanguage.googleapis.com/v1beta`，原生 generateContent | AI Studio API Key／`x-goog-api-key`，Models API | Gemini 原生 JSON 配置，不伪装为 OpenAI response_format |
| 其他 | 用户指定地址、实际协议 | 认证与模型 ID 显式配置 | 不自动假设兼容全部协议 |

模型下拉应优先显示当前凭据实时可用的模型，并允许自定义 ID。离线示例只是候选，不能宣称账号一定可用。Google 列表还应按 `supportedGenerationMethods` 筛选可调用 generateContent 的模型，排除纯嵌入模型。

## Kimi 会员与开放平台必须分开

[Kimi 官方 FAQ](https://www.kimi.com/en/help/kimi-code/faq)明确区分：会员 Coding 服务为 `https://api.kimi.com/coding/`（国际 `api.kimi.ai/coding/`）且使用 Anthropic 兼容协议；开放平台为 `api.moonshot.cn/v1` 或 `api.moonshot.ai/v1`。额度、账户和密钥不同。

[官方 Providers 文档](https://www.kimi.com/code/docs/en/kimi-code-cli/configuration/providers)说明 Kimi Code 管理服务通过 OAuth 登录并刷新凭据。本文没有发现供任意第三方通用翻译应用注册 OAuth 客户端的正式说明，因此不能把 OneClaw 内的客户端标识直接当成本工具的授权身份，也不能把 API Key 存在解释为会员登录成功。

[官方社区规范](https://www.kimi.com/en/help/kimi-code/community-guidelines)限制会员为个人交互用途，明确不允许脚本批量执行及伪装客户端身份。因此，本工具后台全文重译应使用开放平台 API。会员选项可展示其独立入口及说明，但不承诺以订阅额度运行后台批量重译；不实现伪造 coding-agent 请求头来绕过服务限制。

## 官方协议参考

- [Claude API 概述](https://platform.claude.com/docs/en/api/overview)：Messages、Models、认证和版本头。模型和版本变化应以服务响应为准。
- [Claude Models](https://platform.claude.com/docs/en/api/models)：列表可提供模型能力和配额信息。
- [Gemini Models](https://ai.google.dev/api/models)：按可用生成方法筛选模型。
- [Gemini 结构化输出](https://ai.google.dev/gemini-api/docs/structured-output)：原生生成配置与所支持的 JSON Schema 子集。
- [Kimi K2.5 官方模型说明](https://huggingface.co/moonshotai/Kimi-K2.5)：支持思考／即时模式，采样建议有差异。不能将本机 Qwen 的 `reasoning_effort:none` 无条件发送给云端 Kimi。

## 验证应报告的层次

厂商表单和注册表测试、协议请求响应模拟测试、本机真实模型联调、云服务真实凭据联调是不同证据。没有云凭据时可以完成前两项，但不能声称云服务账号已登录或其模型已实测通过。
