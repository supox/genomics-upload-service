# File Upload Service

A lightweight service that watches local folders and uploads files to Amazon S3 with resumable multipart support.

This repository is a home assignment for **Ultima Genomics**; functional and non-functional requirements are detailed in [REQUIREMENTS.md](doc/REQUIREMENTS.md).

## 📚 Documentation

- High-level design: [ARCHITECTURE.md](doc/ARCHITECTURE.md)

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- (Optional) Python 3.11+ for local development

### Start with Docker Compose
```bash
# Clone & launch
git clone <repository-url>
cd file-upload-service
docker-compose up -d     # API → http://localhost:8000
```
LocalStack S3 is available at http://localhost:4566.

### Local Development
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# (Optional) start LocalStack in a second terminal
# docker run --rm -it -p 4566:4566 localstack/localstack:2.3
export AWS_ENDPOINT_URL=http://localhost:4566
python -m src.main
```

## 🧑‍💻 Running Tests
```bash
# Run entire suite
python run_tests.py

# Smoke / category examples
python run_tests.py --smoke
pytest -m "e2e"
```

## ⚙️ Configuration
Key environment variables (defaults shown):

|      Variable        |            Default             |            Purpose            |
|----------------------|-------------------------------|--------------------------------|
| DATABASE_URL         | sqlite:///./data/uploads.db   | SQLite database location       |
| AWS_ENDPOINT_URL     | http://localhost:4566         | S3 endpoint (LocalStack)       |
| CHUNK_SIZE           | 5242880                       | Multipart chunk size (bytes)   |
| WORKER_CONCURRENCY   | 5                             | Parallel uploads               |

See `doc/ARCHITECTURE.md` for the full list.
