# StreamCopy EXP 0.7.1

StreamCopy is a separate experimental local-copy engine; the regular Commander is unchanged.

A folder is scanned once into a manifest and then streamed through a bounded producer/consumer RAM queue. Destination objects remain normal filesystem files; no raw-sector writer or proprietary storage format is used.

Source and destination media types are selected manually (HDD, SSD/NVMe, flash) and are locked for the duration of a job. Transport is a separate hint (Internal, USB2, USB3.x, USB4/Thunderbolt, Unknown), so two HDDs attached over USB3 still use the HDD→HDD sequential profile.

USB topology can be marked unknown, shared hub/controller, or separate paths/controllers. Drive cache sizes are optional hints and are not treated as RAM queue sizes. The 32 MiB → 128 MiB HDD test pair uses an 8 MiB chunk and a bounded queue chosen from cache/topology hints.

StreamCopy uses the existing FILE WRITE gate. Existing destination files are skipped with warnings rather than overwritten. This first experimental release does not provide Move, SFTP, restart persistence, extent ordering, or raw placement.
