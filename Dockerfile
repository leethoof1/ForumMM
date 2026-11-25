FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
WORKDIR /app
COPY server.py polls.py data.json ./
COPY public ./public
COPY tools ./tools
RUN useradd --uid 10001 --create-home forum && mkdir /state && chown forum:forum /state
USER forum
ENV FORUM_STATE_DIR=/state FORUM_SECURE_COOKIE=1
VOLUME /state
EXPOSE 8090
CMD ["python3", "server.py", "--port", "8090"]
