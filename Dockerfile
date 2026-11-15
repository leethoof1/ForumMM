FROM python:3.12-slim
WORKDIR /app
COPY server.py data.json ./
COPY public ./public
RUN useradd --uid 10001 --create-home forum && mkdir /state && chown forum:forum /state
USER forum
ENV FORUM_STATE_DIR=/state FORUM_SECURE_COOKIE=1
VOLUME /state
EXPOSE 8000
CMD ["python3", "server.py", "--port", "8000"]
