# Offline Bootstrap 5.3.8

Unmodified distribution assets from:

- https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css
- https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/js/bootstrap.bundle.min.js
- https://raw.githubusercontent.com/twbs/bootstrap/v5.3.8/LICENSE
- https://cdn.jsdelivr.net/npm/@popperjs/core@2.11.8/LICENSE.md

Bootstrap and bundled Popper retain their MIT licenses. `web_framework.py` verifies CSS/JS SHA-384 against the official Bootstrap 5.3 getting-started integrity values, embeds both licenses, and removes source-map comments only in the generated HTML. `.gitattributes` prevents Git newline conversion of the pinned files. Update hashes and regression tests deliberately when upgrading; no runtime downloads.
