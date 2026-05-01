# MailKnow - 跨生态邮件知识引擎

> **让邮件成为你的知识库，而不是负担。**

![MailKnow](https://img.shields.io/badge/version-1.0.0-blue) ![License](https://img.shields.io/badge/license-MIT-green) ![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey)

---

## 📖 简介

MailKnow 是一款跨生态邮件知识引擎，帮助用户从海量邮件中提取关键信息、自动分流、智能推荐，让邮件管理更高效。

### 核心能力

| 功能 | 说明 |
|------|------|
| **Gate 5级分流** | 智能分流邮件到 ⭐重要/📬一般/🔔通知/🗑️垃圾，准确率>92% |
| **审批汇总** | 自动识别审批邮件，置信度分级，小额简化流程，大额二次确认 |
| **场景推荐** | 审批提醒、周报推荐、报价聚合，每日≤5张卡片防疲劳 |
| **周报生成** | 确定性推导生成，事实准确率>90%，不含"下周计划"预测 |
| **邮件知识库** | Hybrid Search + 实体关系图谱，"和某人往来的邮件"一键可查 |

### 技术特点

- **纯本地存储**：邮件数据存储在本地 PGLite，隐私安全
- **低 Token 成本**：Gate分流纯规则(0 token)，重度用户月成本≤$9
- **LLM 降级**：LLM不可用时自动降级到纯GBrain模式，核心功能保留
- **跨平台支持**：macOS + Windows 双平台安装包

---

## 🚀 快速开始

### 下载安装

| 平台 | 下载地址 |
|------|---------|
| macOS | [DMG安装包](https://github.com/were37114/mailknow/releases) |
| Windows | [EXE安装包](https://github.com/were37114/mailknow/releases) |

### 配置邮箱

1. 打开 MailKnow，进入 **设置** 页面
2. 点击 **添加邮箱账号**
3. 输入邮箱地址和密码（支持 IMAP）
4. 点击 **同步** 开始拉取邮件

### BYOK（自带 API Key）

如果使用 LLM 功能（审批精筛、周报生成等），可配置自己的 API Key：

1. 进入 **设置** → **LLM 配置**
2. 输入 GPT-4o-mini 或 Haiku API Key
3. 设置月度 Token 预算（默认 $9）

---

## 📁 项目结构

```
mailknow/
├── src/                    # Python 后端
│   ├── core/               # GBrain 核心引擎
│   │   ├── gate/           # Gate 5级分流
│   │   ├── wiring/         # Self-wiring 链接提取
│   │   ├── search/         # Hybrid Search
│   │   ├── minion/         # Minion 异步 Worker
│   │   ├── truth/          # compiled_truth
│   │   └── entity/         # 实体对齐
│   ├── sync/               # 邮件同步引擎
│   ├── llm/                # LLM 增强层
│   ├── scenes/             # 场景引擎
│   ├── db/                 # 数据层
│   └── api/                # IPC API
├── client/                 # Electron 前端
│   ├── main/               # Electron 主进程
│   ├── renderer/           # React 渲染进程
│   │   ├── components/     # UI 组件
│   │   └── pages/          # 页面
│   └── preload/            # Preload 脚本
├── tests/                  # 测试套件
│   ├── unit/               # 单元测试（497个）
│   ├── integration/        # 集成测试
│   ├── datasets/           # 测试数据集
│   └── perf/               # 性能测试
├── phase0_report.md        # Phase 0 验收报告
├── tests/ACCEPTANCE_TEST_PLAN.md  # 验收测试计划
├── TODO.md                 # 未完成事项清单
└── README.md               # 本文档
```

---

## 🔧 开发指南

### 本地开发

```bash
# 克隆仓库
git clone https://github.com/were37114/mailknow.git
cd mailknow

# 安装 Python 依赖
pip install -r requirements.txt

# 安装 Node 依赖
cd client
npm install

# 开发模式运行
npm run dev
```

### 运行测试

```bash
# 单元测试
pytest tests/unit/ -v

# 集成测试
pytest tests/integration/ -v

# 性能测试
python tests/perf/test_10k_performance.py --count 50000
```

### 打包发布

```bash
# macOS 打包
cd client
npm run dist:mac

# Windows 打包（需要 GitHub Actions）
# 自动构建：.github/workflows/build-windows.yml
```

---

## 📊 性能指标

| 指标 | 目标 | 实测 |
|------|------|------|
| Gate分流准确率 | >92% | 待验证 |
| 搜索响应 P95 | <500ms | 待压测 |
| 重度用户Token成本 | ≤$9/月 | 设计达标 |
| LLM降级响应时间 | <10s | 设计达标 |

---

## 🛡️ 安全与隐私

- **本地存储**：所有邮件数据存储在本地 PGLite，不上传云端
- **脱敏引擎**：人名/手机/邮箱/身份证/金额/密码自动脱敏
- **IPC鉴权**：随机token + Unix Domain Socket，防止外部访问
- **BYOK**：用户自带 API Key，敏感数据不经第三方

---

## 📝 版本历史

### V1.0.0 (2026-05-01)

- ✅ Gate 5级分流 + 4档视图
- ✅ 审批汇总 + 小额/大额审批流程
- ✅ 场景推荐 + 反馈飞轮
- ✅ 周报生成 + 编辑器
- ✅ Hybrid Search + 实体关系图谱
- ✅ Token预算控制器 + 降级机制
- ✅ 脱敏引擎 + IPC鉴权
- ✅ macOS + Windows 安装包

---

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE)

---

## 🙏 致谢

- Enron Email Dataset - 测试数据来源
- bge-small-zh - 本地 Embedding 模型
- pgvector - 向量搜索索引
- Electron - 跨平台桌面框架

---

## 📮 联系方式

- GitHub: https://github.com/were37114/mailknow
- Issues: https://github.com/were37114/mailknow/issues

---

> **MailKnow - 让邮件成为你的知识库**