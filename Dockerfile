FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p uploads data

# SaliBot: run as a normal user (id 1000), not root, as Hugging Face Spaces
# requires and as is safer on any host. That user must own the folders SaliBot writes to (data/, uploads/, chroma_db/)
RUN useradd -m -u 1000 user && mkdir -p chroma_db && chown -R user:user /app
USER user
ENV HOME=/home/user

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
