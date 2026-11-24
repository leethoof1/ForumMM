FROM python:3.12-slim
WORKDIR /app
COPY server.py data.json ./
COPY public ./public
COPY tools/manage_codes.py ./tools/manage_codes.py
RUN useradd --uid 10001 --create-home forum && mkdir /state && chown forum:forum /state
USER forum
ENV FORUM_STATE_DIR=/state FORUM_SECURE_COOKIE=1
VOLUME /state
EXPOSE 8090
CMD ["python3", "server.py", "--port", "8090"]
