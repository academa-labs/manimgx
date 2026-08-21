# manimgx from PyPI, with a GPU to draw on: Mesa's lavapipe on the CPU, or the machine's GPU
# when the container is given one (--device /dev/dri for AMD and Intel, --gpus all for NVIDIA).
#
#   docker run --rm -v "$PWD:/work" ghcr.io/academa-labs/manimgx render scene.py
#
# Build a release with `just build-docker-image VERSION` (VERSION unset: the latest): this folder
# is its context, as it installs manimgx from PyPI.

# uv as a stage: Dependabot bumps FROM lines only
FROM ghcr.io/astral-sh/uv:0.12.19 AS uv
FROM python:3.14-slim-trixie

# Vulkan's loader and Mesa's drivers (lavapipe on the CPU; RADV, ANV, NVK on /dev/dri); NVIDIA's
# driver, which the NVIDIA Container Toolkit mounts in, needs libEGL and libXext to start
RUN apt-get update \
 && apt-get install -y --no-install-recommends libvulkan1 mesa-vulkan-drivers libegl1 libxext6 \
 && rm -rf /var/lib/apt/lists/*

# the python image ships its standard library without bytecode, and every run starts fresh
RUN python -m compileall -q /usr/local/lib

# VERSION unset: the latest release. uv is mounted for this step only
ARG VERSION
RUN --mount=from=uv,source=/uv,target=/bin/uv \
    uv pip install --system --no-cache --compile-bytecode "manimgx${VERSION:+==$VERSION}"

# NVIDIA's Vulkan driver comes with `graphics`, its shader compiler with `compute`; no
# __pycache__ in the mounted project; caches (Mesa's) where any --user can write
ENV NVIDIA_DRIVER_CAPABILITIES=all \
    PYTHONDONTWRITEBYTECODE=1 \
    XDG_CACHE_HOME=/tmp/.cache
WORKDIR /work
ENTRYPOINT ["manimgx"]
CMD ["--help"]
