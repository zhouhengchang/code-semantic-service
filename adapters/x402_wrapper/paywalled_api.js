/**
 * x402 付费包装层
 * ============================================================
 * 作用：
 *   在 core 服务前面加一层「按次收费」的墙。Agent 请求未付费时收到
 *   402 + 报价，用钱包签 EIP-3009 授权后重试即可拿到结果 —— 无需
 *   注册账号、无需 API Key、无需预付额度。
 *
 * 双模式设计（重要）：
 *   1) sdk 模式：检测到 @circle-fin/x402-batching 已安装时，用官方
 *      中间件做真正的链上结算校验。
 *   2) 本地模式：未装 SDK 时自动降级为「标准 402 报价中间件」。
 *      它会返回完全合规的 PAYMENT-REQUIRED 报价头，但不做链上验签 ——
 *      用于本地联调 / 给 RunAPI 抓取 openapi 与报价结构。
 *      上线前必须装齐依赖切到 sdk 模式。
 *
 * 运行：
 *   npm install && npm start
 *   环境变量见 .env.example（X402_SELLER_ADDRESS 必须配置才会进入 sdk 模式）
 */

'use strict';

const express = require('express');

// ------------------------------------------------------------
// 配置（全部来自环境变量，不硬编码任何凭证）
// ------------------------------------------------------------
const PORT = parseInt(process.env.X402_PORT || '8402', 10);
const CORE_BASE_URL = (process.env.CORE_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
const SELLER_ADDRESS = process.env.X402_SELLER_ADDRESS || '';
const NETWORK = process.env.X402_NETWORK || 'base';
const PRICE_REFACTOR = process.env.X402_PRICE_REFACTOR || '$0.01';
const PRICE_SEMANTIC = process.env.X402_PRICE_SEMANTIC || '$0.005';
const CORE_TIMEOUT_MS = parseInt(process.env.CORE_TIMEOUT_MS || '300000', 10);

// ------------------------------------------------------------
// 尝试加载 Circle x402 中间件
// ------------------------------------------------------------
let gateway = null;
let sdkMode = false;

function tryInitGateway() {
  if (!SELLER_ADDRESS) {
    console.warn('[x402][warn] 未配置 X402_SELLER_ADDRESS —— 无法进入 sdk 计费模式');
    return null;
  }
  try {
    // eslint-disable-next-line global-require
    const { createGateway } = require('@circle-fin/x402-batching');
    const gw = createGateway({
      sellerAddress: SELLER_ADDRESS,
      network: NETWORK,
    });
    sdkMode = true;
    console.log(`[x402] Circle Gateway 已初始化，seller=${SELLER_ADDRESS} network=${NETWORK}`);
    return gw;
  } catch (err) {
    console.warn(`[x402][warn] x402 SDK 不可用（${err.message}），降级为本地报价模式`);
    return null;
  }
}

/**
 * 本地模式中间件：返回标准 402 报价。
 * 报文遵循 x402 v2 的报价语义：
 *   - HTTP 402
 *   - PAYMENT-REQUIRED 头：base64(JSON) 形式的付款要求
 *   - body 里同时给出人类可读的报价明细（便于调试与 RunAPI 抓取）
 */
function localPaywall(priceUSD, routeName) {
  return function paywall(req, res, next) {
    const paidHeader = req.header('X-PAYMENT') || req.header('PAYMENT-SIGNATURE');

    if (!paidHeader) {
      const quote = {
        x402Version: 2,
        error: 'payment_required',
        accepts: [
          {
            scheme: 'exact',
            network: NETWORK,
            maxAmountRequired: priceUSD,
            resource: req.originalUrl,
            description: `code-refactor ${routeName}`,
            payTo: SELLER_ADDRESS || '0x0000000000000000000000000000000000000000',
            asset: 'USDC',
            mimeType: 'application/json',
            maxTimeoutSeconds: 60,
          },
        ],
      };
      const encoded = Buffer.from(JSON.stringify(quote)).toString('base64');
      res.set('PAYMENT-REQUIRED', encoded);
      res.set('WWW-Authenticate', `x402 ${encoded}`);
      return res.status(402).json(quote);
    }

    // 本地模式不验签：仅做结构存在性检查，便于把链路跑通
    console.warn(`[x402][warn] 本地模式未验签，直接放行 ${routeName}。上线请装齐依赖`);
    return next();
  };
}

// ------------------------------------------------------------
// 应用组装
// ------------------------------------------------------------
gateway = tryInitGateway();

const app = express();
app.use(express.json({ limit: '5mb' }));

/** 给每个响应补上计费单元头，RunAPI / fal 之类平台可据此核算 */
app.use((req, res, next) => {
  res.set('x-service', 'code-refactor');
  res.set('x-version', '1.0.0');
  next();
});

/** 免费路由：健康检查永远不收钱，否则 Agent 无法探活 */
app.get('/health', async (req, res) => {
  try {
    const r = await fetch(`${CORE_BASE_URL}/health`, {
      signal: AbortSignal.timeout(10000),
    });
    const data = await r.json();
    res.status(r.status).json({
      ...data,
      paywall: sdkMode ? 'circle-x402-sdk' : 'local-quote-only',
    });
  } catch (err) {
    res.status(503).json({ error: 'core_unreachable', detail: err.message });
  }
});

/** 付费路由检查函数：sdk 模式走 gateway.require，本地模式走报价中间件 */
function requirePayment(price, routeName) {
  if (sdkMode && gateway && typeof gateway.require === 'function') {
    return gateway.require(price);
  }
  return localPaywall(price, routeName);
}

/** 通用转发：把请求体原样交给 core，把 core 的响应头一并带回 */
async function forward(req, res, path, tag) {
  try {
    const r = await fetch(`${CORE_BASE_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req.body),
      signal: AbortSignal.timeout(CORE_TIMEOUT_MS),
    });
    const units = r.headers.get('x-billable-units');
    if (units) res.set('x-billable-units', units);

    const text = await r.text();
    let payload;
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { raw: text };
    }
    res.status(r.status).json(payload);
  } catch (err) {
    console.error(`[x402][error] ${tag} 转发失败:`, err.message);
    res.status(503).json({
      error: 'core_unreachable',
      detail: `无法访问核心服务 ${CORE_BASE_URL}${path}：${err.message}`,
    });
  }
}

app.post('/refactor', requirePayment(PRICE_REFACTOR, 'refactor'), (req, res) =>
  forward(req, res, '/refactor', 'refactor')
);

app.post('/semantic', requirePayment(PRICE_SEMANTIC, 'semantic'), (req, res) =>
  forward(req, res, '/semantic', 'semantic')
);

/** 免费元信息：RunAPI / Circle Discovery 抓取服务描述用 */
app.get('/', (req, res) => {
  res.json({
    service: 'code-refactor',
    version: '1.0.0',
    paywall: sdkMode ? 'circle-x402-sdk' : 'local-quote-only',
    seller: SELLER_ADDRESS || null,
    pricing: { '/refactor': PRICE_REFACTOR, '/semantic': PRICE_SEMANTIC, '/health': '$0' },
    endpoints: ['POST /refactor', 'POST /semantic', 'GET /health'],
  });
});

/** 免费：OpenAPI 描述，供 RunAPI 收录与 Agent 自描述 */
app.get('/openapi.json', (req, res) => {
  res.sendFile(require('path').join(__dirname, 'openapi.json'));
});

app.listen(PORT, () => {
  console.log(`[x402] 付费网关已启动 http://0.0.0.0:${PORT}`);
  console.log(`[x402] 模式: ${sdkMode ? 'Circle x402 SDK（真实链上校验）' : '本地报价模式（未验签）'}`);
  if (!sdkMode) {
    console.log('[x402] 上线前请：npm install 齐依赖 + 配置 X402_SELLER_ADDRESS');
  }
});
