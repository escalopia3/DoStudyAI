# DoStudy Web

Vue 3 课程工作台。开发服务器将 `/api/v2` 请求代理到 `http://127.0.0.1:8092`。在仓库根目录 `.env` 中设置 `VITE_V2_PROXY_TARGET` 可修改代理目标。

```bash
npm ci
npm run dev
npm test
npm run build
```

部署 `dist/` 时，在同一站点将 `/api/v2` 转发给 FastAPI Gateway。流式响应需要关闭代理缓冲。
