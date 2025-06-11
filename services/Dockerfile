# Use an official Python image
FROM python:3.12

# Set working directory
WORKDIR /app

# Copy requirements file and install dependencies

COPY latterpay/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your code
COPY . .

# Expose port (Flask default is 5000)
EXPOSE 5000

# Command to run your app
CMD ["python", "app.py"]
