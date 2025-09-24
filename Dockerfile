# Use Ubuntu 20.04 as base image
FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt update && apt install -y \
    build-essential \
    git \
    python3-dev \
    python3-pip \
    && apt clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install requests ujson graphviz ply pytest atomicwrites more-itertools pluggy py attrs setuptools six django pycparser sympy

RUN git clone https://github.com/ispras/cv.git /cv

WORKDIR /cv

RUN make install DEPLOY_DIR=/deploy

WORKDIR /deploy
