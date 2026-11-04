# Scientific methods and validation scope

## Input and distance model

Trendsmapp accepts explicit long or wide spatial tables. Timestamps become UTC
ISO 8601 values; coordinates and measurements must be finite and geographically
valid. Malformed non-blank cells reject the upload, while blank wide-format
measurements represent unsampled combinations.

Regional distances use an equirectangular kilometre projection:
`x = longitude * 111.320 * cos(reference latitude)` and
`y = latitude * 110.574`. This approximation is intended for compact regional
domains, not global or antimeridian-spanning studies.

## IDW

The IDW estimate is `sum(w_i z_i) / sum(w_i)`, with
`w_i = 1 / max(distance_i, 1e-9)^p`. Exact station matches return the observed
value. Colocated observations are averaged first. Power is limited to 0.1-5.0.

## KDE kernel smoother

The KDE option is a Gaussian kernel-weighted mean, also called a
Nadaraya-Watson smoother. With bandwidth `h` kilometres,
`w_i = exp(-distance_i^2 / (2 h^2))` and the predicted measurement is
`sum(w_i z_i) / sum(w_i)`. Bandwidth is limited to 0.1-100 km.

This is not an unweighted probability-density estimate of sampling locations.
It smooths measurement values and preserves their units. Larger bandwidths
produce broader, less locally variable surfaces. If all weights underflow, the
nearest colocated aggregate is used.

## Boundary, rendering, and animation

Only non-empty Polygon and MultiPolygon boundaries are accepted. Invalid
geometries are repaired only when a zero-width buffer yields a valid non-empty
result. Cells outside the boundary are missing. PNGs use one global range and
include geographic bounds for correct placement.

Animations compute one IDW or KDE surface per observed timestamp and linearly
interpolate adjacent complete surfaces. Transition frames are distributed
proportionally to the real elapsed time between observations using
deterministic largest-remainder rounding, with a minimum of one frame per
interval; playback speed therefore reflects actual sampling gaps instead of
treating every interval identically. Interpolated frames are estimates, not
observations, and are labelled. Response headers record the spatial method,
method parameter, temporal method, and CPU execution location.

## Client graphics behavior

MapLibre uses WebGL2 only to display boundaries, stations, and georeferenced
scientific PNGs. No heatmap calculation runs on the client GPU. Without WebGL2,
the IDW/KDE PNG is displayed as a normal image; generation, animation, copying,
and downloading remain available.

## Automated checks

Tests cover parser corruption, spatial roles, timestamps, finite values,
coordinate bounds, boundary masking, IDW exact matches, KDE bounds and
bandwidth sensitivity, PNG/MP4 signatures for both methods, session isolation,
database transactions, OpenAPI, and example checksums.
