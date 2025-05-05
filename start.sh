#!/bin/bash
apt-get update
apt-get install -y poppler-utils tesseract-ocr
python3 botcopy2.py
