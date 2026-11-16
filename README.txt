RINGBLAST - design of ring / fan blast patterns (sublevel stoping)

HOW TO USE (end user)
  1. Double-click  RingBlast.bat  (the first time it sets up its own environment: 2-5 minutes, internet needed).
  2. Optional: double-click  "Create Desktop Shortcut.bat"  to get a RingBlast icon (no black console window)
     on the Desktop and in the Start menu. From then on start the program from that icon.
  3. In the program: draw the stope in the "Stope layout" tab (drift position: centre / left / right), then in
     "Blast design" choose rock and explosive, press "Run design", then "Export...".
     Files are saved in  output\  : DXF (AutoCAD), hole CSV, JSON and a printable HTML report.

TABS
  Stope layout      stope geometry, drift positions (horizontal, and height inside the sublevel) and optional
                    arched roof, one or two (symmetric) drifts per sublevel, drawn live
  Blast design      rock, explosive and parameters, then "Run design" (pattern, fragmentation, totals)
  Rock properties   editable rock table (add rows, edit values, add your own parameters, reset to the original data)
  Explosives        editable explosive table, same functions
  Muck-pile photos  load photos of the blasted muck pile, set the scale (click two points of a known length),
                    note date / location / remarks, measure the fragment size distribution and compare it with
                    the Kuz-Ram prediction of the design.
                    The Segmentation panel tunes the detection: contrast, gamma, smoothing, threshold (adaptive /
                    Otsu / fixed), light-or-dark fragments, erode / open / close, with a live preview of the
                    processing stages (grey image, boundaries) and the fragments.
  Settings          colours, background, fonts and sizes of all plots; switch to turn the help tooltips off
  Help menu         User manual (F1) and About (version, authors, how to cite)
  Project bar       project name and notes, Open / Save project, Reset (default inputs).
                    A project file stores the inputs, the rock and explosive rows used (and all you added or
                    modified), the photo records with ALL their settings (scale, smallest fragment, sensitivity and every
                    segmentation parameter, per photo, plus the values used for the stored results) AND THE PHOTOS THEMSELVES with their measurements: one single
                    file (*.ringblast) that you can copy to another computer and open there.
                    Photos are extracted to ~/.ringblast/project_images when a project is opened.

WHAT IS CALCULATED
  One ring pattern for every drift level: the n sublevel drifts (rectangular blocks) plus the base drift
  (trapezoidal block above the hopper). Each drift can be central or at the side of the stope.

FOLDERS
  src\ringblast   code (calculation engine, GUI, command line)
  database        rocks and explosives (editable CSV files)
  examples        numerical examples (JSON) and their results in examples\output
  figures         figures for the paper (regenerate with tools\make_figures.py; the icon with tools\make_icon.py);
                  figures\screenshots = GUI screenshots (tools\make_screenshots.py, add --photo FILE to use a real photo)
  docs            design notes (DESIGN.md)
  tests           automatic tests (pytest)
  tools           conversion of the legacy Excel data, figure generation
  launcher        icon and script to build a stand-alone executable (no Python needed)
