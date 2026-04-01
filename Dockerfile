FROM python:3.11-slim

# Update Linux and install FFmpeg (Crucial for yt-dlp to merge video/audio)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Set working directory inside the container
WORKDIR /app

# Copy Python dependencies file
COPY requirements.txt .

# Install Python requirements
RUN pip install --no-cache-dir -r requirements.txt

# Copy the actual application files (server.py, index.html, etc)
COPY . .

# Run the Flask server via gunicorn with threading to allow concurrent downloads.
# Render dynamically passes the $PORT variable into the container.
CMD gunicorn -w 1 --threads 4 -b 0.0.0.0:$PORT server:app
