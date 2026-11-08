FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HLTV_DB=/data/hltv.sqlite3
WORKDIR /app
COPY pyproject.toml ./
COPY hltv_api ./hltv_api
RUN pip install --no-cache-dir '.[server]' \
    && groupadd --gid 10001 hltv \
    && useradd --uid 10001 --gid hltv --no-create-home hltv \
    && mkdir /data && chown hltv:hltv /data
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--access-logfile", "-", "hltv_api.wsgi:application"]
