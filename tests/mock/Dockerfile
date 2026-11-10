FROM python:3.12.11-alpine3.22@sha256:efcdfa6a6b2fd2afb9c7dfa9a5b288a6f68338b5cfdebe6b637d986067d85757
WORKDIR /mock
COPY server.py /mock/server.py
USER 1000:1000
ENTRYPOINT ["python3", "/mock/server.py"]
