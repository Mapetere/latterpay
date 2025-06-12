# Use an official Python image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements file and install dependencies

COPY requirements.txt .
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends gcc && \
	pip install --no-cache-dir -r requirements.txt && \
	apt-get purge -y --auto-remove gcc && \
	rm -rf /var/lib/apt/lists/*

# Copy the rest of your code
COPY . .

# Expose port (Flask default is 5000)
EXPOSE 8080

# Command to run your app
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "app:app"]

