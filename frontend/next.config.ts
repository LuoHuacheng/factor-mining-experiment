import type { NextConfig } from "next";

// 通过容器名访问 backend(同 docker network,不经过宿主端口)
const BACKEND_URL =
  process.env.BACKEND_URL ?? "http://backend:8001";

const nextConfig: NextConfig = {
  output: "standalone",
  // 关闭开发态左下角黑色「N」DevTools 指示球
  devIndicators: false,
  // 同域转发:浏览器请求 /api/* 由 Next.js server 反代到后端
  // 解决 HTTPS 域名(qh.00n.top)访问时调用 HTTP API 的混合内容/CORS 问题
  //
  // 注意：rewrites 用 http-proxy，默认 ~30s 超时且不可配置（见 Next.js #36586）。
  // 因子实验室的 LLM 生成 / GP 搜索常需 1-3 分钟，会触发 30s socket hang up。
  // 故排除 /api/factor-lab/* —— 这些路径改由 Route Handler
  // (app/api/factor-lab/[...path]/route.ts) 接管，该 handler 配置了 5 分钟超时
  // 与完善的错误处理。其余 /api/* 仍走 rewrites。
  async rewrites() {
    return [
      {
        source: "/api/:path((?!factor-lab).*)",
        destination: `${BACKEND_URL}/api/:path*`,
      },
      {
        source: "/ws/:path*",
        destination: `${BACKEND_URL}/ws/:path*`,
      },
    ];
  },
};

export default nextConfig;
