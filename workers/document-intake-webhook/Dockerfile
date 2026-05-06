FROM node:22-slim

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY src/ src/

ENV NODE_ENV=production
ENV PORT=4010

EXPOSE 4010

CMD ["node", "src/index.js"]
