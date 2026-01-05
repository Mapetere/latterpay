# =============================================================================
# LatterPay Dockerfile
# =============================================================================
# Production-ready Docker configuration with multi-stage build
# =============================================================================

# Stage 1: Build environment
FROM python:3.11-slim as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install requirements
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt


# Stage 2: Production environment
FROM python:3.11-slim as production

# Labels
LABEL maintainer="Nyasha Mapetere <mapeterenyasha@gmail.com>" \
    version="2.1.0" \
    description="LatterPay WhatsApp Payment Service"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8010 \
    APP_HOME=/app

# Create non-root user for security
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set up application directory
WORKDIR $APP_HOME

# Copy application code
COPY --chown=appuser:appgroup . .

# Create necessary directories
RUN mkdir -p logs && \
    chown -R appuser:appgroup $APP_HOME

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Expose port
EXPOSE ${PORT}

# Run with Gunicorn
CMD ["gunicorn", "app:latterpay", \
    "--bind", "0.0.0.0:8010", \
    "--workers", "4", \
    "--threads", "4", \
    "--worker-class", "gthread", \
    "--worker-tmp-dir", "/dev/shm", \
    "--timeout", "120", \
    "--keep-alive", "5", \
    "--log-level", "info", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "--capture-output"]
