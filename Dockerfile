ARG NODE_IMAGE=node:24.11.1-bookworm-slim
ARG PYTHON_IMAGE=python:3.11.13-slim

FROM ${NODE_IMAGE} AS frontend
ARG NPM_REGISTRY=https://registry.npmmirror.com
WORKDIR /build/client
COPY client/package.json client/package-lock.json ./
RUN npm ci --registry="$NPM_REGISTRY"
COPY client/ ./
COPY agent_platform/static/trace-format.js agent_platform/static/trace-format.d.ts /build/agent_platform/static/
RUN npm run build

FROM ${PYTHON_IMAGE} AS runtime
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements-platform*.txt ./
RUN python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements-platform-m6.txt
RUN groupadd --gid 10001 maths && useradd --uid 10001 --gid maths --create-home maths \
    && mkdir -p /var/lib/maths/rag && chown -R maths:maths /var/lib/maths
COPY agent_platform/ agent_platform/
COPY --from=frontend /build/agent_platform/static/chat/ agent_platform/static/chat/
COPY reasoning_agent/ reasoning_agent/
COPY skill2_en/ skill2_en/
COPY skill2/ skill2/
COPY deployment_bootstrap.py llm_client.py ./
USER maths
CMD ["python", "-m", "agent_platform.deployment", "api"]

FROM runtime AS rag
USER root
RUN python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements-platform-m5.txt
USER maths

FROM runtime AS web
ARG TORCH_INDEX_URL=https://mirror.sjtu.edu.cn/pytorch-wheels/cpu
USER root
RUN python -m pip install --no-cache-dir torch --index-url "$TORCH_INDEX_URL" \
    && python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements-platform-m5.txt
COPY --chown=maths:maths strategy_data/ strategy_data/
RUN chown -R maths:maths /app/skill2_en
USER maths
EXPOSE 8000
CMD ["python", "-m", "agent_platform", "--host", "0.0.0.0", "--port", "8000", "--runtime", "langgraph", "--client-provider", "deployment_bootstrap:provided_client", "--function-calling", "off", "--question-dir", "/var/lib/maths/questions"]
