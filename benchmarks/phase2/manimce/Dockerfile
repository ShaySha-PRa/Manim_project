# Official Manim Community image, pinned to the contract's exact release.
FROM manimcommunity/manim:v0.20.1

WORKDIR /work
COPY scenes.py /work/scenes.py

# Keep the image's Manim entry point explicit; benchmark runs override it too.
ENTRYPOINT ["manim"]
