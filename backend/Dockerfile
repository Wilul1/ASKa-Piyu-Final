FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ASKA_DATABASE_INIT_ON_STARTUP=false

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install CPU-only torch/torchvision first (must come from the same index so
# their ABIs match, otherwise torchvision's compiled ops fail to load): the
# default PyPI wheel pulls several GB of NVIDIA CUDA libraries that this API
# image never uses (no GPU at runtime), which can exhaust disk on small VPS
# hosts. sentence-transformers/easyocr below then reuse these already-
# satisfied packages instead of pulling mismatched GPU builds.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Single worker: local Chroma PersistentClient + in-process rate limits are not
# safe across multiple uvicorn workers sharing one SQLite/chroma directory.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]
