# Sequence Network Implementation Plan

**Goal:** 双尺度GRU序列学习与更稳健的状态规则。
**Architecture:** 保留现有成熟标签队列/风控执行器；通过模型特征、双头推理及更新钩子接入PyTorch，新增独立序列数据与网络模块。
**Tech Stack:** Python3.12、NumPy/PyTorch可选依赖、React/TypeScript。
**Spec:** docs/superpowers/specs/2026-09-18-sequence-network.md

- [x] 序列输入：`sequence_features.py` 统一离线/运行OHLCV token、完成5分钟聚合、短长窗口；测试未来前缀、跨日/缺口聚合、归一化padding。
- [x] 网络：`sequence_model.py` 实现因果卷积/GRU/attention、双头BCE+Huber、训练教师、成熟样本回放、CPU序列化与CUDA设备选择；`timeseries.py`只抽取必要钩子。
- [x] 规则：`strategies.py` 新增trend_pullback/regime_adaptive，保持旧规则行为；测试入场、下跌拒绝、冻结退出模式与风险预算。
- [x] 界面与保存：可选GRU、更新间隔与学习率，发布元数据allowlist、Torch版本检查、安装文档。
- [ ] 研究：固定候选与验证分段稳定性，完成新数据检查；冻结选择后才运行新最终测试，记录成本后表现。
- [ ] 验证：关键因果/持久化/股票隔离测试、既有回归、Ruff、前端build、独立代码审查；提交推送，运行结束后重启本地API。
