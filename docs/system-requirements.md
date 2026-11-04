# System configuration criteria

## Server and container

| Criterion | Minimum baseline | Effect when unmet |
|---|---:|---|
| CPU | 2 logical cores | IDW/KDE and MP4 export remain valid but may be slow |
| Memory | 4 GB available | reduce stations or animation frames |
| Disk | 2 GB free plus data | uploads or temporary encoding may fail |
| Python | 3.10.x | use Docker when an exact runtime is unavailable |
| Docker | Engine 24+ and Compose v2 | use Python/Uvicorn instead |

IDW and KDE execute on the server CPU and never require a client GPU. Server
limits cap uploads, normalized observations, timestamps, stations per surface,
and animation frames.

## Client map gate

The interactive MapLibre canvas is enabled only when its local asset loads and
the browser creates WebGL2 with `failIfMajorPerformanceCaveat: true`. Renderer
identity disclosure is optional when context creation succeeds.

Without WebGL2, station and boundary interaction is disabled. The server still
generates IDW/KDE PNGs and MP4s, and the page displays scientific PNGs as normal
images. Graphics hardware is therefore not a scientific-computation requirement.

## Pipeline matrix

| Pipeline | Execution | Client GPU | Semantics | Output |
|---|---|---:|---|---|
| IDW surface | server CPU | no | projected inverse-distance weighted mean | georeferenced PNG |
| KDE surface | server CPU | no | Gaussian kernel-weighted mean, bandwidth in km | georeferenced PNG |
| IDW animation | server CPU | no | IDW plus linear surface interpolation | H.264 MP4 |
| KDE animation | server CPU | no | KDE plus linear surface interpolation | H.264 MP4 |
| Interactive map | client WebGL2 | yes | display only; no heatmap calculation | canvas |
