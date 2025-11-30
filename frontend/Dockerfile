FROM node:18-alpine as build

WORKDIR /app
COPY frontend/package.json .
RUN npm install
# Install typescript and vite globally to ensure they are executable
RUN npm install -g typescript vite
COPY frontend .
# Run build using global binaries
RUN tsc && vite build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/nginx/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
