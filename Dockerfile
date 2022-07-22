FROM python:3.9-slim-buster

RUN mkdir -p /etc/broadlink
WORKDIR /etc/broadlink

RUN groupadd -r -g 1000 broadlink && useradd -r -u 1000 -g broadlink broadlink
RUN chown -R broadlink:broadlink /etc/broadlink

COPY . /src
RUN pip install -r /src/requirements.txt

USER broadlink

VOLUME ["/etc/broadlink"]

ENV DATA_DIR="/etc/broadlink"

CMD python /src/app.py
