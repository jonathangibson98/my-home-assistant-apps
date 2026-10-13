FROM ghcr.io/home-assistant/base:latest

# Install python and dependencies
RUN apk add --no-cache python3 py3-pip py3-cryptography py3-pydantic

WORKDIR /app
COPY . /app

RUN chmod a+x /app/run.sh

CMD ["/app/run.sh"]
