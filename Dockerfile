# Equipment Finder web app: builds web/ and serves it with the API on one port.
# Secrets (GEMINI_API_KEY etc.) come from the host's environment variables, never from the image.

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-web.txt
COPY *.py ./
COPY api/ api/
COPY data/ data/
COPY --from=web /web/dist web/dist
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT}"]
