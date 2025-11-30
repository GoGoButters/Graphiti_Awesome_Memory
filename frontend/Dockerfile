FROM node:18-alpine as build

WORKDIR /app
COPY frontend/package.json .
RUN npm install
COPY frontend .
# Use npx to run tsc to avoid permission issues with local node_modules/.bin
RUN npx tsc && npx vite build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/nginx/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
