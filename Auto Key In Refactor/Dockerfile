# Auto Key In Runner - Docker Image
# Build: docker build -t auto-key-in-runner .
# Run:   docker run -v ./data:/app/data -v ./configs:/app/configs --env-file .env auto-key-in-runner

FROM python:3.11-slim

# Install system deps for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libasound2 libpango-1.0-0 libcairo2 \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libgnutls30 libingress9 xvfb wget gnupg curl \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps from root
COPY pyproject.toml setup.py* ./
RUN pip install --no-cache-dir -e .

# Install Node.js deps
COPY runner/package.json runner/package-lock.json* runner/
WORKDIR /app/runner
RUN npm ci --only=production && npx playwright install chromium --with-deps

# Copy app files
WORKDIR /app
COPY app app/
COPY runner runner/
COPY configs configs/
COPY .env.example ./

# Create non-root user
RUN useradd -m -s /bin/bash runneruser && chown -R runneruser:runneruser /app
USER runneruser

ENV PYTHONUNBUFFERED=1

# Default: run with Xvfb (headless display)
ENTRYPOINT ["xvfb-run", "--auto-servernum", "-a", "python", "-m", "app"]