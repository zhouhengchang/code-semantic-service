# ============================================================
# x402 付费网关镜像
# ------------------------------------------------------------
# 构建：docker build -t code-refactor-x402 .
# 运行：docker run -p 8402:8402 \
#         -e X402_SELLER_ADDRESS=0x... \
#         -e CORE_BASE_URL=http://host.docker.internal:8000 \
#         code-refactor-x402
# ============================================================
FROM node:20-slim

WORKDIR /app

# 先装依赖，利用层缓存
COPY package.json ./
# 用 --omit=dev 去掉开发依赖；若 SDK 装不上也不阻塞启动（会自动降级为报价模式）
RUN npm install --omit=dev || npm install --omit=dev express

COPY . .

ENV X402_PORT=8402 \
    NODE_ENV=production

EXPOSE 8402

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:'+(process.env.X402_PORT||8402)+'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "paywalled_api.js"]
