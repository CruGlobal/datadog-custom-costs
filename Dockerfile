# PYTHON_VERSION set by build.sh based on .tool-versions file
ARG PYTHON_VERSION=3.13.11
FROM python:${PYTHON_VERSION}-alpine

# Set environment variables to prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /usr/src/app

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Make entrypoint script executable
RUN chmod +x entrypoint.sh

# Run as non-root user for security
RUN adduser -D -u 1000 appuser && chown -R appuser:appuser /usr/src/app
USER appuser

ENTRYPOINT ["./entrypoint.sh"]
