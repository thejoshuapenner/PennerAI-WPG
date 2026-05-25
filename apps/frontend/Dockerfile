# Dockerfile for Next.js App
FROM node:18-alpine AS base

# Install dependencies only when needed
FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Copy root configuration and package.json files
COPY package.json turbo.json ./
COPY apps/frontend/package.json ./apps/frontend/

# Install dependencies
RUN npm install

# Rebuild the source code only when needed
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/frontend/node_modules ./apps/frontend/node_modules
COPY . .

# Disable telemetry
ENV NEXT_TELEMETRY_DISABLED 1

# Run build
RUN npm run build -- --filter=frontend

# Production image, copy all the files and run next
FROM base AS runner
WORKDIR /app

ENV NODE_ENV production
ENV NEXT_TELEMETRY_DISABLED 1

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

COPY --from=builder /app/apps/frontend/public ./apps/frontend/public
COPY --from=builder --chown=nextjs:nodejs /app/apps/frontend/.next ./apps/frontend/.next
COPY --from=builder /app/apps/frontend/package.json ./apps/frontend/package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/apps/frontend/node_modules ./apps/frontend/node_modules

USER nextjs

EXPOSE 3000

ENV PORT 3000
ENV HOSTNAME "0.0.0.0"

CMD ["npm", "run", "start", "--workspace=apps/frontend"]
