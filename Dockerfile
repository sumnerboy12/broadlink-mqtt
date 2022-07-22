FROM python:3.10

RUN mkdir -p /opt/broadlink
RUN mkdir -p /var/log/broadlink

WORKDIR /opt/broadlink
COPY . /opt/broadlink

RUN pip install -r /opt/broadlink/requirements.txt

RUN groupadd -r broadlink && useradd -r -g broadlink broadlink
RUN chown -R broadlink:broadlink /opt/broadlink
RUN chown -R broadlink:broadlink /var/log/broadlink

USER broadlink

VOLUME ["/opt/broadlink"]
ENV DATA_DIR="/opt/broadlink"

CMD python app.py
