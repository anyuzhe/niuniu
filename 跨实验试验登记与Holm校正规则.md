# 跨实验固定检验族：本地登记与 Holm 校正 1.1.0

本功能在多个独立启动的单因子/组合研究实验之间固定检验族，沿用现有日均 IC/Rank IC 日期块符号检验。它不修改原实验或原研究内校正，也不把事后汇总称为正式预注册。

## 登记、绑定、报告

1. `trials-create --plan PLAN.json --output NEW_REGISTRY`：冻结 name、alpha、trials，单实验每项包括安全且唯一的 trial_id 和完整 ExperimentConfig 序列化 config；父研究另加下文 study。相同配置重复登记被拒绝。每项必须开启 permutation，自动登记全部 horizons × daily_mean_ic/daily_mean_rank_ic，不能挑选部分显著指标。
2. `trials-bind --registry REGISTRY --trial-id ID --artifact RUN_DIRECTORY`：校验配置完全匹配，接受 completed 或 failed 的已登记单实验或下文四类父研究产物。完成实验必须包含全部计划原始检验。绑定保存完整记录、源路径、源文件 SHA256、本地绑定时间和指纹。只允许绑定一次；同一文件内容重复交付 unchanged，不同结果替换被拒绝。
3. `trials-report --registry REGISTRY --output NEW_REPORT`：按登记顺序收集全部假设，直接使用 metrics 中的原始 p_value 重算 Holm，忽略原记录中的 p_holm。复制计划及已绑定记录到报告目录，保存 JSON 和 Markdown。

创建登记和报告的目标目录必须不存在。结果绑定先在同目录完整写入临时文件，再以原子硬链接发布；并发竞争不能覆盖已绑定结果，要求文件系统支持硬链接。报告读取每项绑定一次；并发进行绑定时，报告可能包含部分已绑定试验，未读取到的结果按未运行保留名额。报告不是跨所有条目的事务快照，但其实际使用记录全部保存在 bindings.json。

完整 config 应由 `ExperimentConfig` 的 `asdict`/encode 生成，包含默认字段；仅填参数片段不会匹配实际实验配置。配置登记不自动运行研究，也不锁定未来代码环境、行情或资格资料；实际结果中的运行环境、数据来源及因子指纹随原记录保存。

## 校正口径

每个登记持有期有两个固定检验名额。未绑定试验的全部检验标 not_run；失败单实验标 failed；失败父研究保留已经产生的原始检验，仅未产生部分标 failed；原检验不满足有效日期块要求时保持 unavailable。三者的 p_value、p_holm、拒绝判定均为 null，仍计入 Holm 的总假设数，在内部相当于保留 p=1 的位置。

Holm 在有效原始 p 值上排序，以固定总名额做逐步放大并保持调整 p 值单调。不拿各实验已调整 p 值再次校正。Holm 本身允许检验之间依赖，但要求每个原始 p 值有效；原日期块符号对称、块间假设和重叠标签限制仍然存在。

根实验配置必须与登记 config 完全相等。1.1 支持下文四类父研究及消融中的配对 IC 差异；theory_study 最外层和执行净收益检验仍不接受。不能把部分子实验挑出来登记后，声称控制了原完整父研究或此前探索。

## 时间与防误用边界

- record.created_at 早于本地登记时刻，报告标 retrospective。
- 不早于本地登记，标 after_local_registration；这仅是两个本地时间戳的比较，不证明用户此前没有见过数据或跑过其他研究。
- 文件指纹用于发现意外变更，不是防恶意篡改或可信第三方时间戳；具有文件写权限者能修改文件并重新计算指纹。
- 多次生成报告不会减少计划名额，但本功能不控制反复查看、择时停止、另建检验族或登记之外的探索。部分结果到达时的报告是进度快照，不是序贯显著性检验方案。
- 报告使用绑定副本，因此原来源文件移动或删除不会改变已有绑定和报告。不同复跑结果不能替换该试验已有绑定；新增计划须使用新登记，旧记录保留，不自动合并新旧族。

## 可复现验收

```sh
.venv/bin/python examples/verify_trial_registry.py --output artifacts/trial-registry-recheck
```

脚本先登记四个配置，再读取固定二十证券行情，执行两项动量研究、一个故意无效参数失败对照，并保留一个未运行试验。通过真实 CLI 创建、绑定、重复绑定、报告，核对 24 个计划检验名额及 12 个可用原始检验。失败对照用于验证记录流程，不是市场研究结果。

实际证据见 [验收报告](artifacts/trial-registry-acceptance/report.md)。本功能补跨实验固定族管理；稳定性/子样本检验、真实控制资料验收、theory_study 最外层登记和工作台入口仍未完成。

## 1.1 父研究设计与自动布局

兼容 1.0 单实验登记。新建登记版本为 1.1.0；单实验仍使用原字段。父研究 trial 另含 `study: {kind, design}`，完整 config 不变。支持：

| kind | design 必需字段 | 自动计划范围 |
|---|---|---|
| ablation | 空对象 `{}` | 完整版本及每个删减版本；incremental_test=true 时同时包含每个删减项的配对 IC/Rank IC 差异 |
| holdout | split，包含 train_end/valid_end | train/valid/test 全部持有期和两个指标 |
| walkforward | schedule，包含 train_days/valid_days/test_days | 所有完整窗口、全部阶段 |
| sweep | grid（包含 parameters）、split、schedule，未使用者必须为 null | 所有参数组合；无分段时 all，否则所有固定分段或滚动阶段 |

split/schedule 不能同时设置；日期为 ISO 日期。grid 使用与 ParameterGrid 序列化相同的结构，例如 `{"parameters":{"lookback":[10,20]}}`。消融必须使用组合因子且至少有两个输入；incremental_test 只允许消融。

布局复用现有枚举器和日期窗口计算器，不读取行情。自动保存 layout，用户输入中不能手填 layout。冻结后重新加载会校验当前枚举器生成的布局是否一致；实现变化造成布局不同会拒绝，不能静默缩减旧族。完整源记录仍另存运行时、因子和数据快照，此校验并非跨机器完整环境锁定。

Holdout 使用可拟合 PipelineConfig 时，必须登记实际生效的 fit_start=data.start、fit_end=split.train_end，避免执行器自动补充边界后与登记配置不同。滚动内部的各窗口拟合继续由既有引擎处理，不在登记中手动伪造训练结果。

完成父记录必须覆盖全部计划子项、阶段、参数及原始检验；遗漏、重复、额外子项或配置/设计变更均拒绝。按 removed/name/phase/参数/窗口身份匹配而非依赖显示顺序；报告中的索引路径来自冻结布局。

失败父记录允许部分子项存在，但它们仍须符合计划，已有检验必须完整且有效；已产生的 p 值保留，未产生部分为 null 并继续占名额。报告还拒绝跨登记条目重复出现同一根或后代 run_id，防止把同一父/子运行重复计入。不声称识别不同 run_id 下全部语义重复的研究。

配对指标为 daily_mean_ic_difference、daily_mean_rank_ic_difference，方向是完整组合有符号 IC 减删减版本；它们和各子实验的原始 IC 检验共同校正，不按各子项旧 p_holm 计算。理论全流程最外层、执行净收益配对族仍未实现。

真实四类父研究与旧登记兼容性证据见 [1.1 验收](artifacts/parent-trial-acceptance/report.md)。
