# This Dockerfile sets up an XBlock SDK environment for developing and testing XBlocks.
# The following commands in the Makefile facilitate the Docker lifecycle:
# - `make dev.clean`: Cleans up any existing Docker containers and images.
# - `make dev.build`: Builds the Docker image for the XBlock SDK environment.
# - `make dev.run`: Cleans, builds, and runs the container, mapping the local project directory.

FROM openedx/xblock-sdk:latest

WORKDIR /usr/local/src/xblocks-contrib
VOLUME ["/usr/local/src/xblocks-contrib"]

RUN apt-get update && apt-get install -y \
    gettext \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY . /usr/local/src/xblocks-contrib/

RUN pip install -r requirements/dev.txt && pip install --force-reinstall -e .
RUN make compile_translations

ENTRYPOINT ["bash", "-c", "python /usr/local/src/xblock-sdk/manage.py migrate && exec python /usr/local/src/xblock-sdk/manage.py runserver 0.0.0.0:8000"]
EXPOSE 8000
