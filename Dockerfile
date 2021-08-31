# Container image that runs your code.
# NOTE: Could speed things up if you use an existing image with all the
#       deps pre-installed but still not as fast as TypeScript.
FROM ubuntu:20.04

RUN apt-get update \
    && apt-get install -y \
    build-essential \
    python3-pip \
    python3.8 \
    git \
    && python3 -m pip install --upgrade pip \
    && python3 -m pip install --upgrade setuptools \
    && python3 -m pip install --upgrade wheel \
    && python3 -m pip install humanize \
    && python3 -m pip install python-dateutil \
    && python3 -m pip install PyGithub

# Copies code file action repository to the filesystem path `/` of the container
COPY entrypoint.sh /entrypoint.sh

COPY stale_issues.py /stale_issues.py
COPY stale_pull_requests.py /stale_pull_requests.py

# Code file to execute when the docker container starts up (`entrypoint.sh`)
ENTRYPOINT ["/entrypoint.sh"]
