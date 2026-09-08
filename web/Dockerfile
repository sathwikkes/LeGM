# LeGM web (Next.js). Build from the repo root:
#   docker build -t legm-web --build-arg NEXT_PUBLIC_API_URL=https://api.example.com -f web/Dockerfile web
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S legm && adduser -S legm -G legm
COPY --from=build --chown=legm:legm /app/.next/standalone ./
COPY --from=build --chown=legm:legm /app/.next/static ./.next/static
COPY --from=build --chown=legm:legm /app/public ./public
USER legm
EXPOSE 3000
CMD ["node", "server.js"]
