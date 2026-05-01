# RAIM Scope — Raspberry Pi Multi-Modal Microscope

A PyQt5 desktop application for the **Raspberry Pi 5 + Sense HAT 2 + Hailo-10H AI Processor** stack
that turns a low-cost USB microscope into a multi-modal imaging platform with onboard
AI cell-stage classification.

> **Reference:** Watanabe et al. (2020). *Low-cost multi-modal microscope using Raspberry Pi*. **Optik**, 212, 164713.

## Highlights

- **Multi-modal illumination** via Sense HAT 2 LED matrix (BF / DF / OBL / variable DF / DPC)
- **NA-matched dark-field** annulus pattern for Olympus 10× NA 0.25 onion samples
- **Hailo-10H AI inference** — YOLOv8/v11 (NMS-postprocess HEF) at 30+ FPS
- **In-app dataset labeling pipeline** — ROI → COCO JSON → YOLO export (train/val auto-split)
- **Active learning loop** — AI predictions become editable labels in 1 click
- **Anti-flicker camera control** — manual exposure + power-line frequency for LED PWM banding
- **Auto camera classification** — microscope vs general USB webcam profiles
- **Korean UI** with 3 selectable themes (blue / light / black)

## Architecture

```
app/
├── main.py                    # Qt entry point
├── ai/                        # Hailo-10H inference (YOLO NMS-postprocess)
│   ├── hailo_inference.py
│   └── inference_worker.py
├── capture/
│   └── camera_worker.py       # V4L2 + auto-classification + control sliders
├── dataset/                   # Phase 17 — labeling pipeline
│   ├── coco_writer.py         # COCO JSON read/write
│   ├── yolo_writer.py         # YOLO format + train/val 80/20 split
│   └── dataset_manager.py     # Onion mitosis 5 classes
├── imaging/                   # Sense HAT 2 LED patterns
├── ui/
│   ├── main_window.py         # 4-tab layout (Live / Dataset / Detect / Archive)
│   ├── live_view.py           # Camera canvas + ROI + AI/pending overlays
│   ├── dataset_panel.py       # Label collection + YOLO export UI
│   ├── detect_panel.py        # AI inference + per-class statistics
│   ├── camera_panel.py        # V4L2 control sliders
│   └── ...
├── util/
│   └── image_convert.py
└── docs/
    ├── RAIM_Scope_Development_Report.html  # Phase 1–18 report
    └── onion_mitosis_train.ipynb           # Colab training notebook
```

## Pipeline (5-step workflow)

1. **Observe** — Live tab, multi-modal illumination, ROI selection
2. **Label** — Dataset tab, choose mitosis stage, save COCO sample
3. **Export** — One-click YOLO format with auto train/val 80/20 split
4. **Train** — `app/docs/onion_mitosis_train.ipynb` on Google Colab → `best.pt` + `best.onnx`
5. **Deploy** — Hailo Compiler (`onnx → hef`) → drop in `models/` → Detect tab

## Onion Mitosis Classes

| ID | English   | Korean |
|----|-----------|--------|
| 0  | interphase| 간기   |
| 1  | prophase  | 전기   |
| 2  | metaphase | 중기   |
| 3  | anaphase  | 후기   |
| 4  | telophase | 말기   |

## Setup (Raspberry Pi 5 / Debian Trixie)

```bash
sudo apt install -y python3-pyqt5 python3-opencv python3-numpy sense-hat \
                    python3-venv python3-pip
uv venv --system-site-packages .venv
.venv/bin/python -m app.main
```

## Setup (Windows / macOS dev)

```bash
uv pip install -r requirements.txt
python -m app.main
```

> `sense-hat` is Pi-only and gracefully degrades on dev machines.

## Documentation

- **`app/docs/RAIM_Scope_Development_Report.html`** — Complete Phase 1–18 development report
- **`app/docs/onion_mitosis_train.ipynb`** — Colab YOLOv8 training notebook
- **`app/docs/Low-cost multi-modal microscope using Raspberry Pi.pdf`** — Reference paper

## License

Research / educational use. Hailo SDK and HEF compilation require Hailo Developer Zone access.
