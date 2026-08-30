# frontend/Dockerfile
# 1단계: 빌드 환경
# vite 8 / @vitejs/plugin-react 6 은 node ^20.19.0 || >=22.12.0 을 요구한다.
# node 18 에서는 vite CLI 가 CustomEvent(전역, node 19+) 를 쓰다가 빌드가 실패한다.
FROM node:22-alpine AS build
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
