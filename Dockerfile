# Menu & Inventory - container image for hosting.
#   docker build -t menu-inventory .
#   docker run -d -p 8000:8000 -v menu-data:/data --name menu-inventory menu-inventory
# All data (catalog, users, pictures, backups, Excel export) lives in the /data volume.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MENU_DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8000 \
    MENU_START_EMPTY=1

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

RUN useradd --create-home --uid 1000 menu && mkdir -p /data && chown menu:menu /data
USER menu
VOLUME ["/data"]
EXPOSE 8000
CMD ["python", "-m", "app.server"]
