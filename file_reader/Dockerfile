FROM python:3.11-alpine

WORKDIR /usr/src/app

RUN pip install --no-cache-dir flask paho-mqtt requests

COPY app /usr/src/app/app
COPY run.sh /run.sh

RUN chmod +x /run.sh

CMD [ "/run.sh" ]
