# 可复制的 AI 请求

## 开发一个任务包

```text
请执行 docs/learning-plan/STATUS.json 中的 nextTaskId，只做这一包。
先读 docs/learning-plan/README.md、EXECUTION.md、CONTRACTS.md、TESTING.md、对应任务卡和前置任务交接。
核实当前代码与依赖产物，不假设文档中的未来接口已经存在。
实现当前包并执行要求的测试，保持旧视频功能兼容。
缺少环境或证据时如实写 VERIFY_PENDING/BLOCKED；不以 mock 结果冒充集成或模型质量验证。
完成后更新 STATUS.json 和 handoffs/Txx.md，给出变更、测试证据和下一包，不自动开发后续包。
```

## 恢复中断任务

```text
恢复任务 Txx。先核对 STATUS.json、handoffs/Txx.md 和当前文件变化。
从已验证状态继续，不重新实现已完成步骤，也不跳过未执行的验收。
发现交接与代码不一致先报告具体差异并纠正记录。
```

## 复核一个任务包

```text
复核任务 Txx，检查实际代码是否满足卡片和共享契约。
重点看越权、异步重复、版本/删除一致性、旧功能回归与测试是否真的执行。
报告按严重程度列出可复现问题及具体文件；没有证据不要臆测问题。
本轮只复核，不扩展功能。必要时将任务改为 VERIFY_PENDING 并记录须补验的项。
```

## 检查阶段门禁

```text
检查 docs/learning-plan/TESTING.md 中的 Gx 门禁。
核对对应任务交接与真实报告，执行缺少的必要验证。
分别记录 PASS/FAIL/NOT_RUN/BLOCKED，更新 STATUS.json.gates。
不因任务都标 DONE 就推断端到端与模型评估已通过。
```
