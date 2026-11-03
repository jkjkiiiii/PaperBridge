# PaperBridge 宣传素材包

完成日期：2026-11-04。八张 PNG 均为 1080 × 1920（9:16），可直接配合 publish-copy.md 使用。gallery.html 为总览，index.html 为可编辑设计源文件（?slide=1..8）。

## 发布组合

- 产品首发：01 → 02 → 03 → 04 → 05 → 08。
- 费用实测：07 → 06 → 02 → 04 → 08。
- API 与本地模型：06 → 03 → 04 → 08。
- 朋友圈：01/04/05 或 07/06/08；配套两条文案见 publish-copy.md。
- GitHub README：使用现有横版截图及文案中的插入片段，避免八张长图挤占文档。

## 图像来源与口径

1. 封面为原创排版示意，非软件截图、非真实研究结论。
2. 对照、原位编辑和 diff 复用 docs/assets/attention-native.png、attention-edit.png、attention-diff.png，裁剪放大未改变截图内容。这是 Attention 短演示，不是全文计费测试。
3. tasks.jpg 是 2026-11-04 当前应用的真实任务分配界面，未改动配置。
4. references.png 是 Attention 全文项目真实参考文献保留英文界面的裁剪；未展示私人稿件列表。
5. attention-export.docx 来自 Attention Is All You Need - Demo.docx 实际导出接口。export.png 来自该 DOCX 经 Microsoft Word 导出的 PDF 页面，已核对含 solely；不是 Word 应用窗口截图。
6. 第七张费用引用 docs/attention-cost-case.md 与 examples/attention/cost-summary.json：98,982 tokens、约 ¥0.12 仅为本次 DeepSeek 句子映射，不含后续回写。火山免费与否取决于剩余额度；额外修复约 ¥0.0029 单列。
7. API 名称表示已提供接入适配，不表示每个服务和模型都经过真实账号联调。消费者订阅不等于 API 额度。

## 内容权利

PaperBridge 代码按仓库 MIT 许可证。Attention 示例与论文内容的来源和许可说明请参见仓库 examples/attention/README.md、THIRD_PARTY_NOTICES.md；第三方论文内容不因本素材包而改为 MIT。服务名称仅作兼容说明，不表示官方合作。

本次仅制作本地素材，没有代发社交平台或推送 GitHub。

## 清晰度修订（2026-11-04）

封面仅对改动词句着色，相同文字保留。hires/ 包含 2160×3840 高清版，根目录保留 1080×1920 发布版。HTML/CSS 文字在两倍尺寸重新渲染，而非放大旧海报；旧界面截图仍受原始像素限制。第 4 图新增清晰的 diff 文字转录，第 6 图聚焦任务选择区域。overview.png 仅为选图缩略预览，请查看单张原图判断清晰度。截图工具输出 JPEG，之后保存为 PNG 不会消除原有压缩；高清版主要提升重新排版文字的清晰度。
