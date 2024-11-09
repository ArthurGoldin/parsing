# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variable to avoid some issues in headless mode
ENV DEBIAN_FRONTEND=noninteractive

# Set the working directory in the container
WORKDIR /app

# Install dependencies including curl, wget, unzip, and Xvfb
RUN apt-get update && apt-get install -y wget gnupg ca-certificates curl unzip xvfb

# Install Google Chrome
RUN wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
RUN apt install -y ./google-chrome-stable_current_amd64.deb

# Install Chromedriver
RUN wget -q "https://chromedriver.storage.googleapis.com/$(curl -s chromedriver.storage.googleapis.com/LATEST_RELEASE)/chromedriver_linux64.zip" -O /tmp/chromedriver.zip \
    && unzip /tmp/chromedriver.zip -d /usr/local/bin/ \
    && rm /tmp/chromedriver.zip \
    && chmod +x /usr/local/bin/chromedriver

# Verify installation of Chrome and Chromedriver
RUN google-chrome --version || (echo 'Google Chrome was not installed' && exit 1)
RUN chromedriver --version || (echo 'Chromedriver was not installed' && exit 1)

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY app/ /app

# Copy the entrypoint script and set it as executable
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Set the entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]

CMD ["python3", "system_check.py"]
