FROM ubuntu:22.04

ARG DEBIAN_FRONTEND=noninteractive
ARG MANIM_TAG=v1.7.2

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    MESA_LOADER_DRIVER_OVERRIDE=llvmpipe

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    fonts-dejavu-core \
    fonts-liberation2 \
    git \
    latexmk \
    libcairo2-dev \
    libegl1-mesa \
    libgl1-mesa-dri \
    libgl1-mesa-glx \
    libosmesa6 \
    libpango1.0-dev \
    mesa-utils \
    pkg-config \
    python3 \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    texlive-fonts-recommended \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-science \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Install the fixed upstream release rather than a moving master checkout.
RUN git clone --branch "${MANIM_TAG}" --depth 1 \
        https://github.com/3b1b/manim.git /opt/manim \
    && test "$(git -C /opt/manim describe --tags --exact-match HEAD)" = "${MANIM_TAG}" \
    && python3 -m pip install --no-cache-dir /opt/manim

WORKDIR /benchmark

CMD ["manimgl", "--help"]
