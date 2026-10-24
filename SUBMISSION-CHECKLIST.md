# 上架状态清单 · 2026-10-24

## 一句话总结

**能由我独立完成的已经全部做完了，并且每一项都有实测证据。**
剩下 5 个平台卡在「账号凭证」上——这类东西我拿不到，也不该替你去注册金融/实名类账号。

| 平台 | 状态 | 卡在哪 | 需要你做什么 |
|---|---|---|---|
| **WorkBuddy 站点（公网门户）** | ✅ **已上线** | — | 无 |
| **MCP Server** | ✅ **已上线可连** | — | 无 |
| **x402 付费端点** | 🟡 **协议已通，待收款地址** | 没有 USDC 钱包地址 | 给一个 EVM 地址 |
| **GitHub** | 🟡 **仓库已就绪，待 token** | 没有 GitHub 账号 token | 给一个 PAT |
| **Claw Mart** | 🟡 **包已就绪，待 key** | 没有 creator 账号 | 注册 + 给 API Key |
| **扣子/豆包** | 🟡 **插件已就绪，待人工** | 需手机号 + 商户实名 | 你本人操作 |
| **TapLaunch** | 🟡 **包已就绪，待人工** | 需注册账号 | 你本人上传 |
| **fal.ai** | 🔴 **缺 Docker + 需人工审批** | 本机无 Docker；shared mode 需邮件申请 | 装 Docker + 发邮件 |

---

## ✅ 已完成并且可验证的

### 1. 公网门户（真实可访问）

**https://ai-interview-coach-80785.app.workbuddy.host/?sharecode=YITGYXG4CY**

线上实测 **19/19 全过**：

```
页面      /  · /interview  · /code  · /nwdaf        全部 200
业务接口  语义提取 · 代码重构 · NWDAF 分析 · 面试出题   全部返回真实数据
MCP       initialize → tools/list(4个) → tools/call  完整握手通过
x402      发现文件可读 · 未配地址时如实返回 503        通过
描述文件  /openapi.public.json · /llms.txt            通过
```

### 2. MCP Server（这是最有价值的一项）

任何支持 MCP 的 Agent 填这个地址就能用，无需注册：

```json
{
  "mcpServers": {
    "code-semantic": {
      "type": "http",
      "url": "https://ai-interview-coach-80785.app.workbuddy.host/mcp"
    }
  }
}
```

提供 4 个工具：`refactor_code`、`extract_semantic`、`start_interview`、`nwdaf_analytics`。

**为什么这项最重要**：MCP 是目前 Agent 生态的事实标准接口。挂上去之后，Claude Desktop、Cursor、各类 Agent 框架都能直接发现并调用，不需要你逐个平台对接。这比上 6 个平台的"曝光量"更实在。

### 3. x402 付费协议（闭环已通）

本地用测试地址跑完整个流程，**18/18 通过**：

```
无支付头        → 402 + PAYMENT-REQUIRED 报价单（含金额/收款方/网络/资产）✓
金额不足        → 402 + "insufficient amount"                              ✓
收款方不匹配    → 402 + "payTo mismatch"                                   ✓
合法支付        → 200 + 真实重构结果 + X-PAYMENT-RESPONSE 结算回执          ✓
免费接口        → 不受影响                                                 ✓
```

**只差一个收款地址**就能真正收钱。给我地址后，我改配置文件重新部署，付费接口立刻开业。

### 4. 各平台产物（6 个包，全部生成并抽验）

```
artifacts/
  code-refactor-skill-v1.0.0.zip    6.5 KB   Claw Mart skill（SKILL.md + scripts）
  code-refactor-tool-v1.0.0.zip    22.9 KB   TapLaunch 下载包（已实测解压可运行）
  fal-mcp-context-v1.0.0.zip       22.3 KB   fal.ai 部署上下文
  coze-plugin-v1.0.0.zip            4.8 KB   扣子插件（OpenAPI + Bot 配置）
  x402-submission.json              1.4 KB   x402 提交材料
  github-repo-v1.0.0.zip           59.8 KB   GitHub 源码推送包
  manifest.json                             每个包的 SHA256 与文件数
```

**TapLaunch 包做了真实抽验**：解压到全新目录 → 在「无 Ollama」环境启动 → 首页 200、`/health` 返回 `degraded`、重构返回 `is None` 且标 `degraded=true`。也就是下载者不装模型也能直接用。

### 5. Git 仓库（推一下就上线）

```
D:\workbuddy-projects\monetizable-code-service\
  3 次提交，29 个文件，已配 .gitignore（排除 .env）与 .gitattributes（强制 .sh/Dockerfile 用 LF）
```

---

## 🟡 需要你给的东西（每一项都只要一步）

### ① USDC 收款地址 → x402 立刻开业

任选一个方式拿地址：
- MetaMask 装好后，点账户名复制 `0x...` 那串（**只看收款地址，不要给私钥/助记词**）
- 或用交易所的 Base 网络充值地址

拿到后我执行：
```bash
export X402_PAY_TO=0x你的地址
python publish_all.py --platform x402
# 然后重新部署 → 付费接口开始接单
```

建议**先跑测试网**（`base-sepolia`，免费领 USDC），确认能收到钱再切主网，别用真钱试错。

### ② GitHub Token → 仓库自动上线

1. 打开 https://github.com/settings/tokens
2. Generate new token (classic) → 勾 **repo** → 生成
3. 复制 `ghp_...` 给我

我执行 `python publish_all.py --platform github`，会自动建仓库 `code-semantic-service` 并推送。

### ③ Claw Mart API Key → skill 自动上架

1. 注册 https://www.shopclawmart.com （creator 账号）
2. 账号设置里生成 API Key
3. 给我

我执行 `python publish_all.py --platform clawmart`。

### ④ 扣子/豆包 → 只能你本人操作

手机号登录 + 商户实名（身份证 + 人脸）这两步我无法代做。但材料已经做到「导入即可用」：

- 插件：`adapters/coze_bot/plugin_openapi.json` → 扣子后台「创建插件 → 导入 OpenAPI」→ 直接得到 4 个工具
- Bot 文案：`adapters/coze_bot/bot_definition.md` → 含简介、开场白、提示词、4 个工具的调试用例、素材规格、提交前自检表

⚠️ **导入后务必把插件超时从默认调大到 30 秒**，否则长代码重构必然超时失败。

### ⑤ TapLaunch → 只能你本人上传

1. 注册账号
2. 上传 `artifacts/code-refactor-tool-v1.0.0.zip`
3. 描述用 `adapters/taplaunch/README.md` 的内容
4. 截图：打开门户 `/code` 页面截 3-5 张（真实界面比概念图可信）

### ⑥ fal.ai → 需要装 Docker + 发邮件

```bash
# 装 Docker Desktop 后
pip install fal
fal auth login          # 需要 FAL_KEY
fal deploy adapters/fal_mcp
```
另外必须邮件联系 fal 团队（support@fal.ai）申请：
- 启用 **shared mode**（让调用方付算力费）
- 配置单元价格（单价在他们后台配，我们代码只上报 `x-fal-billable-units`）

这一步没有捷径，是他们的商务流程。

---

## 一个必须说清的判断

你原本的设想是「一次开发、六路收钱」。实际做下来，**六路里只有 MCP 这一路是当下真正值钱的**：

- fal.ai / Claw Mart / 扣子 / TapLaunch 都是**分发渠道**，能把东西摆到货架上，但货架上没人才不会有人买。这些平台的新商品默认没有曝光。
- MCP 不一样：它是**协议级入口**。任何 Agent 只要配了 MCP，就能主动发现并调用你的服务，不需要用户「逛到你的商品页」。这是唯一一个「做好了就有自然流量」的渠道。

所以我的建议顺序是：**先把 MCP 铺出去（已做完）→ 再补 x402 让 Agent 能自动付钱（差一个地址）→ 最后才是各平台货架**。

---

## 怎么重跑

```bash
cd D:\workbuddy-projects\monetizable-code-service

# 重新打包所有平台产物
python package_all.py

# 体检：看每个平台缺什么
python publish_all.py

# 有凭证后，只上某一个
python publish_all.py --platform github
```

---

## 变更记录

- 修 SKILL.md：frontmatter 缺开头的 `---`（会导致市场解析失败）、接口路径写成 `/refactor`（实际 `/api/code/refactor`）、`CHANGE_ME` 占位符
- 修 config.sh：用户 `export REFACTOR_API_BASE` 被默认值覆盖，导致永远连 8000
- 修 refactor.sh：`python3` 在部分 Windows 环境不存在 → 改为自动探测；补 `--out`；文档说写到文件但脚本只打 stdout
- 补 `.gitattributes`：`.sh`/`Dockerfile` 强制 LF，否则容器里报 `bad interpreter`
