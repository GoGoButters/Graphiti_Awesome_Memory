FROM node:20-alpine as build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
# Pinned toolchain from package-lock (tsc + vite are devDependencies)
RUN npm ci --no-audit --no-fund
# Sources + frontend/.env (VITE_* are baked in at build time)
COPY frontend .
RUN npx tsc && npx vite build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/nginx/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
