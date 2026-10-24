# x402 付费包装层（适配 B：RunAPI + Circle）

把 `core/` 的能力包装成「Agent 原生付费」API：**不注册、不发 Key、不预付额度**，
Agent 请求 → 收 402 报价 → 钱包签 USDC 授权 → 重试拿到结果。

---

## 1. 前置条件

| 项 | 说明 | 谁来做 |
|---|---|---|
| EVM 收款钱包地址 | USDC 直接打进这个地址，填 `X402_SELLER_ADDRESS` | **你本人**（详见第 6 节） |
| 公网部署 | 本地 localhost 无法被 Agent 调用 | 部署平台一键完成 |
| Circle 服务注册 | 在 Discovery API 登记，才能被 Agent 发现 | **你本人**（需账号） |

---

## 2. 本地跑通（两步）

```bash
# 终端 1：启动核心服务
cd D:\workbuddy-projects\monetizable-code-service
D:\workbuddy-tools\venvs\code-service\Scripts\python.exe -m uvicorn core.main:app --port 8000

# 终端 2：启动付费网关
cd adapters/x402_wrapper
npm install          # 首次
node paywalled_api.js
```

验证 402 报价是否正常：

```bash
curl -i -X POST http://127.0.0.1:8402/refactor \
  -H "Content-Type: application/json" \
  -d '{"code":"def f(a):\n    return a+1"}'
```

预期：`HTTP/1.1 402`，响应头带 `PAYMENT-REQUIRED`（base64 报价），body 是报价 JSON。

---

## 3. 两种运行模式（必须理解）

| 模式 | 触发条件 | 行为 |
|---|---|---|
| `circle-x402-sdk` | 已配 `X402_SELLER_ADDRESS` **且** `@circle-fin/x402-batching` 装成功 | 走官方中间件，真实链上验签与批结算 |
| `local-quote-only` | 上述任一不满足 | 返回合规 402 报价，但**不验签直接放行**（仅本地联调用） |

`GET /health` 的 `paywall` 字段会告诉你当前是哪一种。
**上线前必须是 `circle-x402-sdk`**，否则等于白送。

---

## 4. 部署

### Docker

```bash
docker build -t code-refactor-x402 .
docker run -d -p 8402:8402 \
  -e X402_SELLER_ADDRESS=0x你的地址 \
  -e X402_NETWORK=base \
  -e CORE_BASE_URL=http://host.docker.internal:8000 \
  code-refactor-x402
```

### Railway

```bash
railway init && railway up
railway variables set X402_SELLER_ADDRESS=0x... X402_NETWORK=base
```

### Fly.io

```bash
fly launch --no-deploy
fly secrets set X402_SELLER_ADDRESS=0x... X402_NETWORK=base
fly deploy
```

> 注意：`CORE_BASE_URL` 必须指向**网关能访问到的**核心服务地址。
> 若 core 与网关同机部署，Railway/Fly 上请用私网地址或把两者合成一个容器。

---

## 5. 提交到 Circle Agent Marketplace

1. 登录 Circle 开发者后台，进入 Agent Marketplace → Services。
2. 提交服务时填：
   - **Service URL**：`https://你的域名/`
   - **OpenAPI**：直接给出 `https://你的域名/openapi.json`（本目录 `openapi.json` 已就绪，把 `servers.url` 改成你的域名）
   - **Pricing**：`/refactor` = `$0.01`，`/semantic` = `$0.005`
3. 平台会主动探测你的 402 报价；探测通过即进入目录。

> Discovery API 的具体端点与鉴权字段以 Circle 官方卖家文档为准。
> 本目录报价结构与 `openapi.json` 已按 x402 v2 语义组织，[x402scan.com](https://x402scan.com) 可直接收录。

---

## 6. 如何拿到收款钱包地址（这一步只能你自己做）

三种方式，按省事程度排序：

1. **已有交易所提现地址**：在你的交易所账户里查 Base 网络的 USDC 充值地址即可。
2. **Coinbase Wallet / MetaMask**：新建账户，切到 Base 网络，复制 `0x...` 地址。
3. **Circle CLI 创建 agent wallet**：在装了 Circle CLI 的机器上执行其 wallet 创建命令，得到一个**托管钱包**地址。

⚠️ 我无法代你创建或保管钱包私钥 —— 涉及资金安全，必须本人持有。
把地址填进 `.env` 的 `X402_SELLER_ADDRESS` 即可，**私钥不要给任何人，也不要写进任何文件**。

---

## 7. 定价建议

| 端点 | 建议价 | 理由 |
|---|---|---|
| `/semantic` | $0.001 - $0.005 | 静态分析，近乎零成本，做引流价 |
| `/refactor` | $0.005 - $0.01 | 有推理成本，但对 Agent 而言仍是"随手可付"区间 |
| 批量/长代码 | 按 unit 加价 | 已在 `x-billable-units` 里分层上报 |

关键原则：**单价压到 Agent 不做比价决策的程度**（< $0.02）。x402 的成交优势是
"无需开户"，一旦单价高了，Agent 就会转去比较订阅制服务。

RunAPI 约束：单次报价上限 10 USDC，当前定价远低于上限，安全。
