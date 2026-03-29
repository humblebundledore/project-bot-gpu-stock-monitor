FROM python:3.12-slim

# System deps for lxml + Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    gnupg \
    ca-certificates \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgtk-3-0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy source and package files
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install Python deps (non-editable for production correctness)
RUN pip install --no-cache-dir ".[dev]"

# Install Playwright browser
RUN playwright install chromium

# Copy config
COPY config/ ./config/

# Create data and log directories
RUN mkdir -p data logs/screenshots

# Non-root user for security
RUN useradd -m -u 1000 monitor && chown -R monitor:monitor /app
USER monitor

ENV GPU_MONITOR_CONFIG=/app/config/config.yaml
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["gpu-monitor"]
CMD ["run-daemon"]
