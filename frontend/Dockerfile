# frontend/Dockerfile
# 1단계: 빌드 환경
FROM node:18-alpine as build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# 2단계: Nginx 서빙 환경
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# 우리가 작성할 커스텀 Nginx 설정 덮어쓰기
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
