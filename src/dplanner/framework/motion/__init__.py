"""Motion: what a surface that moves is made of, smooth and cheap.

``curves`` and ``particles`` are plain arithmetic — easings, tweens, springs, a breeze, a
Bézier, a particle system — so a model that moves is tested without a window. ``clock`` is
the one Qt driver, ticking at the display's rate only while its surface is seen, and ``draw``
the soft shapes and light a painter builds from them. Home's garden is the first user; the
canvas is the one it was shaped for (``docs/architecture/shell-ui.md``'s *Motion is a library*).
"""
