# Python 3.11 slim base image
FROM python:3.11-slim

# FFmpeg, Node.js (for yt-dlp JavaScript runtime) and other dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    libopus-dev \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create music, playlists and cookies directories
RUN mkdir -p /app/music /app/playlists /app/cookies

# Run the bot
CMD ["python", "bot.py"]
