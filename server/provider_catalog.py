"""Provider-specific defaults; model availability is discovered using user credentials."""

PROVIDERS = [
    {'id':'moonshot-cn','vendor':'Kimi','name':'Kimi 开放平台 · 中国', 'baseUrl':'https://api.moonshot.cn/v1',
     'protocol':'openai_chat','outputMode':'json','keyUrl':'https://platform.moonshot.cn/console/api-keys',
     'auth':'api_key','modelHints':[], 'notes':'开放平台按量计费，与 Kimi 会员订阅使用不同密钥；从账户获取可用模型。'},
    {'id':'moonshot-global','vendor':'Kimi','name':'Kimi 开放平台 · 国际', 'baseUrl':'https://api.moonshot.ai/v1',
     'protocol':'openai_chat','outputMode':'json','keyUrl':'https://platform.moonshot.ai/console/api-keys',
     'auth':'api_key','modelHints':[], 'notes':'国际开放平台密钥与中国站、Kimi Code 订阅密钥不通用。'},
    {'id':'kimi-code','vendor':'Kimi','name':'Kimi Code 会员订阅', 'baseUrl':'https://api.kimi.com/coding',
     'protocol':'anthropic_messages','outputMode':'text','keyUrl':'https://www.kimi.com/code/console',
     'auth':'subscription','modelHints':[], 'available':False,
     'notes':'会员订阅面向编码客户端；本工具为论文翻译与批量重译，不模拟编码客户端身份或提供未授权登录。请使用开放平台 API。'},
    {'id':'anthropic','vendor':'Anthropic','name':'Anthropic API', 'baseUrl':'https://api.anthropic.com/v1',
     'protocol':'anthropic_messages','outputMode':'schema','keyUrl':'https://console.anthropic.com/settings/keys',
     'auth':'api_key','modelHints':[], 'notes':'使用 Anthropic API 密钥，独立于 Claude 订阅；结构化结果通过工具调用返回。'},
    {'id':'openai','vendor':'OpenAI','name':'OpenAI API', 'baseUrl':'https://api.openai.com/v1',
     'protocol':'openai_responses','outputMode':'schema','keyUrl':'https://platform.openai.com/api-keys',
     'auth':'api_key','modelHints':[], 'notes':'使用 OpenAI API 密钥，独立于 ChatGPT 订阅。默认 Responses，可按模型能力选择 Chat Completions。'},
    {'id':'google','vendor':'Google','name':'Google Gemini API', 'baseUrl':'https://generativelanguage.googleapis.com/v1beta',
     'protocol':'google_genai','outputMode':'schema','keyUrl':'https://aistudio.google.com/apikey',
     'auth':'api_key','modelHints':[], 'notes':'使用 Google AI Studio API 密钥；原生 generateContent 协议，只列出支持生成内容的模型。'},
    {'id':'deepseek','vendor':'DeepSeek','name':'DeepSeek 官方 API', 'baseUrl':'https://api.deepseek.com',
     'protocol':'openai_chat','outputMode':'json','keyUrl':'https://platform.deepseek.com/api_keys',
     'auth':'api_key','modelHints':['deepseek-flash','deepseek-v4-pro'], 'notes':'DeepSeek 官方 OpenAI 兼容接口；使用 JSON Object 输出并本地校验。模型候选来自官方文档，实际可用性以账号模型列表为准；网页聊天免费额度不等于 API 免费。'},
    {'id':'lmstudio','vendor':'其他','name':'LM Studio 本地', 'baseUrl':'http://127.0.0.1:7894/v1',
     'protocol':'openai_chat','outputMode':'schema','keyUrl':'https://lmstudio.ai/docs/developer/core/authentication',
     'auth':'optional_api_key','modelHints':[], 'notes':'从本机服务读取模型列表，附加参数按当前模型配置。'},
    {'id':'custom','vendor':'其他','name':'自定义服务', 'baseUrl':'',
     'protocol':'openai_chat','outputMode':'text','keyUrl':'','auth':'api_key','modelHints':[],
     'notes':'手动填写服务地址、接口类型与实际模型 ID。'},
]


def catalog():
    return {'providers':PROVIDERS,'protocols':[
        {'id':'openai_chat','name':'OpenAI Chat Completions'},
        {'id':'openai_responses','name':'OpenAI Responses'},
        {'id':'anthropic_messages','name':'Anthropic Messages'},
        {'id':'google_genai','name':'Google Gemini 原生'},
    ]}
