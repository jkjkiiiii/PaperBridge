# PaperBridge 发布文案

以下为待发布稿；发布前请核对项目链接、实际配图与服务价格。示意封面、真实界面和单次实测应分别标注，勿将不同例子描述为连续操作。

## 小红书 A：中文修改，英文同步

**标题：做了个开源工具：改中文，再检查英文怎么变**

**配图顺序：** `01-cover-9x16.png` → `02-read-9x16.png` → `03-edit-9x16.png` → `04-diff-9x16.png` → `05-export-9x16.png` → `08-start-9x16.png`

改英文论文时，中文已经想清楚了，落到英文里却还要反复核对。于是做了开源工具纸桥 PaperBridge，把这个流程串起来：

导入英文 Word，左右对照中文阅读；直接修改中文译文，让模型回写对应英文；再查看 diff，逐处检查增删，确认后另存英文 Word。

封面是原创功能演示：把“彻底解决了模型幻觉”改成“在测试集上减少了模型幻觉”。后面的 Attention 示例则是真实软件截图，是另一组例子。

导出的是干净的英文 DOCX，还可保存独立 JSON 修改记录；它不是 Word 内置修订。模型可能改变原意，术语、数字、引用和英文表达仍需作者核对。

目前原生 Word 版面主要在 Windows ＋ Microsoft Word 环境验证，使用前需要自行配置翻译服务或模型。欢迎试试这个流程是否适合自己。

项目与安装说明：https://github.com/jkjkiiiii/PaperBridge

#论文写作 #科研工具 #开源工具 #Word #学术英语

## 小红书 B：这次实测花了多少

**标题：火山初译、DeepSeek 映射，这次论文实验花了多少？**

**配图顺序：** `07-cost-9x16.png` → `06-services-9x16.png` → `02-read-9x16.png` → `04-diff-9x16.png` → `08-start-9x16.png`

用《Attention Is All You Need》的可编辑 Word 重建稿跑了一次 PaperBridge：火山负责初译，DeepSeek Flash 为固定的中英文建立句子对应。

本次火山初译处理 27,490 字符；DeepSeek 映射输入 91,124、输出 7,858，共 98,982 tokens，使用者核对控制台消费约 **¥0.12**。40 条参考文献及其标题在本次实验中跳过翻译和映射；顺序运行约 5 分 51 秒。

这个数字只对应本次 DeepSeek 映射，**不含后续中文编辑触发的英文回写**。火山是否收费取决于账号剩余额度；两段映射修复另计约 ¥0.0029。图片内文字与脚注未翻译，机器译文需要人工审校。不同文稿、模型、重试和价格会改变费用与耗时。

完整口径与项目地址：https://github.com/jkjkiiiii/PaperBridge/blob/main/docs/attention-cost-case.md

#论文写作 #科研工具 #API #开源工具

## 小红书 C：翻译与模型服务怎么选

**标题：已有 DeepSeek 或本地模型，能接进论文修改流程吗？**

**配图顺序：** `06-services-9x16.png` → `03-edit-9x16.png` → `04-diff-9x16.png` → `08-start-9x16.png`

PaperBridge 可以按任务配置服务：初始翻译可选专用翻译 API 或通用 LLM；句子映射和中文修改后的英文回写由 LLM 完成。

专用翻译 API 有四种：火山引擎机器翻译、DeepL API、Azure Translator、自托管 LibreTranslate。通用模型服务支持 DeepSeek、OpenAI、Anthropic、Google Gemini、Kimi 开放平台，也可配置 LM Studio 本地服务或兼容协议的自定义接口。具体模型能否使用取决于账号、接口和结构化输出能力。

配置好之后，直接修改中文译文，检查对应英文 diff，再导出 Word。相关请求会发送到所选服务；本地运行软件并不意味着选择云端 API 时文稿内容不会发送到云端。网页会员不等于 API 授权，费用和额度以服务商及账号为准。

项目与配置说明：https://github.com/jkjkiiiii/PaperBridge

#科研工具 #论文写作 #大语言模型 #本地模型 #API

## 朋友圈 1：功能介绍

**配图顺序：** `01-cover-9x16.png` → `03-edit-9x16.png` → `04-diff-9x16.png`

最近做了个开源小工具，叫纸桥 PaperBridge。导入英文 Word 后，可以对照中文阅读，直接修改中文译文，让模型回写对应英文，再看 diff、核对后导出 Word。需要自行配置翻译或模型服务；欢迎有类似需求的朋友试用。

https://github.com/jkjkiiiii/PaperBridge

## 朋友圈 2：单次费用案例

**配图顺序：** `07-cost-9x16.png` → `06-services-9x16.png` → `08-start-9x16.png`

用 Attention 论文的可编辑 Word 重建稿测了一次：火山初译，DeepSeek Flash 做句子映射，后者控制台消费约 ¥0.12。这个数字不含后续英文回写，火山费用取决于剩余额度，另有两段映射修复约 ¥0.0029。数据和范围都写在这里：

https://github.com/jkjkiiiii/PaperBridge/blob/main/docs/attention-cost-case.md

## README 可插入片段

以下链接以仓库根目录的 README.md 为基准；可按现有章节调整位置。

```markdown
## 从中文修改到英文回写

导入英文 DOCX，对照阅读中文译文；直接编辑中文，让模型回写对应英文；在差异视图逐处核对后，另存英文 Word。

![双语原生页面](docs/assets/attention-native.png)
![中文原位编辑](docs/assets/attention-edit.png)
![双语编辑差异](docs/assets/attention-diff.png)

以上为 Attention 演示文稿的真实界面，来源与复现说明见 [Demo 说明](examples/attention/README.md)。Word 原生版面主要在 Windows 与 Microsoft Word 环境验证。模型输出需人工检查术语、数值、引用及修改后的含义。

初译支持火山引擎、DeepL、Azure Translator、自托管 LibreTranslate 或通用 LLM；句子映射和英文回写使用 LLM。详见 [翻译服务](docs/translation-services.md)、[厂商适配](docs/provider-adaptation.md)和 [单次费用实测](docs/attention-cost-case.md)。

输出为干净的英文 DOCX 副本与独立 JSON 修改记录，JSON diff 不是 Word Track Changes。安装和配置见 [使用指南](docs/user-guide.md)。
```

## 安装与常见问题

**如何开始？** Windows 上准备 Python 3.12、Node.js 22，下载仓库后在项目根目录 PowerShell 运行 `./setup.ps1`，再运行 `./run.ps1 -OpenBrowser`。打开模型与术语设置，配置并测试服务，导入 DOCX、翻译、编辑、检查并导出。详见 [快速开始](../../../README.md#快速开始)与 [使用指南](../../user-guide.md)。

**必须安装 Word 吗？** Word 原生页面渲染需要 Windows 桌面版 Microsoft Word。结构编辑不依赖 Word；Windows 以外的运行情况尚未完整验证。

**本地运行是否意味着完全离线？** 文稿、译文、草稿和缓存存于本机 `.data/`。使用云端翻译或模型时，相关请求会发送到所选服务；也可配置可用的本地模型服务。具体数据处理以服务商政策和实际配置为准。

**导出是什么？** 生成干净的英文 DOCX 副本，并可保存独立 JSON 修改记录；JSON diff 不是 Word 内置 Track Changes。文字变化可能导致重新换行和分页；遇到待回写、冲突或失效映射时，完整 DOCX 导出需先处理。

**参考文献会自动跳过吗？** 本次 Attention 实测中，40 条参考文献及标题跳过翻译和映射；实际文稿的识别与处理应逐篇检查，详见 [实测说明](../../attention-cost-case.md)。

**API 如何收费？** 软件需自行配置可用服务。专用翻译服务、LLM 映射、英文回写和重试可能分别产生费用，额度和价格由服务商及账号决定；本次约 ¥0.12 仅为指定样本的 DeepSeek 映射，不含火山费用和后续回写，映射修复另计。详见 [费用口径](../../token-cost.md)。

**结果可以直接投稿吗？** 作者应检查翻译、英文回写、专业术语、数字、引用与上下文含义，并在 Word 中检查导出后的排版。
