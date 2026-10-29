# Vendored front-end libraries

Served from `/static/`, so the web app needs no CDN. Each comes from its npm
tarball, checked against the registry's `sha512` integrity hash.

| Directory | Package | Files | Licence |
|---|---|---|---|
| `alpine-csp-3.17.5/` | `@alpinejs/csp@3.17.5` | `dist/module.esm.min.js` | MIT |
| `bootstrap-5.3.8/` | `bootstrap@5.3.8` | `dist/css/bootstrap.min.css`, `dist/js/bootstrap.bundle.min.js` | MIT (`LICENSE`) |

To upgrade, fetch the new tarball from `https://registry.npmjs.org/<package>/<version>`,
check its `dist.integrity`, copy the same files into a new versioned directory,
and update the paths in `templates/base.html`.
