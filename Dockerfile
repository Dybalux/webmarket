FROM python:3.13.7-alpine


ARG ENVIRONMENT=development

ENV TZ=America/Argentina/Buenos_Aires \
    PIP_DEFAULT_TIMEOUT=100 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYDEVD_DISABLE_FILE_VALIDATION=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

ADD requirements.txt requirements.txt
ADD Aptfile Aptfile

RUN apk add --no-cache $(cat Aptfile)


RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt


COPY . /app/

# Run as non-root user (F-012)
RUN adduser -D -g '' appuser && \
    chown -R appuser:appuser /app
USER appuser

CMD ["python3", "main.py"]
