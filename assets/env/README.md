# Environment map

`studio.env` is Babylon.js's stock studio environment, fetched once from
<https://assets.babylonjs.com/environments/studio.env> and vendored here.

It is a prefiltered `.env` cubemap (205 KB) and is loaded with
`BABYLON.CubeTexture.CreateFromPrefilteredData`. It provides the image-based
lighting the PBR fabric needs — the sheen term has nothing to reflect without an
environment, and sheen is the whole reason the shirt reads as cloth.

It is vendored rather than linked so the scene works offline, does not break if
Babylon reorganises their asset host, and keeps every asset under one root —
`playground.js` already loads everything else from this repo's raw GitHub URL.

Babylon.js and its assets are MIT licensed, © Microsoft Corporation.
