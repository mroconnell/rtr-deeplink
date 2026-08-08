# ffmpeg/ffprobe are system binaries, not pip packages -- Render's plain
# `runtime: python` buildpack isn't confirmed to include them (most don't),
# so this worker builds as a real Docker image instead, where installing
# them is explicit and verifiable rather than an assumption. Build context
# is the repo root (see render.yaml's `dockerContext: .`), not worker/ --
# this needs app/ and archive/ alongside worker/ itself, since worker/main.py
# imports both directly (see its module docstring for why).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY worker/requirements.txt worker/requirements.txt
RUN pip install --no-cache-dir -r worker/requirements.txt

COPY app app
COPY archive archive
COPY worker worker

CMD ["python", "-m", "worker.main"]
