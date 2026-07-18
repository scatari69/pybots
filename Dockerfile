# Pull the compiled simc binary + bundled profiles straight out of the
# official nightly image instead of building SimulationCraft from source
# ourselves. That image is Alpine-based (see its Dockerfile in
# simulationcraft/simc), so we stay on python:3.12-alpine to keep the same
# musl libc the binary was linked against.
FROM simulationcraftorg/simc:latest AS simc

FROM python:3.12-alpine

# libcurl/libgcc/libstdc++ are simc's runtime deps, mirroring the base layer
# of the official image.
RUN apk add --no-cache libcurl libgcc libstdc++

COPY --from=simc /app/SimulationCraft/simc /usr/local/bin/simc
COPY --from=simc /app/SimulationCraft/profiles /app/profiles
ENV SIMC_BINARY=/usr/local/bin/simc

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV SIMCBOTS_DATA_DIR=/app/data
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
