# Use the official lightweight Python 3.11 runtime
FROM python:3.11-slim

# Prevent Python from writing .pyc files to disk and enable unbuffered logging
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Install basic system build dependencies (required for compiling certain python package bindings)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file to install dependencies first (leverages Docker cache caching layer)
COPY requirements.txt /app/

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application source code into the container
COPY . /app/

# Expose the default port (for documentation, though dynamic ports are supported)
EXPOSE 8000

# Start the application using uvicorn. 
# We use a shell wrapper to support the dynamic $PORT environment variable provided by cloud hosts like Render/Heroku/Google Cloud.
# If $PORT is not defined, it defaults to 8000.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
