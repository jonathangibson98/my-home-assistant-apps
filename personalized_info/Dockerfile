ARG BUILD_FROM
FROM $BUILD_FROM
RUN apk add --no-cache python3 py3-aiohttp py3-yaml
COPY run.py index.html /
CMD ["python3", "/run.py"]
