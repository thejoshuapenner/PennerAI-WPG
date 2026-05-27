/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: process.env.NODE_ENV === 'development' ? '/tmp/next-penner-ai-wpg-dev' : '.next',
  webpack: (config, { dev }) => {
    if (dev) {
      config.cache = false;
    }
    return config;
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL || 'https://wa-policy-graph-backend.onrender.com'}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
