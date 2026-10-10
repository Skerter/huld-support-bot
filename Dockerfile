FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /usr/src/app
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
    && groupadd --gid 10001 support \
    && useradd --uid 10001 --gid support --no-create-home support
COPY --chown=support:support app ./app
COPY LICENSE ./LICENSE
USER 10001:10001
CMD ["python", "-m", "app"]
