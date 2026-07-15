# Lightweight Dockerfile for deploying StudySpring
# (Optional; Procfile is enough for many platforms.)

FROM python:3.11-slim

WORKDIR /app

# System deps for PyMuPDF (fitz)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501

# Bind to 0.0.0.0 so the platform can reach the server
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]

