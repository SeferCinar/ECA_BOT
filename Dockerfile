# Python 3.11 slim base image
FROM python:3.11-slim

# FFmpeg and other dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    libopus-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create music and playlists directories
RUN mkdir -p /app/music /app/playlists

# Run the bot
CMD ["python", "bot.py"]
