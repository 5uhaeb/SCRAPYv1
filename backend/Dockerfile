# Use an official lightweight Python image.
# https://hub.docker.com/_/python
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create and change to the app directory.
WORKDIR /app

# Copy requirement files first to leverage Docker cache
COPY requirements.txt ./

# Install dependencies.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Run the web service on container startup.
# Koyeb and other PaaS often provide a PORT environment variable. We default to 8000.
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
